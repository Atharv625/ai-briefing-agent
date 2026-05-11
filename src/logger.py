"""
logger.py - Structured logging with rich formatting for local dev,
JSON output for production (Cloud Run / Cloud Logging compatible).
"""

import logging
import sys
from functools import lru_cache
from typing import Optional


class JSONFormatter(logging.Formatter):
    """
    Outputs log records as single-line JSON for Cloud Logging ingestion.
    Cloud Run captures stdout → Cloud Logging automatically parses JSON.
    """

    import json as _json

    def format(self, record: logging.LogRecord) -> str:
        import json
        import traceback

        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload)


class ColorFormatter(logging.Formatter):
    """
    Colorized formatter for local development readability.
    """

    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"
    FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        formatter = logging.Formatter(
            f"{color}{self.FMT}{self.RESET}",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        return formatter.format(record)


@lru_cache(maxsize=None)
def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Returns a named logger. Creates it with the right handler on first call.

    Usage:
        from src.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Hello")
    """
    from src.config import get_settings

    settings = get_settings()
    log_level = getattr(logging, level or settings.log_level, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid adding duplicate handlers if function is called multiple times
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if settings.environment == "production":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ColorFormatter())

    logger.addHandler(handler)
    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    return logger
