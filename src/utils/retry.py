"""
utils/retry.py - Async-compatible retry decorator with exponential backoff.
Handles transient API failures (rate limits, network errors, timeouts).
"""

import asyncio
import functools
import time
from typing import Callable, Optional, Tuple, Type

from src.logger import get_logger

logger = get_logger(__name__)


def with_retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Decorator factory for automatic retry with exponential backoff.

    Args:
        max_attempts: Maximum number of total attempts (including first try).
        backoff: Base backoff in seconds; doubles each attempt.
        exceptions: Which exception types trigger a retry.
        on_retry: Optional callback called before each retry (for logging / alerts).

    Usage:
        @with_retry(max_attempts=3, backoff=2.0, exceptions=(httpx.HTTPError,))
        async def call_api(): ...
    """

    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            attempt = 0
            delay = backoff
            while attempt < max_attempts:
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"[retry] {func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    logger.warning(
                        f"[retry] {func.__name__} attempt {attempt}/{max_attempts} failed "
                        f"({type(exc).__name__}: {exc}). Retrying in {delay:.1f}s..."
                    )
                    if on_retry:
                        on_retry(attempt, exc)
                    await asyncio.sleep(delay)
                    delay *= 2  # Exponential backoff

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            attempt = 0
            delay = backoff
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"[retry] {func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    logger.warning(
                        f"[retry] {func.__name__} attempt {attempt}/{max_attempts} failed. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    if on_retry:
                        on_retry(attempt, exc)
                    time.sleep(delay)
                    delay *= 2

        return async_wrapper if is_async else sync_wrapper

    return decorator
