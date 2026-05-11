"""
services/telegram_service.py - Telegram Bot API integration.

Uses python-telegram-bot (v20+) async interface.
Handles:
  - Sending formatted briefing messages
  - Splitting long messages (Telegram limit: 4096 chars)
  - Retry on rate limit (429) errors
  - Future: multi-user routing, inline keyboards
"""

import asyncio
from typing import Optional

import httpx

from src.config import get_settings
from src.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
MAX_MESSAGE_LENGTH = 4096


class TelegramService:
    """
    Telegram Bot API client using raw httpx for minimal dependencies.
    Supports HTML and MarkdownV2 parse modes.
    """

    def __init__(self):
        self.settings = get_settings()
        self._base_url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ── Core send method ───────────────────────────────────────────────────────

    @with_retry(
        max_attempts=3,
        backoff=5.0,
        exceptions=(httpx.HTTPError, httpx.TimeoutException, Exception),
    )
    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
        disable_preview: bool = True,
    ) -> bool:
        """
        Sends a message to the configured chat.
        Automatically splits messages exceeding Telegram's 4096-char limit.

        Args:
            text: Message content (HTML or MarkdownV2 formatted).
            chat_id: Override the default chat ID (for multi-user support).
            parse_mode: "HTML" or "MarkdownV2". Defaults to config value.
            disable_preview: Suppresses link previews (cleaner for briefings).

        Returns:
            True if all chunks sent successfully, False otherwise.
        """
        target_chat_id = chat_id or self.settings.telegram_chat_id
        mode = parse_mode or self.settings.telegram_parse_mode

        # Split long messages into chunks
        chunks = self._split_message(text)
        logger.info(
            "Sending %d message chunk(s) to chat %s...", len(chunks), target_chat_id
        )

        client = self._client or httpx.AsyncClient(timeout=30.0)
        should_close = self._client is None

        try:
            for i, chunk in enumerate(chunks):
                payload = {
                    "chat_id": target_chat_id,
                    "text": chunk,
                    "disable_web_page_preview": disable_preview,
                }

                response = await client.post(
                    f"{self._base_url}/sendMessage",
                    json=payload,
                )

                data = response.json()
                if not data.get("ok"):
                    error = data.get("description", "Unknown error")
                    # Handle Telegram rate limiting
                    if response.status_code == 429:
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        logger.warning(
                            "Rate limited by Telegram. Waiting %ds...", retry_after
                        )
                        await asyncio.sleep(retry_after)
                        # Re-send this chunk
                        response = await client.post(
                            f"{self._base_url}/sendMessage", json=payload
                        )
                        data = response.json()
                        if not data.get("ok"):
                            logger.error("Chunk %d failed after rate-limit retry: %s", i, error)
                            return False
                    else:
                        logger.error(
                            "Telegram API error on chunk %d: %s (status=%d)",
                            i, error, response.status_code,
                        )
                        return False

                logger.debug("Chunk %d/%d sent successfully.", i + 1, len(chunks))

                # Brief pause between chunks to avoid rate limits
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)

        finally:
            if should_close:
                await client.aclose()

        logger.info("Briefing sent to Telegram successfully.")
        return True

    async def send_error_alert(self, error_msg: str) -> bool:
        """
        Sends a simplified error notification to Telegram.
        Used when the main briefing pipeline fails.
        """
        text = (
            "⚠️ <b>Briefing Agent Error</b>\n\n"
            f"<code>{self._escape_html(error_msg[:500])}</code>\n\n"
            "Please check the logs."
        )
        # Try to send even if HTML parse fails
        try:
            return await self.send_message(text)
        except Exception:
            return await self.send_message(
                f"⚠️ Briefing Agent Error: {error_msg[:200]}",
                parse_mode=None,
            )

    async def test_connection(self) -> bool:
        """
        Verifies bot token is valid and can reach the chat.
        Run this during setup / health checks.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/getMe")
            data = response.json()
            if data.get("ok"):
                bot_name = data["result"].get("username", "unknown")
                logger.info("Telegram bot connected: @%s", bot_name)
                return True
            logger.error("Telegram bot token invalid: %s", data)
            return False

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
        """
        Splits text into chunks respecting Telegram's character limit.
        Splits at newline boundaries to avoid breaking HTML tags mid-way.
        """
        if len(text) <= limit:
            return [text]

        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current.strip())
                current = line + "\n"
            else:
                current += line + "\n"

        if current.strip():
            chunks.append(current.strip())

        return chunks

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escapes characters that break Telegram HTML parsing."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
