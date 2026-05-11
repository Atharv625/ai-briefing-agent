"""
scheduler.py - Cron-based scheduler using APScheduler.

Supports two modes:
  1. --run-now : Execute briefing immediately (for testing / CI / Cloud Run Jobs)
  2. --schedule : Start long-running process with cron-based scheduling
                  (for running locally or on a VM)

Cloud Run + Cloud Scheduler calls the container with --run-now,
so the container exits after one briefing (stateless, cost-efficient).
"""

import argparse
import asyncio
import signal
import sys

from src.agents.briefing_agent import BriefingAgent
from src.config import get_settings
from src.logger import get_logger

logger = get_logger(__name__)


async def run_briefing() -> bool:
    """Run a single briefing and return success status."""
    agent = BriefingAgent()
    result = await agent.run()
    return result.success


async def run_scheduled():
    """
    Start the APScheduler cron loop.
    Runs indefinitely until interrupted (Ctrl+C or SIGTERM).
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error(
            "APScheduler not installed. Run: pip install apscheduler"
        )
        sys.exit(1)

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    # Parse cron expression from config (e.g., "0 7 * * *" = 7:00 AM daily)
    cron_parts = settings.briefing_cron.split()
    if len(cron_parts) != 5:
        raise ValueError(
            f"Invalid BRIEFING_CRON format: '{settings.briefing_cron}'. "
            "Expected 5 parts: minute hour day month weekday"
        )

    trigger = CronTrigger(
        minute=cron_parts[0],
        hour=cron_parts[1],
        day=cron_parts[2],
        month=cron_parts[3],
        day_of_week=cron_parts[4],
        timezone=settings.timezone,
    )

    scheduler.add_job(
        func=run_briefing,
        trigger=trigger,
        id="daily_briefing",
        name="AI Daily Briefing",
        misfire_grace_time=300,  # Allow up to 5 min late execution
        coalesce=True,           # Skip if missed multiple times
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Briefing will run at cron: '%s' (%s)",
        settings.briefing_cron,
        settings.timezone,
    )

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info("Received signal %s. Shutting down scheduler...", sig)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Keep running until shutdown signal
    await stop_event.wait()
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped cleanly.")


def main():
    """Entry point. Parses CLI args and dispatches to the right mode."""
    parser = argparse.ArgumentParser(description="AI Daily Briefing Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--run-now",
        action="store_true",
        help="Run briefing immediately and exit (used by Cloud Run Jobs / CI)",
    )
    group.add_argument(
        "--schedule",
        action="store_true",
        help="Start long-running scheduled mode (local / VM deployment)",
    )

    args = parser.parse_args()

    if args.run_now:
        logger.info("Running briefing immediately (--run-now mode)...")
        success = asyncio.run(run_briefing())
        sys.exit(0 if success else 1)

    elif args.schedule:
        logger.info("Starting scheduled mode (--schedule mode)...")
        asyncio.run(run_scheduled())


if __name__ == "__main__":
    main()
