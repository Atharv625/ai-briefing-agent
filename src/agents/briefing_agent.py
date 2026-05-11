"""
agents/briefing_agent.py - Core orchestration agent.

The BriefingAgent ties all services together:
  1. Authenticate with Google
  2. Fetch emails (async) + calendar events (async) + tasks (async) in parallel
  3. Generate AI summary
  4. Format and send via Telegram
  5. Log outcomes and handle errors gracefully

This is the single entry point for the briefing pipeline.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from src.config import get_settings
from src.logger import get_logger
from src.services.ai_summary import AIOrchestrator
from src.services.calendar_service import CalendarEvent, CalendarService, ConflictInfo
from src.services.gmail_service import EmailItem, GmailService
from src.services.tasks_service import (
    TasksService,
    TaskItem,
    TaskSummary,
)
from src.services.telegram_service import TelegramService
from src.utils.date_utils import now_local

logger = get_logger(__name__)


@dataclass
class BriefingResult:
    """Structured result of a briefing run for logging and debugging."""

    success: bool
    run_at: datetime
    emails_fetched: int
    events_fetched: int
    tasks_fetched: int
    conflicts_detected: int
    briefing_length: int
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def summary(self) -> str:
        status = "✅ SUCCESS" if self.success else "❌ FAILED"
        return (
            f"{status} | {self.run_at.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"Emails: {self.emails_fetched} | Events: {self.events_fetched} | "
            f"Tasks: {self.tasks_fetched} | "
            f"Conflicts: {self.conflicts_detected} | "
            f"Briefing: {self.briefing_length} chars | "
            f"Duration: {self.duration_seconds:.1f}s"
            + (f" | Error: {self.error}" if self.error else "")
        )


class BriefingAgent:
    """
    Autonomous agent that orchestrates the full daily briefing pipeline.

    Design principles:
    - Services are injected (testable, replaceable)
    - Fetch operations run concurrently (asyncio.gather)
    - Errors in one service don't crash the entire pipeline
    - Sends error alerts to Telegram on failure
    """

    def __init__(
        self,
        gmail: Optional[GmailService] = None,
        calendar: Optional[CalendarService] = None,
        tasks: Optional[TasksService] = None,
        ai: Optional[AIOrchestrator] = None,
        telegram: Optional[TelegramService] = None,
    ):
        self.settings = get_settings()
        self.gmail = gmail or GmailService()
        self.calendar = calendar or CalendarService()
        self.tasks = tasks or TasksService()
        self.ai = ai or AIOrchestrator()
        self.telegram = telegram or TelegramService()

    # ── Main entry point ───────────────────────────────────────────────────────

    async def run(self) -> BriefingResult:
        """
        Execute the full briefing pipeline.
        Returns a BriefingResult regardless of success/failure.
        """
        start_time = asyncio.get_event_loop().time()
        run_at = now_local()
        logger.info("=" * 60)
        logger.info("Starting Daily Briefing Agent run at %s", run_at)
        logger.info("=" * 60)

        try:
            # Step 1: Authenticate (all services share token)
            await self._authenticate()

            # Step 2: Fetch data concurrently
            emails, (events, conflicts), (tasks, task_summary) = await self._fetch_all_data()

            # Step 3: Generate AI briefing
            briefing_text = await self._generate_briefing(
                emails,
                events,
                conflicts,
                tasks,
                task_summary,
            )

            # Step 4: Send to Telegram
            await self._send_briefing(briefing_text)

            duration = asyncio.get_event_loop().time() - start_time
            result = BriefingResult(
                success=True,
                run_at=run_at,
                emails_fetched=len(emails),
                events_fetched=len(events),
                tasks_fetched=len(tasks),
                conflicts_detected=len(conflicts),
                briefing_length=len(briefing_text),
                duration_seconds=duration,
            )
            logger.info(result.summary())
            return result

        except Exception as exc:
            duration = asyncio.get_event_loop().time() - start_time
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Briefing pipeline failed: %s", error_msg)

            # Best-effort: notify via Telegram even if pipeline failed
            await self._send_error_alert(error_msg)

            return BriefingResult(
                success=False,
                run_at=run_at,
                emails_fetched=0,
                events_fetched=0,
                tasks_fetched=0,
                conflicts_detected=0,
                briefing_length=0,
                error=error_msg,
                duration_seconds=duration,
            )

    # ── Pipeline steps ─────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """
        Initialize Google OAuth2 for all services.
        Calendar and Tasks reuse the same token as Gmail.
        Runs synchronously in executor to not block async context.
        """
        loop = asyncio.get_event_loop()
        logger.info("Authenticating with Google APIs...")
        # Gmail authenticate first (creates/refreshes token)
        await loop.run_in_executor(None, self.gmail.authenticate)
        # Calendar reuses the same token path
        await loop.run_in_executor(None, self.calendar.authenticate)
        # Tasks reuses the same token path
        await loop.run_in_executor(None, self.tasks.authenticate)
        logger.info("Authentication complete.")

    async def _fetch_all_data(self) -> Tuple[
        List[dict],
        Tuple[List[CalendarEvent], List[ConflictInfo]],
        Tuple[List[TaskItem], TaskSummary],
    ]:
        """
        Fetch emails, calendar events, and tasks concurrently.
        asyncio.gather runs all three coroutines in parallel — saves ~66% time
        vs sequential fetching.
        """
        logger.info("Fetching Gmail, Calendar, and Tasks data concurrently...")
        emails_task = self.gmail.fetch_emails()
        calendar_task = self.calendar.fetch_today_events()
        tasks_task = self.tasks.fetch_pending_tasks()

        emails, calendar_result, task_result = await asyncio.gather(
            emails_task,
            calendar_task,
            tasks_task,
            return_exceptions=False,  # Propagate exceptions
        )

        events, conflicts = calendar_result
        tasks, task_summary = task_result
        
        logger.info(
            "Fetched: %d emails, %d events, %d tasks, %d conflicts.",
            len(emails),
            len(events),
            len(tasks),
            len(conflicts),
        )
        return emails, (events, conflicts), (tasks, task_summary)

    async def _generate_briefing(
        self,
        emails: List[dict],
        events: List[CalendarEvent],
        conflicts: List[ConflictInfo],
        tasks: List[TaskItem],
        task_summary: TaskSummary,
    ) -> str:
        """Generates AI briefing text from fetched data."""
        logger.info("Generating AI briefing...")

        if not emails and not events and not tasks:
            logger.info("No data to summarize. Sending empty-day briefing.")
            return self._empty_day_message()

        briefing = await self.ai.generate_briefing(
            emails,
            events,
            conflicts,
            tasks,
            task_summary,
        )
        logger.info("AI briefing generated (%d chars).", len(briefing))
        return briefing

    async def _send_briefing(self, briefing_text: str) -> None:
        """Sends the briefing to Telegram."""
        logger.info("Sending briefing to Telegram...")
        success = await self.telegram.send_message(briefing_text)
        if not success:
            raise RuntimeError("Failed to deliver briefing to Telegram.")

    async def _send_error_alert(self, error_msg: str) -> None:
        """Best-effort error notification to Telegram."""
        try:
            await self.telegram.send_error_alert(error_msg)
        except Exception as alert_exc:
            logger.error("Even error alert failed to send: %s", alert_exc)

    @staticmethod
    def _empty_day_message() -> str:
        """Generates a friendly message for days with no data."""
        from src.utils.date_utils import now_local
        date_str = now_local().strftime("%A, %B %d, %Y")
        return (
            f"Good Morning ☀️ {date_str}\n\n"
            "📭 No unread emails, calendar events, or pending tasks found for today.\n\n"
            "Looks like a calm day — use it wisely! 🎯"
        )
