"""
services/gmail_service.py - Gmail integration via Google API v1.

Responsibilities:
  - OAuth2 authentication (local browser flow + token refresh)
  - Fetch unread emails from the past N hours
  - Parse email metadata (sender, subject, snippet, labels)
  - Categorize emails: important / low_priority / useless / spam
  - Handle AWS Lambda filesystem constraints (/tmp writable storage)
  - Return structured EmailItem objects ready for AI summarization
"""

import asyncio
import base64
import email as email_lib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_settings
from src.logger import get_logger
from src.utils.date_utils import hours_ago, now_local
from src.utils.retry import with_retry

logger = get_logger(__name__)

# Scopes required — read-only is sufficient; never request write unless needed
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

# ── Email category keyword rules ───────────────────────────────────────────────
CATEGORY_RULES = {
    "important": [
        r"\burgent\b",
        r"\bASAP\b",
        r"\bimmediate\b",
        r"\bcritical\b",
        r"\bdeadline\b",
        r"\baction required\b",
        r"\bimportant\b",
        r"\bmeeting\b",
        r"\binterview\b",
        r"\bpayment\b",
        r"\binvoice\b",
        r"\btransaction\b",
        r"\bsecurity\b",
        r"\blogin\b",
        r"\bverification\b",
        r"\bOTP\b",
        r"\bproject\b",
        r"\bhackathon\b",
    ],

    "low_priority": [
        r"github",
        r"workflow",
        r"build failed",
        r"run failed",
        r"notification",
        r"update available",
        r"reminder",
        r"jira",
        r"confluence",
        r"daily digest",
    ],

    "useless": [
        r"newsletter",
        r"unsubscribe",
        r"weekly update",
        r"marketing",
        r"promotion",
        r"sale",
        r"offer",
        r"try premium",
        r"recommended for you",
        r"social",
    ],

    "spam": [
        r"free money",
        r"won prize",
        r"claim now",
        r"limited time",
        r"act now",
        r"crypto giveaway",
        r"earn \$",
        r"click here",
        r"congratulations",
    ],
}

LOW_PRIORITY_PATTERNS = [
    "newsletter",
    "unsubscribe",
    "noreply",
    "no-reply",
]


@dataclass
class EmailItem:
    """Structured representation of a single email."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    snippet: str
    body_text: str          # Truncated plain-text body
    received_at: datetime
    labels: List[str] = field(default_factory=list)
    category: str = "general"
    is_urgent: bool = False
    has_attachment: bool = False

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "from": self.sender,
            "snippet": self.snippet,
            "category": self.category,
            "is_urgent": self.is_urgent,
            "received_at": self.received_at.isoformat(),
            "has_attachment": self.has_attachment,
        }


class GmailService:
    """
    Encapsulates all Gmail API interactions.

    Authentication flow:
      1. First run → opens browser for OAuth2 consent → saves token.json
      2. Subsequent runs → loads token.json, refreshes automatically if expired
      3. Lambda mode → uses /tmp for writable storage, copies token on cold start

    Design handles both local development and AWS Lambda deployment.
    """

    def __init__(self):
        self.settings = get_settings()
        self._service = None  # Lazy-initialized
        self._is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

    # ── Authentication ─────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """
        Performs OAuth2 authentication.
        On first run, opens a local browser window for user consent.
        On subsequent runs, loads and refreshes the saved token.
        
        In AWS Lambda:
          - Uses /tmp for writable token storage
          - Copies bundled token from /var/task on cold start
          - Automatically persists refreshed token to /tmp
        """
        creds: Optional[Credentials] = None

        # ── Determine token path (local vs Lambda) ─────────────────────────────
        if self._is_lambda:
            token_path = Path("/tmp/token.json")
            original_token = self.settings.google_token_path

            # Cold start: copy bundled token into writable /tmp
            if not token_path.exists() and original_token.exists():
                logger.info(
                    "Lambda cold start detected. Copying token from %s to /tmp/token.json",
                    original_token,
                )
                token_path.write_text(original_token.read_text())
                logger.info("Token copied to writable /tmp directory.")
        else:
            token_path = self.settings.google_token_path

        creds_path = self.settings.google_credentials_path

        # Load existing token
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
                logger.debug("Loaded existing OAuth2 token from %s", token_path)
            except Exception as e:
                logger.warning("Failed to load token from %s: %s", token_path, e)
                creds = None

        # Refresh or re-authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired OAuth2 token...")
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning("Token refresh failed: %s. Re-authenticating...", e)
                    creds = None
            
            if not creds:
                logger.info("No valid token found. Launching OAuth2 flow...")
                if not creds_path.exists():
                    raise FileNotFoundError(
                        f"Google credentials file not found: {creds_path}\n"
                        "Download it from Google Cloud Console → APIs & Services → Credentials"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=8080)
                logger.info("OAuth2 flow complete.")

            # Persist token for future runs
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
            logger.info("Token saved to %s", token_path)

        self._service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API service initialized.")

    @property
    def service(self):
        if self._service is None:
            self.authenticate()
        return self._service

    # ── Core email fetching ────────────────────────────────────────────────────

    @with_retry(max_attempts=3, backoff=2.0, exceptions=(HttpError, Exception))
    async def fetch_emails(self) -> Dict[str, List[EmailItem]]:
        """
        Async wrapper: runs blocking Gmail API calls in a thread pool
        so we don't block the event loop.
        Returns grouped emails by priority: important, low_priority, useless, spam.
        """
        loop = asyncio.get_event_loop()
        emails = await loop.run_in_executor(None, self._fetch_emails_sync)
        return self._group_emails(emails)

    def _fetch_emails_sync(self) -> List[EmailItem]:
        """
        Fetches unread emails from the past N hours.
        Uses Gmail search syntax for efficient server-side filtering.
        """
        lookback = self.settings.gmail_hours_lookback
        cutoff = hours_ago(lookback)
        # Gmail uses Unix epoch seconds in its 'after:' filter
        after_ts = int(cutoff.timestamp())

        # Build Gmail query: unread, not spam/trash, after cutoff
        query = f"is:unread -in:spam -in:trash after:{after_ts}"
        logger.info("Fetching emails with query: %s", query)

        try:
            response = (
                self.service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=self.settings.gmail_max_emails,
                )
                .execute()
            )
        except HttpError as e:
            logger.error("Gmail list error: %s", e)
            raise

        messages = response.get("messages", [])
        logger.info("Found %d email(s) to process.", len(messages))

        emails: List[EmailItem] = []

        for msg_stub in messages:
            try:
                item = self._parse_message(msg_stub["id"])

                if not item:
                    continue

                subject_lower = item.subject.lower()
                sender_lower = item.sender.lower()

                skip = any(
                    pattern in subject_lower or pattern in sender_lower
                    for pattern in LOW_PRIORITY_PATTERNS
                )

                if skip:
                    logger.info(
                        "Skipping low-priority email: %s",
                        item.subject
                    )
                    continue

                emails.append(item)

            except Exception as exc:
                logger.warning(
                    "Failed to parse message %s: %s",
                    msg_stub["id"],
                    exc
                )

        # Sort by priority (important first), then by recency (newest first)
        priority_order = {
            "important": 0,
            "low_priority": 1,
            "useless": 2,
            "spam": 3,
            "general": 4,
        }

        emails.sort(
            key=lambda e: (
                priority_order.get(e.category, 99),
                -e.received_at.timestamp(),
            )
        )

        return emails

    def _parse_message(self, msg_id: str) -> Optional[EmailItem]:
        """
        Fetches full message and extracts structured fields.
        Handles multipart MIME bodies to extract plain text.
        """
        raw = (
            self.service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        subject = headers.get("subject", "(No Subject)")
        from_raw = headers.get("from", "")
        sender, sender_email = self._parse_sender(from_raw)
        snippet = raw.get("snippet", "")
        labels = raw.get("labelIds", [])
        internal_date = int(raw.get("internalDate", 0)) // 1000
        received_at = datetime.fromtimestamp(internal_date)

        # Extract body text (up to 1500 chars to keep prompt concise)
        body_text = self._extract_body(raw.get("payload", {}))[:1500]

        # Check for attachments
        has_attachment = any(
            part.get("filename")
            for part in self._iter_parts(raw.get("payload", {}))
            if part.get("filename")
        )

        category = self._categorize(subject, snippet, sender_email)
        is_urgent = category == "important"

        return EmailItem(
            message_id=msg_id,
            thread_id=raw.get("threadId", ""),
            subject=subject,
            sender=sender,
            sender_email=sender_email,
            snippet=snippet,
            body_text=body_text,
            received_at=received_at,
            labels=labels,
            category=category,
            is_urgent=is_urgent,
            has_attachment=has_attachment,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_sender(from_raw: str):
        """Splits 'Name <email@example.com>' into (name, email)."""
        match = re.match(r"^(.*?)\s*<(.+?)>$", from_raw.strip())
        if match:
            return match.group(1).strip().strip('"'), match.group(2).strip()
        # Plain email with no display name
        return from_raw.strip(), from_raw.strip()

    def _extract_body(self, payload: dict) -> str:
        """
        Recursively extracts plain text from a MIME payload.
        Prefers text/plain; falls back to stripped text/html.
        """
        parts = payload.get("parts", [])
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if not parts:
            # Leaf node
            if mime_type == "text/plain" and body_data:
                return base64.urlsafe_b64decode(body_data + "==").decode(
                    "utf-8", errors="replace"
                )
            return ""

        # Walk parts: prefer text/plain
        plain_text = ""
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    plain_text += base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
            elif part.get("mimeType", "").startswith("multipart/"):
                plain_text += self._extract_body(part)

        return plain_text or snippet_fallback(payload)

    @staticmethod
    def _iter_parts(payload: dict):
        """Yields all MIME parts recursively."""
        yield payload
        for part in payload.get("parts", []):
            yield from GmailService._iter_parts(part)

    @staticmethod
    def _categorize(subject: str, snippet: str, sender_email: str) -> str:
        """
        Rule-based email categorization.
        Checks subject + snippet + sender_email against keyword patterns.
        Returns the first matching category or 'general'.
        """
        text = f"{subject} {snippet} {sender_email}".lower()
        for category, patterns in CATEGORY_RULES.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return category
        return "general"

    @staticmethod
    def _group_emails(emails: List[EmailItem]) -> Dict[str, List[EmailItem]]:
        """
        Groups emails by priority category for cleaner display.
        Returns dict with keys: important, low_priority, useless, spam, general.
        """
        grouped = {
            "important": [],
            "low_priority": [],
            "useless": [],
            "spam": [],
            "general": [],
        }

        for email in emails:
            category = email.category
            if category in grouped:
                grouped[category].append(email)
            else:
                grouped["general"].append(email)

        return grouped


def snippet_fallback(payload: dict) -> str:
    """Returns empty string if no plain text found."""
    return ""