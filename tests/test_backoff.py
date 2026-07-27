"""Tests for exponential backoff logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from harness.backoff import backoff_call


class FakeRateLimitError(Exception):
    pass


class FakeAuthError(Exception):
    pass


# Patch the retryable exceptions for testing
@pytest.fixture(autouse=True)
def _patch_retryable(monkeypatch):
    import harness.backoff as mod

    monkeypatch.setattr(mod, "_RETRYABLE", (FakeRateLimitError,))
    monkeypatch.setattr(mod, "MAX_TRIES", 3)
    monkeypatch.setattr(mod, "MAX_TIME", 10.0)
    monkeypatch.setattr(mod, "BASE_FACTOR", 0.01)  # fast tests


@pytest.mark.asyncio
async def test_succeeds_first_try() -> None:
    fn = AsyncMock(return_value="ok")
    result = await backoff_call(fn, "arg1", key="val")
    assert result == "ok"
    fn.assert_called_once_with("arg1", key="val")


@pytest.mark.asyncio
async def test_retries_on_rate_limit() -> None:
    fn = AsyncMock(side_effect=[FakeRateLimitError("429"), "ok"])
    result = await backoff_call(fn)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
async def test_exhausts_retries() -> None:
    fn = AsyncMock(side_effect=FakeRateLimitError("always 429"))
    with pytest.raises(FakeRateLimitError, match="always 429"):
        await backoff_call(fn)
    assert fn.call_count == 3  # MAX_TRIES


@pytest.mark.asyncio
async def test_non_retryable_propagates_immediately() -> None:
    fn = AsyncMock(side_effect=FakeAuthError("401 unauthorized"))
    with pytest.raises(FakeAuthError, match="401"):
        await backoff_call(fn)
    fn.assert_called_once()  # no retry


@pytest.mark.asyncio
async def test_recovers_after_multiple_failures() -> None:
    fn = AsyncMock(side_effect=[FakeRateLimitError("1"), FakeRateLimitError("2"), "recovered"])
    result = await backoff_call(fn)
    assert result == "recovered"
    assert fn.call_count == 3
