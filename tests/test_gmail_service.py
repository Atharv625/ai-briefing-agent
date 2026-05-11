"""
tests/test_gmail_service.py - Unit tests for GmailService.
Uses mocks to avoid real API calls.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.gmail_service import GmailService, EmailItem


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def gmail_service():
    """Returns a GmailService with a mocked authenticated service."""
    svc = GmailService()
    svc._service = MagicMock()
    return svc


SAMPLE_RAW_EMAIL = {
    "id": "msg_123",
    "threadId": "thread_456",
    "snippet": "Your AWS bill is due tomorrow",
    "internalDate": "1700000000000",
    "labelIds": ["INBOX", "UNREAD"],
    "payload": {
        "headers": [
            {"name": "Subject", "value": "AWS Billing Alert - Action Required"},
            {"name": "From", "value": "AWS Billing <billing@amazon.com>"},
        ],
        "mimeType": "text/plain",
        "body": {"data": "WW91ciBBV1MgYmlsbCBpcyBkdWUgdG9tb3Jyb3c="},  # base64
        "parts": [],
    },
}


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestEmailCategorization:
    """Tests the rule-based email categorization logic."""

    def test_categorizes_urgent(self):
        category = GmailService._categorize(
            "Action Required: System Down", "Please respond ASAP", "ops@company.com"
        )
        assert category == "urgent"

    def test_categorizes_finance(self):
        category = GmailService._categorize(
            "AWS Billing Alert", "Your invoice is ready", "billing@amazon.com"
        )
        assert category == "finance"

    def test_categorizes_newsletter(self):
        category = GmailService._categorize(
            "Weekly Newsletter", "Unsubscribe from this list", "noreply@news.com"
        )
        assert category == "newsletter"

    def test_categorizes_general(self):
        category = GmailService._categorize(
            "Hello there", "Just checking in", "friend@example.com"
        )
        assert category == "general"


class TestSenderParsing:
    """Tests email sender extraction."""

    def test_parses_name_and_email(self):
        name, email = GmailService._parse_sender("John Doe <john@example.com>")
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_parses_plain_email(self):
        name, email = GmailService._parse_sender("john@example.com")
        assert email == "john@example.com"

    def test_parses_quoted_name(self):
        name, email = GmailService._parse_sender('"AWS Billing" <billing@amazon.com>')
        assert name == "AWS Billing"
        assert email == "billing@amazon.com"


class TestEmailParsing:
    """Tests full email parsing from raw API response."""

    def test_parse_message_returns_email_item(self, gmail_service):
        gmail_service._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            SAMPLE_RAW_EMAIL
        )
        item = gmail_service._parse_message("msg_123")
        assert isinstance(item, EmailItem)
        assert item.subject == "AWS Billing Alert - Action Required"
        assert item.sender == "AWS Billing"
        assert item.sender_email == "billing@amazon.com"
        assert item.category == "finance"

    def test_parse_message_detects_urgency(self, gmail_service):
        urgent_email = {**SAMPLE_RAW_EMAIL, "labelIds": ["INBOX", "IMPORTANT"]}
        gmail_service._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            urgent_email
        )
        item = gmail_service._parse_message("msg_123")
        assert item.is_urgent is True


@pytest.mark.asyncio
class TestFetchEmails:
    """Tests async email fetching with mocked API."""

    async def test_fetch_returns_list(self, gmail_service):
        gmail_service._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg_123"}]
        }
        gmail_service._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            SAMPLE_RAW_EMAIL
        )
        emails = await gmail_service.fetch_emails()
        assert isinstance(emails, list)
        assert len(emails) == 1

    async def test_fetch_empty_inbox(self, gmail_service):
        gmail_service._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }
        emails = await gmail_service.fetch_emails()
        assert emails == []
