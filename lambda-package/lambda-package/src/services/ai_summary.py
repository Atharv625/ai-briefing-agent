"""
services/ai_summary.py - AI summarization using Google Gemini (primary)
with OpenAI as fallback.

Architecture:
  - AbstractAIProvider: interface for any LLM backend
  - GeminiProvider: Google Gemini 1.5 Flash implementation
  - OpenAIProvider: OpenAI GPT-4o-mini fallback
  - AIOrchestrator: tries primary, falls back gracefully
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import List, Optional

import google.generativeai as genai

from src.config import get_settings
from src.logger import get_logger
from src.prompts.briefing_prompt import (
    SYSTEM_PROMPT,
    build_briefing_prompt,
    build_categorization_prompt,
)
from src.services.calendar_service import CalendarEvent, ConflictInfo
from src.services.gmail_service import EmailItem
from src.services.tasks_service import TaskItem, TaskSummary
from src.utils.retry import with_retry

logger = get_logger(__name__)


# ── Abstract Provider Interface ────────────────────────────────────────────────

class AbstractAIProvider(ABC):
    """
    Interface for AI providers.
    New providers (Claude, Cohere, etc.) implement this and drop in.
    """

    @abstractmethod
    async def generate(self, system: str, user: str) -> str:
        """Generate a response given system and user messages."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        ...


# ── Gemini Provider ────────────────────────────────────────────────────────────

class GeminiProvider(AbstractAIProvider):
    """
    Google Gemini 1.5 Flash — fast, cheap, multimodal.
    Uses the google-generativeai SDK (synchronous calls run in executor).
    """

    def __init__(self):
        self.settings = get_settings()
        self._initialized = False

    def _ensure_init(self):
        if not self._initialized:
            genai.configure(api_key=self.settings.gemini_api_key)
            self._model = genai.GenerativeModel(
                model_name=self.settings.gemini_model,
                system_instruction=SYSTEM_PROMPT,
                generation_config=genai.types.GenerationConfig(
                    temperature=self.settings.gemini_temperature,
                    max_output_tokens=self.settings.gemini_max_tokens,
                ),
            )
            self._initialized = True

    def is_available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    @with_retry(max_attempts=3, backoff=2.0)
    async def generate(self, system: str, user: str) -> str:
        """
        Generates text using Gemini.
        The system prompt is baked into the model at init time.
        Runs blocking SDK call in thread pool to not block event loop.
        """
        self._ensure_init()
        loop = asyncio.get_event_loop()

        def _call():
            response = self._model.generate_content(user)
            return response.text

        logger.info("Sending request to Gemini (%s)...", self.settings.gemini_model)
        result = await loop.run_in_executor(None, _call)
        logger.info("Gemini response received (%d chars).", len(result))
        return result


# ── OpenAI Provider (Fallback) ─────────────────────────────────────────────────

class OpenAIProvider(AbstractAIProvider):
    """
    OpenAI GPT-4o-mini fallback.
    Only activated if Gemini fails AND openai_api_key is set.
    """

    def __init__(self):
        self.settings = get_settings()

    def is_available(self) -> bool:
        return bool(self.settings.openai_api_key)

    @with_retry(max_attempts=2, backoff=3.0)
    async def generate(self, system: str, user: str) -> str:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.settings.openai_api_key)
            response = await client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=self.settings.gemini_max_tokens,
                temperature=self.settings.gemini_temperature,
            )
            return response.choices[0].message.content or ""
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )


# ── AI Orchestrator ────────────────────────────────────────────────────────────

class AIOrchestrator:
    """
    Manages multiple AI providers with automatic fallback.
    Primary: Gemini → Fallback: OpenAI → Error if both fail.
    """

    def __init__(self):
        self.settings = get_settings()
        self._providers: List[AbstractAIProvider] = []
        self._init_providers()

    def _init_providers(self):
        gemini = GeminiProvider()
        if gemini.is_available():
            self._providers.append(gemini)
            logger.info("Gemini provider registered.")

        openai_prov = OpenAIProvider()
        if openai_prov.is_available():
            self._providers.append(openai_prov)
            logger.info("OpenAI fallback provider registered.")

        if not self._providers:
            raise RuntimeError(
                "No AI providers configured. Set GEMINI_API_KEY or OPENAI_API_KEY."
            )

    async def generate_briefing(
        self,
        emails: List[EmailItem],
        events: List[CalendarEvent],
        conflicts: List[ConflictInfo],
        tasks: List[TaskItem],
        task_summary: TaskSummary,
    ) -> str:
        """
        Generates the complete morning briefing.
        Tries each provider in order, returns first success.
        Includes emails, calendar events, and pending tasks.
        """
        user_prompt = build_briefing_prompt(
            emails,
            events,
            conflicts,
            tasks,
            task_summary,
        )

        for provider in self._providers:
            try:
                logger.info(
                    "Attempting briefing generation with %s...",
                    provider.__class__.__name__,
                )
                result = await provider.generate(SYSTEM_PROMPT, user_prompt)
                return self._post_process(result)
            except Exception as exc:
                logger.warning(
                    "%s failed: %s. Trying next provider...",
                    provider.__class__.__name__,
                    exc,
                )

        raise RuntimeError("All AI providers failed to generate briefing.")

    async def categorize_email(self, email: EmailItem) -> dict:
        """
        Enhanced AI-based email categorization.
        Returns structured JSON with category + extracted metadata.
        Falls back to rule-based category if AI fails.
        """
        prompt = build_categorization_prompt(email)
        for provider in self._providers:
            try:
                raw = await provider.generate("", prompt)
                # Strip markdown fences if present
                clean = raw.strip().removeprefix("```json").removesuffix("```").strip()
                return json.loads(clean)
            except Exception as exc:
                logger.debug("Categorization failed: %s", exc)

        # Fallback: return the rule-based category
        return {
            "category": email.category,
            "action_required": email.is_urgent,
            "follow_up_needed": False,
            "deadline_mentioned": None,
            "task_summary": None,
        }

    @staticmethod
    def _post_process(text: str) -> str:
        """
        Clean up AI output for Telegram:
        - Remove markdown code fences
        - Ensure it doesn't exceed Telegram's 4096-char message limit
        """
        text = text.strip()
        # Remove markdown artifacts that Gemini sometimes adds
        for fence in ["```html", "```", "**", "__"]:
            text = text.replace(fence, "")
        # Truncate safely at sentence boundary if too long
        if len(text) > 4000:
            text = text[:3990] + "...\n\n<i>(Briefing truncated)</i>"
        return text
