"""
services/calendar_service.py - Google Calendar integration via API v3.

Responsibilities:
  - Reuse OAuth2 token from Gmail auth (same credential scope)
  - Fetch today's calendar events from all calendars
  - Parse event details: title, time, attendees, location, conference links
  - Detect scheduling conflicts
  - Categorize events by calendar type (meetings, tasks, birthdays, holidays)
  - Return structured CalendarEvent objects for AI summarization
  - Filter stale/old events using timezone-aware validation
  - Handle AWS Lambda filesystem constraints (/tmp writable storage)
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_settings
from src.logger import get_logger
from src.utils.date_utils import (
    format_event_time,
    to_utc_rfc3339,
    today_end,
    today_start,
)
from src.utils.retry import with_retry

logger = get_logger(__name__)

# Combined scopes needed if we share the token with Gmail
COMBINED_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

# Calendars to exclude from aggregation (system calendars)
EXCLUDED_CALENDARS = [
    "Contacts",
    "Birthdays",
]


@dataclass
class CalendarEvent:
    """Structured representation of a single calendar event."""

    event_id: str
    title: str
    start_time: str         # Formatted for display (e.g., "10:00 AM")
    end_time: str
    start_dt: Optional[datetime]
    end_dt: Optional[datetime]
    location: Optional[str]
    description: Optional[str]
    attendees: List[str] = field(default_factory=list)
    conference_link: Optional[str] = None  # Meet / Zoom / Teams
    is_all_day: bool = False
    organizer: Optional[str] = None
    is_accepted: bool = True
    calendar_name: Optional[str] = None
    calendar_type: str = "meeting"  # meeting, task, birthday, holiday

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start": self.start_time,
            "end": self.end_time,
            "attendees_count": len(self.attendees),
            "location": self.location,
            "conference_link": self.conference_link,
            "is_all_day": self.is_all_day,
            "calendar_name": self.calendar_name,
            "calendar_type": self.calendar_type,
        }

    def duration_minutes(self) -> int:
        if self.start_dt and self.end_dt:
            return int((self.end_dt - self.start_dt).total_seconds() / 60)
        return 0


@dataclass
class ConflictInfo:
    """Represents an overlap between two calendar events."""
    event_a: CalendarEvent
    event_b: CalendarEvent
    overlap_minutes: int


class CalendarService:
    """
    Encapsulates all Google Calendar API interactions.
    Fetches events from all calendars (primary + secondary).
    Reuses the OAuth2 token created by GmailService (same credentials file).
    Filters stale events using timezone-aware validation.
    Handles AWS Lambda filesystem constraints with /tmp token storage.
    """

    def __init__(self):
        self.settings = get_settings()
        self._service = None
        self.india_tz = ZoneInfo("Asia/Kolkata")
        self._is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

    # ── Authentication ───────────────────────────────────────────────────────���─

    def authenticate(self) -> None:
        """
        Loads the existing OAuth2 token (created during Gmail auth).
        If the token doesn't cover calendar scopes, initiates a new flow.
        
        In AWS Lambda:
          - Uses /tmp for writable token storage
          - Copies bundled token from /var/task on cold start
          - Automatically persists refreshed token to /tmp
        """
        creds: Optional[Credentials] = None

        # ── Determine token path (local vs Lambda) ─────────────────────────────
        if self._is_lambda:
            token_path = Path("/tmp/token.json")

            # Copy bundled token into writable /tmp on cold start
            original_token = self.settings.google_token_path

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
                creds = Credentials.from_authorized_user_file(
                    str(token_path), COMBINED_SCOPES
                )
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
                    str(creds_path), COMBINED_SCOPES
                )
                creds = flow.run_local_server(port=8080)
                logger.info("OAuth2 flow complete.")

            # Persist token for future runs
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
            logger.info("Token saved to %s", token_path)

        self._service = build("calendar", "v3", credentials=creds)
        logger.info("Google Calendar API service initialized.")

    @property
    def service(self):
        if self._service is None:
            self.authenticate()
        return self._service

    # ── Calendar Management ────────────────────────────────────────────────────

    def _get_all_calendars(self) -> List[dict]:
        """
        Fetches all calendars (primary + secondary) from the user's account.
        Excludes hidden calendars and system calendars for cleaner aggregation.
        """
        try:
            result = self.service.calendarList().list().execute()
            calendars = result.get("items", [])
            
            # Filter out hidden calendars and excluded system calendars
            visible_calendars = [
                cal for cal in calendars 
                if not cal.get("hidden", False)
                and cal.get("summary") not in EXCLUDED_CALENDARS
            ]
            
            logger.info("Found %d visible calendar(s)", len(visible_calendars))
            return visible_calendars
        except HttpError as e:
            logger.error("Failed to fetch calendar list: %s", e)
            return []

    @staticmethod
    def _detect_calendar_type(calendar_name: str) -> str:
        """
        Detects calendar type based on the calendar name.
        Returns: 'birthday', 'task', 'holiday', or 'meeting' (default)
        """
        cal_name_lower = calendar_name.lower()
        
        if "birthday" in cal_name_lower:
            return "birthday"
        elif any(x in cal_name_lower for x in ["task", "todo", "reminder", "my tasks"]):
            return "task"
        elif any(x in cal_name_lower for x in ["holiday", "vacation"]):
            return "holiday"
        else:
            return "meeting"

    def _is_today_event(self, raw: dict) -> bool:
        """
        Ensures event actually belongs to TODAY in IST.
        Prevents stale recurring birthdays/holidays from appearing.
        
        Returns:
            True if event is today in IST timezone, False otherwise
        """
        today = datetime.now(self.india_tz).date()
        start = raw.get("start", {})

        # All-day event
        if "date" in start:
            try:
                event_date = datetime.fromisoformat(start["date"]).date()
                return event_date == today
            except (ValueError, TypeError):
                logger.warning("Failed to parse all-day event date: %s", start.get("date"))
                return False

        # Timed event
        if "dateTime" in start:
            try:
                dt_str = start["dateTime"].replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                event_date = dt.astimezone(self.india_tz).date()
                return event_date == today
            except (ValueError, TypeError):
                logger.warning("Failed to parse timed event: %s", start.get("dateTime"))
                return False

        return False

    # ── Core event fetching ────────────────────────────────────────────────────

    @with_retry(max_attempts=3, backoff=2.0, exceptions=(HttpError, Exception))
    async def fetch_today_events(self) -> Tuple[List[CalendarEvent], List[ConflictInfo]]:
        """
        Returns (events_today, conflicts).
        Fetches events from all calendars for the current day.
        Filters out stale recurring events using timezone-aware validation.
        Runs synchronous API call in executor to keep async context clean.
        """
        loop = asyncio.get_event_loop()
        events = await loop.run_in_executor(None, self._fetch_events_sync)
        conflicts = self._detect_conflicts(events)
        return events, conflicts

    def _fetch_events_sync(self) -> List[CalendarEvent]:
        """
        Fetches all calendar events for today from all visible calendars.
        Uses timeMin/timeMax for efficient server-side filtering.
        Validates each event is actually today in IST before including.
        Skips completed tasks.
        """
        time_min = to_utc_rfc3339(today_start())
        time_max = to_utc_rfc3339(today_end())

        logger.info(
            "Fetching calendar events between %s and %s", time_min, time_max
        )

        all_events = []
        calendars = self._get_all_calendars()

        for cal in calendars:
            calendar_id = cal.get("id")
            calendar_name = cal.get("summary", "Unknown")

            try:
                result = (
                    self.service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,  # Expand recurring events
                        orderBy="startTime",
                        maxResults=50,
                    )
                    .execute()
                )

                raw_events = result.get("items", [])

                logger.info(
                    "Fetched %d event(s) from calendar: %s",
                    len(raw_events),
                    calendar_name,
                )

                for ev in raw_events:
                    # Skip completed tasks
                    if ev.get("status") == "completed":
                        logger.debug("Skipping completed task: %s", ev.get("summary"))
                        continue

                    # Only include events that are actually today in IST
                    if not self._is_today_event(ev):
                        logger.debug(
                            "Skipping stale/old event: %s (not today in IST)",
                            ev.get("summary")
                        )
                        continue

                    parsed = self._parse_event(ev)
                    
                    # Add calendar metadata
                    parsed.calendar_name = calendar_name
                    parsed.calendar_type = self._detect_calendar_type(calendar_name)
                    
                    all_events.append(parsed)

            except HttpError as e:
                logger.warning(
                    "Failed fetching calendar %s: %s",
                    calendar_name,
                    e,
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error fetching calendar %s: %s",
                    calendar_name,
                    e,
                )

        logger.info("Total events fetched: %d", len(all_events))
        return all_events

    def _parse_event(self, raw: dict) -> CalendarEvent:
        """Parses a raw Google Calendar API event dict into CalendarEvent."""
        start = raw.get("start", {})
        end = raw.get("end", {})

        # All-day events use 'date' key; timed events use 'dateTime'
        is_all_day = "date" in start and "dateTime" not in start
        start_str = start.get("dateTime", start.get("date", ""))
        end_str = end.get("dateTime", end.get("date", ""))

        # Parse to datetime for conflict detection
        start_dt = _parse_dt(start_str) if not is_all_day else None
        end_dt = _parse_dt(end_str) if not is_all_day else None

        # Extract attendees (skip self/organizer duplicates)
        attendees = [
            a.get("displayName") or a.get("email", "")
            for a in raw.get("attendees", [])
            if not a.get("self", False)
        ]

        # Look for conference link (Google Meet, Zoom, Teams)
        conference_link = self._extract_conference_link(raw)

        # Check if current user accepted this event
        self_attendee = next(
            (a for a in raw.get("attendees", []) if a.get("self")), {}
        )
        is_accepted = self_attendee.get("responseStatus", "accepted") in (
            "accepted", "tentative"
        )

        return CalendarEvent(
            event_id=raw.get("id", ""),
            title=raw.get("summary", "(No Title)"),
            start_time=format_event_time(start_str, is_all_day),
            end_time=format_event_time(end_str, is_all_day),
            start_dt=start_dt,
            end_dt=end_dt,
            location=raw.get("location"),
            description=raw.get("description", "")[:500] if raw.get("description") else None,
            attendees=attendees[:10],  # Cap at 10 for display
            conference_link=conference_link,
            is_all_day=is_all_day,
            organizer=raw.get("organizer", {}).get("displayName")
                or raw.get("organizer", {}).get("email"),
            is_accepted=is_accepted,
        )

    @staticmethod
    def _extract_conference_link(raw: dict) -> Optional[str]:
        """Extracts meeting link from Google Meet, Zoom, or Teams data."""
        # Google Meet
        conference_data = raw.get("conferenceData", {})
        for ep in conference_data.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                return ep.get("uri")

        # Zoom / Teams links in description
        desc = raw.get("description", "") or ""
        
        zoom_match = re.search(r"https://[a-z0-9.]+\.zoom\.us/j/\S+", desc)
        if zoom_match:
            return zoom_match.group(0)
        
        teams_match = re.search(r"https://teams\.microsoft\.com/l/meetup-join/\S+", desc)
        if teams_match:
            return teams_match.group(0)

        return None

    @staticmethod
    def _detect_conflicts(events: List[CalendarEvent]) -> List[ConflictInfo]:
        """
        O(n²) overlap detection — fine for typical calendar sizes (<50 events/day).
        Returns list of ConflictInfo for any overlapping timed events.
        Only detects conflicts for 'meeting' type events to avoid false positives with tasks/birthdays.
        """
        conflicts: List[ConflictInfo] = []
        timed = [
            e for e in events 
            if e.start_dt and e.end_dt and e.calendar_type == "meeting"
        ]

        for i in range(len(timed)):
            for j in range(i + 1, len(timed)):
                a, b = timed[i], timed[j]
                overlap_start = max(a.start_dt, b.start_dt)
                overlap_end = min(a.end_dt, b.end_dt)
                if overlap_start < overlap_end:
                    overlap_minutes = int(
                        (overlap_end - overlap_start).total_seconds() / 60
                    )
                    conflicts.append(ConflictInfo(a, b, overlap_minutes))

        if conflicts:
            logger.warning("Detected %d scheduling conflict(s).", len(conflicts))

        return conflicts

    def categorize_events(
        self, events: List[CalendarEvent]
    ) -> Tuple[List[CalendarEvent], List[CalendarEvent], List[CalendarEvent], List[CalendarEvent]]:
        """
        Categorizes events by type for organized display.
        Returns: (meetings, tasks, birthdays, holidays)
        """
        meetings = [e for e in events if e.calendar_type == "meeting"]
        tasks = [e for e in events if e.calendar_type == "task"]
        birthdays = [e for e in events if e.calendar_type == "birthday"]
        holidays = [e for e in events if e.calendar_type == "holiday"]
        
        return meetings, tasks, birthdays, holidays


def _parse_dt(dt_str: str) -> Optional[datetime]:
    """Parse ISO 8601 datetime string, returning None on failure."""
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None