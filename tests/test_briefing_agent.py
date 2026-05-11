"""
tests/test_briefing_agent.py - Integration tests for BriefingAgent.
Mocks all external services to test orchestration logic.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.briefing_agent import BriefingAgent, BriefingResult
from src.services.gmail_service import EmailItem
from src.services.calendar_service import CalendarEvent


# ── Test fixtures ──────────────────────────────────────────────────────────────

def make_mock_email(subject="Test Email", category="work", is_urgent=False):
    return EmailItem(
        message_id="test_id",
        thread_id="thread_id",
        subject=subject,
        sender="Test Sender",
        sender_email="test@example.com",
        snippet="Test snippet",
        body_text="Test body",
        received_at=datetime.now(),
        category=category,
        is_urgent=is_urgent,
    )


def make_mock_event(title="Team Meeting", start_time="10:00 AM", end_time="11:00 AM"):
    return CalendarEvent(
        event_id="event_id",
        title=title,
        start_time=start_time,
        end_time=end_time,
        start_dt=None,
        end_dt=None,
        location=None,
        description=None,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestBriefingAgent:

    async def test_successful_run(self):
        """Full pipeline succeeds when all services return data."""
        mock_gmail = AsyncMock()
        mock_gmail.authenticate = MagicMock()
        mock_gmail.fetch_emails = AsyncMock(return_value=[
            make_mock_email("Invoice Due", "finance", True),
            make_mock_email("Team Update", "work"),
        ])

        mock_calendar = AsyncMock()
        mock_calendar.authenticate = MagicMock()
        mock_calendar.fetch_today_events = AsyncMock(return_value=(
            [make_mock_event("Product Sync")],
            [],  # No conflicts
        ))

        mock_ai = AsyncMock()
        mock_ai.generate_briefing = AsyncMock(
            return_value="Good Morning ☀️\n\n📅 Meetings:\n- Product Sync"
        )

        mock_telegram = AsyncMock()
        mock_telegram.send_message = AsyncMock(return_value=True)

        agent = BriefingAgent(
            gmail=mock_gmail,
            calendar=mock_calendar,
            ai=mock_ai,
            telegram=mock_telegram,
        )

        result = await agent.run()

        assert result.success is True
        assert result.emails_fetched == 2
        assert result.events_fetched == 1
        assert result.conflicts_detected == 0
        assert result.briefing_length > 0
        assert result.error is None
        mock_telegram.send_message.assert_called_once()

    async def test_handles_empty_inbox(self):
        """Agent sends a calm-day message when no emails/events."""
        mock_gmail = AsyncMock()
        mock_gmail.authenticate = MagicMock()
        mock_gmail.fetch_emails = AsyncMock(return_value=[])

        mock_calendar = AsyncMock()
        mock_calendar.authenticate = MagicMock()
        mock_calendar.fetch_today_events = AsyncMock(return_value=([], []))

        mock_ai = AsyncMock()
        mock_telegram = AsyncMock()
        mock_telegram.send_message = AsyncMock(return_value=True)

        agent = BriefingAgent(
            gmail=mock_gmail,
            calendar=mock_calendar,
            ai=mock_ai,
            telegram=mock_telegram,
        )

        result = await agent.run()

        assert result.success is True
        # AI should NOT be called when there's no data
        mock_ai.generate_briefing.assert_not_called()
        mock_telegram.send_message.assert_called_once()

    async def test_sends_error_alert_on_failure(self):
        """Agent sends Telegram error alert when pipeline fails."""
        mock_gmail = AsyncMock()
        mock_gmail.authenticate = MagicMock(side_effect=Exception("Auth failed"))

        mock_telegram = AsyncMock()
        mock_telegram.send_error_alert = AsyncMock(return_value=True)

        agent = BriefingAgent(
            gmail=mock_gmail,
            calendar=AsyncMock(),
            ai=AsyncMock(),
            telegram=mock_telegram,
        )

        result = await agent.run()

        assert result.success is False
        assert "Auth failed" in result.error
        mock_telegram.send_error_alert.assert_called_once()


class TestBriefingResult:

    def test_summary_format_success(self):
        result = BriefingResult(
            success=True,
            run_at=datetime(2024, 1, 15, 7, 0, 0),
            emails_fetched=5,
            events_fetched=3,
            conflicts_detected=1,
            briefing_length=800,
            duration_seconds=4.2,
        )
        summary = result.summary()
        assert "SUCCESS" in summary
        assert "5" in summary
        assert "3" in summary

    def test_summary_format_failure(self):
        result = BriefingResult(
            success=False,
            run_at=datetime(2024, 1, 15, 7, 0, 0),
            emails_fetched=0,
            events_fetched=0,
            conflicts_detected=0,
            briefing_length=0,
            error="Connection refused",
        )
        summary = result.summary()
        assert "FAILED" in summary
        assert "Connection refused" in summary
