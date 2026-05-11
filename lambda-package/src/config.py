"""
config.py - Central configuration management using Pydantic Settings.
All secrets and settings loaded from environment variables or .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Pydantic validates types and provides defaults.
    """

    # ── Google OAuth2 ──────────────────────────────────────────────────────────
    google_client_id: str = Field(..., env="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., env="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8080/oauth2callback",
        env="GOOGLE_REDIRECT_URI",
    )
    # Path to downloaded OAuth2 credentials JSON from Google Cloud Console
    google_credentials_path: Path = Field(
        default=Path("config/credentials.json"),
        env="GOOGLE_CREDENTIALS_PATH",
    )
    # Where to store the OAuth2 token after first-time auth
    google_token_path: Path = Field(
        default=Path("config/token.json"),
        env="GOOGLE_TOKEN_PATH",
    )

    # ── Gmail settings ─────────────────────────────────────────────────────────
    gmail_max_emails: int = Field(default=20, env="GMAIL_MAX_EMAILS")
    gmail_hours_lookback: int = Field(default=24, env="GMAIL_HOURS_LOOKBACK")

    # ── Calendar settings ──────────────────────────────────────────────────────
    calendar_id: str = Field(default="primary", env="CALENDAR_ID")

    # ── Gemini AI ──────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-2.5-flash", env="GEMINI_MODEL"
    )
    gemini_temperature: float = Field(default=0.4, env="GEMINI_TEMPERATURE")
    gemini_max_tokens: int = Field(default=2048, env="GEMINI_MAX_TOKENS")

    # ── OpenAI (fallback) ──────────────────────────────────────────────────────
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", env="OPENAI_MODEL")

    # ── Telegram ───────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(..., env="TELEGRAM_CHAT_ID")
    telegram_parse_mode: str = Field(default="HTML", env="TELEGRAM_PARSE_MODE")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    briefing_cron: str = Field(default="0 7 * * *", env="BRIEFING_CRON")
    timezone: str = Field(default="Asia/Kolkata", env="TIMEZONE")

    # ── App ────────────────────────────────────────────────────────────────────
    app_name: str = Field(default="AI Daily Briefing Agent", env="APP_NAME")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    environment: str = Field(default="development", env="ENVIRONMENT")
    retry_max_attempts: int = Field(default=3, env="RETRY_MAX_ATTEMPTS")
    retry_backoff_seconds: float = Field(default=2.0, env="RETRY_BACKOFF_SECONDS")

    # ── Future: Multi-user / SaaS ──────────────────────────────────────────────
    enable_multi_user: bool = Field(default=False, env="ENABLE_MULTI_USER")
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")  # token store

    # ── Future: Vector Memory / RAG ────────────────────────────────────────────
    enable_vector_memory: bool = Field(default=False, env="ENABLE_VECTOR_MEMORY")
    pinecone_api_key: Optional[str] = Field(default=None, env="PINECONE_API_KEY")
    pinecone_index: Optional[str] = Field(default=None, env="PINECONE_INDEX")

    # ── Future: Notion ─────────────────────────────────────────────────────────
    notion_token: Optional[str] = Field(default=None, env="NOTION_TOKEN")
    notion_database_id: Optional[str] = Field(default=None, env="NOTION_DATABASE_ID")

    # ── Future: Slack ──────────────────────────────────────────────────────────
    slack_bot_token: Optional[str] = Field(default=None, env="SLACK_BOT_TOKEN")
    slack_channel_id: Optional[str] = Field(default=None, env="SLACK_CHANNEL_ID")

    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    @validator("environment")
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v.lower() not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v.lower()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached singleton instance of Settings.
    Use this everywhere instead of instantiating Settings directly.
    """
    return Settings()
