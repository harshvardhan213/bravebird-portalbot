"""Bounded retries with exponential backoff.

Retryable: RetryableError and Playwright timeouts / network errors.
Final: FinalError (bad password, rejected code, missing element, form mismatch)
and anything unexpected. Those fail straight away; retrying would only repeat them.
"""
from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import Error as PlaywrightError, TimeoutError as PWTimeout

from .errors import FinalError, RetryableError

log = logging.getLogger("portalbot.retry")


def is_retryable(e: Exception) -> bool:
    if isinstance(e, FinalError):
        return False
    if isinstance(e, (RetryableError, PWTimeout)):
        return True
    return isinstance(e, PlaywrightError) and "net::" in str(e)  # e.g. net::ERR_CONNECTION_RESET


async def with_retry(stage: str, fn, attempts: int = 3, base_delay: float = 2.0):
    """Run `fn()` up to `attempts` times; wait 2s, 4s, ... (plus jitter) between tries."""
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as e:
            if not is_retryable(e) or attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1) + random.uniform(0, 1)
            log.warning("%s: %s: %s, retrying in %.1fs (attempt %d/%d)",
                        stage, type(e).__name__, e, delay, attempt + 1, attempts)
            await asyncio.sleep(delay)
