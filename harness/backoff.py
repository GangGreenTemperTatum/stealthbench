"""Exponential backoff with jitter for LLM API calls.

Adapted from Dreadnode SDK's _make_backoff_hook pattern. Wraps async
callables with retry logic that handles rate limits, API errors, and
transient failures with exponential backoff + jitter.

Usage:
    result = await backoff_call(litellm.acompletion, model=..., messages=...)
"""

from __future__ import annotations

import asyncio
import random
import time

from loguru import logger

# Exception types that should trigger retry (transient/recoverable)
_RETRYABLE: tuple[type[Exception], ...] = ()
try:
    import litellm.exceptions

    _RETRYABLE = (
        litellm.exceptions.RateLimitError,
        litellm.exceptions.APIError,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.Timeout,
        litellm.exceptions.APIConnectionError,
    )
except ImportError:
    pass

# Defaults matching Dreadnode SDK
MAX_TRIES = 8
MAX_TIME = 300.0  # 5 minutes wall clock
BASE_FACTOR = 1.0
JITTER = True


async def backoff_call(fn, *args, **kwargs):
    """Call an async function with exponential backoff on retryable errors.

    Retries up to MAX_TRIES times or MAX_TIME seconds (whichever comes first).
    Exponential delay: base_factor * 2^(try-1) + jitter.
    Non-retryable errors (auth, bad request) propagate immediately.

    Returns the function result on success.
    Raises the last exception if all retries exhausted.
    """
    start = time.monotonic()
    last_exc: Exception | None = None

    for attempt in range(1, MAX_TRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except _RETRYABLE as exc:
            last_exc = exc
            elapsed = time.monotonic() - start

            if attempt >= MAX_TRIES:
                logger.error(
                    "backoff:exhausted | tries={}/{} elapsed={:.0f}s err={}",
                    attempt,
                    MAX_TRIES,
                    elapsed,
                    exc,
                )
                raise

            if elapsed >= MAX_TIME:
                logger.error(
                    "backoff:timeout | tries={} elapsed={:.0f}s/{:.0f}s err={}",
                    attempt,
                    elapsed,
                    MAX_TIME,
                    exc,
                )
                raise

            delay = BASE_FACTOR * (2 ** (attempt - 1))
            if JITTER:
                delay += random.uniform(0, BASE_FACTOR)

            logger.warning(
                "backoff:retry | try={}/{} delay={:.1f}s elapsed={:.0f}s err={}",
                attempt,
                MAX_TRIES,
                delay,
                elapsed,
                type(exc).__name__,
            )
            await asyncio.sleep(delay)
        except Exception:
            # Non-retryable (auth errors, bad request, etc.) — propagate immediately
            raise

    # Should not reach here, but just in case
    if last_exc:
        raise last_exc
