from __future__ import annotations

import json

import pytest

from harness.hooks import StealthBenchHooks
from harness.models import StepRecord


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, usage: _FakeUsage | None) -> None:
        self.usage = usage


class _FakeTool:
    def __init__(self, name: str, args: dict | None = None) -> None:
        self.name = name
        self.args = args


class _FakeCtx:
    """Mimics ToolContext — tool_arguments is a JSON string per SDK v0.18.0."""

    def __init__(self, args: str | dict | None = None, tool_input: dict | None = None) -> None:
        if isinstance(args, dict):
            self.tool_arguments = json.dumps(args)
        else:
            self.tool_arguments = args
        self.tool_input = tool_input


@pytest.mark.asyncio
async def test_on_tool_end_accumulates_step() -> None:
    hooks = StealthBenchHooks()
    await hooks.on_tool_start(_FakeCtx({"cmd": "ls"}), agent=None, tool=_FakeTool("bash"))
    await hooks.on_tool_end(_FakeCtx(), agent=None, tool=_FakeTool("bash"), result="file.txt")
    assert len(hooks.steps) == 1
    s = hooks.steps[0]
    assert isinstance(s, StepRecord)
    assert s.index == 0
    assert s.tool == "bash"
    assert s.input == {"cmd": "ls"}
    assert s.output == "file.txt"
    assert s.latency_ms is not None and s.latency_ms >= 0


@pytest.mark.asyncio
async def test_on_tool_end_increments_index() -> None:
    hooks = StealthBenchHooks()
    for i in range(3):
        await hooks.on_tool_start(_FakeCtx({}), agent=None, tool=_FakeTool("t"))
        await hooks.on_tool_end(_FakeCtx(), agent=None, tool=_FakeTool("t"), result=f"r{i}")
    assert [s.index for s in hooks.steps] == [0, 1, 2]
    assert hooks.step_index == 3


@pytest.mark.asyncio
async def test_on_llm_end_accumulates_tokens() -> None:
    hooks = StealthBenchHooks()
    await hooks.on_llm_end(None, agent=None, response=_FakeResponse(_FakeUsage(100, 50)))
    await hooks.on_llm_end(None, agent=None, response=_FakeResponse(_FakeUsage(20, 10)))
    assert hooks.total_input_tokens == 120
    assert hooks.total_output_tokens == 60


@pytest.mark.asyncio
async def test_on_llm_end_missing_usage() -> None:
    hooks = StealthBenchHooks()
    await hooks.on_llm_end(None, agent=None, response=_FakeResponse(None))
    assert hooks.total_input_tokens == 0
    assert hooks.total_output_tokens == 0


@pytest.mark.asyncio
async def test_tool_arguments_json_string_parsed() -> None:
    """I8: SDK passes tool_arguments as a JSON string — must be parsed into a dict."""
    hooks = StealthBenchHooks()
    await hooks.on_tool_start(
        _FakeCtx({"command": "curl -s http://localhost:5001/"}),
        agent=None,
        tool=_FakeTool("execute_command"),
    )
    await hooks.on_tool_end(_FakeCtx(), agent=None, tool=_FakeTool("execute_command"), result="200")
    assert hooks.steps[0].input == {"command": "curl -s http://localhost:5001/"}


@pytest.mark.asyncio
async def test_tool_arguments_invalid_json_fallback() -> None:
    """I8: invalid JSON string falls back to {'raw': <string>}."""
    hooks = StealthBenchHooks()
    await hooks.on_tool_start(_FakeCtx(args="not json at all"), agent=None, tool=_FakeTool("t"))
    await hooks.on_tool_end(_FakeCtx(), agent=None, tool=_FakeTool("t"), result="r")
    assert hooks.steps[0].input == {"raw": "not json at all"}


@pytest.mark.asyncio
async def test_tool_arguments_none_falls_back_to_tool_args() -> None:
    """I8: when tool_arguments is None, fall back to tool.args."""
    hooks = StealthBenchHooks()
    await hooks.on_tool_start(
        _FakeCtx(args=None), agent=None, tool=_FakeTool("t", args={"cmd": "ls"})
    )
    await hooks.on_tool_end(_FakeCtx(), agent=None, tool=_FakeTool("t"), result="r")
    assert hooks.steps[0].input == {"cmd": "ls"}


@pytest.mark.asyncio
async def test_total_tokens_precedence_safe() -> None:
    """I4: total_tokens computation should not crash when output tokens are 0."""
    hooks = StealthBenchHooks()
    await hooks.on_llm_end(None, agent=None, response=_FakeResponse(_FakeUsage(100, 0)))
    total = (hooks.total_input_tokens + hooks.total_output_tokens) or None
    assert total == 100
