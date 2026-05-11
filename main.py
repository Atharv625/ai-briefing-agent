"""
main.py - Application entry point.

Usage:
    # Run briefing once (local test or Cloud Run Job)
    python main.py --run-now

    # Run with cron scheduler (local / VM)
    python main.py --schedule

    # Test Telegram connection only
    python main.py --test-telegram

    # Run OAuth2 setup flow
    python main.py --setup-oauth
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure src/ is on the path when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.agents.briefing_agent import BriefingAgent
from src.config import get_settings
from src.logger import get_logger

logger = get_logger(__name__)


async def test_telegram():
    """Quick test that the Telegram bot can reach the configured chat."""
    from src.services.telegram_service import TelegramService
    svc = TelegramService()
    ok = await svc.test_connection()
    if ok:
        result = await svc.send_message(
            "✅ <b>Test message from AI Briefing Agent</b>\n"
            "Telegram integration is working correctly!",
            parse_mode="HTML",
        )
        print("✅ Telegram test passed!" if result else "❌ Message send failed.")
    else:
        print("❌ Telegram connection test failed. Check TELEGRAM_BOT_TOKEN.")
    return ok


async def setup_oauth():
    """
    Runs the OAuth2 browser flow to generate/refresh the token.
    Must be run locally with a display (not in CI/headless).
    """
    from src.services.gmail_service import GmailService
    print("\n🔐 Starting Google OAuth2 setup...\n")
    print("A browser window will open. Sign in and grant the requested permissions.")
    print("The token will be saved to config/token.json for future use.\n")
    svc = GmailService()
    svc.authenticate()
    print("\n✅ OAuth2 setup complete! Token saved to config/token.json")
    print("You can now run: python main.py --run-now\n")

async def run_briefing():
    """Run briefing programmatically (used by AWS Lambda)."""

    logger.info("Running briefing in Lambda mode...")

    agent = BriefingAgent()

    result = await agent.run()

    logger.info(result.summary())

    return result
    
def main():
    parser = argparse.ArgumentParser(
        description="AI Daily Briefing Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --setup-oauth       # First-time Google auth setup
  python main.py --test-telegram     # Verify Telegram bot works
  python main.py --run-now           # Generate and send briefing now
  python main.py --schedule          # Start cron-based scheduler
        """,
    )
    parser.add_argument("--run-now", action="store_true", help="Run briefing immediately")
    parser.add_argument("--schedule", action="store_true", help="Start scheduler")
    parser.add_argument("--test-telegram", action="store_true", help="Test Telegram connection")
    parser.add_argument("--setup-oauth", action="store_true", help="Run OAuth2 setup flow")
    parser.add_argument("--version", action="version", version="AI Briefing Agent v1.0.0")

    args = parser.parse_args()

    # Load and validate config early
    try:
        settings = get_settings()
        logger.info("Config loaded for environment: %s", settings.environment)
    except Exception as exc:
        print(f"❌ Configuration error: {exc}")
        print("Make sure your .env file is complete. See .env.example for reference.")
        sys.exit(1)

    if args.setup_oauth:
        asyncio.run(setup_oauth())

    elif args.test_telegram:
        success = asyncio.run(test_telegram())
        sys.exit(0 if success else 1)

    elif args.run_now:
        logger.info("Running briefing in immediate mode...")
        agent = BriefingAgent()
        result = asyncio.run(agent.run())
        print(f"\n{result.summary()}")
        sys.exit(0 if result.success else 1)

    elif args.schedule:
        from src.scheduler import run_scheduled
        asyncio.run(run_scheduled())

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
