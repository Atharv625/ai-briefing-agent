"""
src/services/tasks_service.py - Google Tasks API integration.

Fetches all pending tasks across all task lists, categorizes them
into overdue / due-today / upcoming buckets, and exposes an
async-compatible interface that matches the rest of the service layer.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_settings
from src.logger import get_logger
from src.utils.retry import with_retry

# ── Constants ──────────────────────────────────────────────────────────────────

IST = ZoneInfo("Asia/Kolkata")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

MAX_TASKS_PER_LIST = 100

logger = get_logger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class TaskItem:
    """Represents a single Google Task with computed categorization fields."""

    task_id: str
    title: str
    notes: Optional[str]
    due_date: Optional[str]
    due_datetime: Optional[datetime]
    updated_at: Optional[datetime]
    task_list_name: str
    is_overdue: bool
    is_today: bool
    position: Optional[str]
    status: str

    def to_dict(self) -> Dict:
        """Serialize to plain dict for prompt injection."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "notes": self.notes,
            "due_date": self.due_date,
            "due_datetime": self.due_datetime.isoformat() if self.due_datetime else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "task_list_name": self.task_list_name,
            "is_overdue": self.is_overdue,
            "is_today": self.is_today,
            "position": self.position,
            "status": self.status,
        }


@dataclass
class TaskSummary:
    """Aggregate counts across all pending task categories."""

    today_tasks: int = 0
    overdue_tasks: int = 0
    upcoming_tasks: int = 0
    total_pending: int = 0


# ── Service ────────────────────────────────────────────────────────────────────


class TasksService:
    """
    Fetches and categorizes Google Tasks for the daily briefing.

    Reuses the shared OAuth token (token.json / credentials.json) that
    Gmail and Calendar services already maintain, with the additional
    tasks.readonly scope appended to the shared scope list.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._service = None

    # ── Authentication ─────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """
        Load OAuth credentials from token.json, refresh if expired,
        or run the browser flow to create a new token when absent.
        Mirrors the pattern used by GmailService and CalendarService.
        """
        creds: Optional[Credentials] = None

        token_path = self._settings.google_token_path
        credentials_path = self._settings.google_credentials_path

        if token_path.exists():
            logger.info("Loading existing OAuth token from %s", token_path)
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("OAuth token expired — refreshing automatically")
                creds.refresh(Request())
            else:
                logger.info("No valid token found — launching OAuth flow")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            token_path.write_text(creds.to_json())
            logger.info("OAuth token saved to %s", token_path)

        self._service = build("tasks", "v1", credentials=creds)
        logger.info("Google Tasks API client initialized")

    # ── Public async interface ─────────────────────────────────────────────────

    
    async def fetch_pending_tasks(self) -> Tuple[List[TaskItem], TaskSummary]:
        """
        Async entry point — runs the sync Tasks API calls in a thread
        executor so the event loop stays unblocked.

        Returns a tuple of (task_list, summary) where task_list contains
        only pending (non-completed, non-deleted) tasks across all lists.
        """
        loop = asyncio.get_event_loop()
        tasks, summary = await loop.run_in_executor(None, self._fetch_tasks_sync)
        logger.info(
            "Fetched %d pending tasks — overdue=%d, today=%d, upcoming=%d",
            summary.total_pending,
            summary.overdue_tasks,
            summary.today_tasks,
            summary.upcoming_tasks,
        )
        return tasks, summary

    # ── Sync implementation ────────────────────────────────────────────────────

    def _fetch_tasks_sync(self) -> Tuple[List[TaskItem], TaskSummary]:
        """
        Synchronous implementation called inside executor.

        Iterates every task list the user owns, fetches up to
        MAX_TASKS_PER_LIST tasks per list, filters out completed /
        deleted / hidden items, and returns categorized results.
        """
        all_tasks: List[TaskItem] = []
        task_lists = self._get_all_tasklists()

        if not task_lists:
            logger.warning("No task lists found for this account")
            return [], TaskSummary()

        logger.info("Discovered %d task list(s)", len(task_lists))

        for tl in task_lists:
            list_id: str = tl["id"]
            list_name: str = tl.get("title", "Unnamed List")

            try:
                response = (
                    self._service.tasks()
                    .list(
                        tasklist=list_id,
                        maxResults=MAX_TASKS_PER_LIST,
                        showCompleted=False,
                        showDeleted=False,
                        showHidden=False,
                    )
                    .execute()
                )
            except HttpError as exc:
                logger.error(
                    "HttpError fetching tasks from list '%s': %s", list_name, exc
                )
                continue

            raw_tasks = response.get("items", [])
            logger.info(
                "Task list '%s' → %d raw item(s) returned", list_name, len(raw_tasks)
            )

            for raw in raw_tasks:
                # Secondary guard: skip completed tasks even if API returned them
                if raw.get("status") == "completed":
                    logger.debug("Skipping completed task: %s", raw.get("title", ""))
                    continue

                title = raw.get("title", "").strip()
                if not title:
                    logger.debug("Skipping blank-title task in list '%s'", list_name)
                    continue

                item = self._parse_task(raw, list_name)
                all_tasks.append(item)

        summary = self._build_summary(all_tasks)
        return all_tasks, summary

    # ── Task list discovery ────────────────────────────────────────────────────

    def _get_all_tasklists(self) -> List[Dict]:
        """
        Retrieve all task lists owned by the authenticated user.
        Returns an empty list on API failure so the caller can decide
        how to handle the absence gracefully.
        """
        try:
            response = self._service.tasklists().list(maxResults=50).execute()
            return response.get("items", [])
        except HttpError as exc:
            logger.error("HttpError fetching task lists: %s", exc)
            return []
        except Exception as exc:
            logger.error("Unexpected error fetching task lists: %s", exc)
            return []

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_task(self, raw: Dict, task_list_name: str) -> TaskItem:
        """
        Convert a raw Google Tasks API item into a typed TaskItem.

        Handles:
        * RFC 3339 due dates returned as bare dates (YYYY-MM-DDT00:00:00.000Z)
        * RFC 3339 updated timestamps
        * Timezone conversion to IST
        * is_overdue / is_today computation relative to today in IST
        """
        today_ist: date = datetime.now(tz=IST).date()

        due_datetime: Optional[datetime] = None
        due_date_str: Optional[str] = raw.get("due")

        if due_date_str:
            try:
                # Google Tasks returns due as RFC 3339 midnight UTC
                due_datetime = datetime.fromisoformat(
                    due_date_str.replace("Z", "+00:00")
                ).astimezone(IST)
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed due date '%s' for task '%s' — skipping due date",
                    due_date_str,
                    raw.get("title", ""),
                )
                due_datetime = None

        updated_at: Optional[datetime] = None
        updated_str: Optional[str] = raw.get("updated")
        if updated_str:
            try:
                updated_at = datetime.fromisoformat(
                    updated_str.replace("Z", "+00:00")
                ).astimezone(IST)
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed updated timestamp '%s' for task '%s'",
                    updated_str,
                    raw.get("title", ""),
                )

        due_date_only: Optional[date] = due_datetime.date() if due_datetime else None
        is_overdue: bool = bool(due_date_only and due_date_only < today_ist)
        is_today: bool = bool(due_date_only and due_date_only == today_ist)

        return TaskItem(
            task_id=raw.get("id", ""),
            title=raw.get("title", "").strip(),
            notes=raw.get("notes") or None,
            due_date=due_date_str,
            due_datetime=due_datetime,
            updated_at=updated_at,
            task_list_name=task_list_name,
            is_overdue=is_overdue,
            is_today=is_today,
            position=raw.get("position") or None,
            status=raw.get("status", "needsAction"),
        )

    # ── Categorization ─────────────────────────────────────────────────────────

    def categorize_tasks(
        self, tasks: List[TaskItem]
    ) -> Dict[str, List[TaskItem]]:
        """
        Split a flat task list into named category buckets.

        Returns:
            {
                "overdue":   [...],
                "today":     [...],
                "upcoming":  [...],
                "no_date":   [...],
            }
        """
        categories: Dict[str, List[TaskItem]] = {
            "overdue": [],
            "today": [],
            "upcoming": [],
            "no_date": [],
        }

        for task in tasks:
            if task.is_overdue:
                categories["overdue"].append(task)
            elif task.is_today:
                categories["today"].append(task)
            elif task.due_datetime:
                categories["upcoming"].append(task)
            else:
                categories["no_date"].append(task)

        logger.info(
            "Categorized tasks — overdue=%d, today=%d, upcoming=%d, no_date=%d",
            len(categories["overdue"]),
            len(categories["today"]),
            len(categories["upcoming"]),
            len(categories["no_date"]),
        )
        return categories

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_summary(self, tasks: List[TaskItem]) -> TaskSummary:
        """Compute aggregate counts from a flat list of TaskItems."""
        overdue = sum(1 for t in tasks if t.is_overdue)
        today = sum(1 for t in tasks if t.is_today)
        upcoming = sum(1 for t in tasks if not t.is_overdue and not t.is_today)
        return TaskSummary(
            today_tasks=today,
            overdue_tasks=overdue,
            upcoming_tasks=upcoming,
            total_pending=len(tasks),
        )
