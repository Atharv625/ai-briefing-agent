"""
utils/date_utils.py - Timezone-aware date/time utilities.
All times are handled in the user's configured timezone for correct
"today" / "past 24 hours" calculations.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo  # Python 3.9+

from src.config import get_settings


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_local() -> datetime:
    """Current datetime in the configured timezone."""
    return datetime.now(_tz())


def today_start() -> datetime:
    """Midnight of today in the configured timezone, UTC-offset-aware."""
    local_now = now_local()
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0)


def today_end() -> datetime:
    """23:59:59 of today in the configured timezone."""
    return today_start() + timedelta(days=1) - timedelta(seconds=1)


def hours_ago(hours: int) -> datetime:
    """Datetime N hours in the past, timezone-aware."""
    return now_local() - timedelta(hours=hours)


def to_utc_rfc3339(dt: datetime) -> str:
    """
    Convert a local datetime to UTC RFC-3339 string for Google API queries.
    Example: '2024-01-15T00:00:00Z'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz())
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_event_time(dt_str: str, all_day: bool = False) -> str:
    """
    Format a Google Calendar datetime string for display.
    Handles both full datetime ('2024-01-15T10:00:00+05:30')
    and date-only ('2024-01-15') for all-day events.
    """
    if all_day:
        return "All Day"
    try:
        dt = datetime.fromisoformat(dt_str)
        local_dt = dt.astimezone(_tz())
        return local_dt.strftime("%I:%M %p")
    except (ValueError, TypeError):
        return dt_str
