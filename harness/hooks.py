"""RunHooksBase subclass: accumulates steps for ATIF export."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from agents.lifecycle import RunHooksBase
from loguru import logger

from .models import StepRecord


class StealthBenchHooks(RunHooksBase):
    """Captures tool calls into StepRecord list + token totals."""

    def __init__(self) -> None:
        self.steps: list[StepRecord] = []
        self.step_index: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self._current_tool: str = ""
        self._current_start: float = 0.0
        self._current_args: dict = {}

    async def on_tool_start(self, context, agent, tool) -> None:  # type: ignore[no-untyped-def]
        self._current_tool = getattr(tool, "name", str(tool))
        self._current_start = time.monotonic()
        self._current_args = {}
        logger.debug("tool:start | {}", self._current_tool)
        # ToolContext.tool_arguments is a JSON string (openai-agents v0.18.0).
        # Fall back to tool_input (parsed dict) on some tool families.
        raw = None
        try:
            raw = getattr(context, "tool_arguments", None)
        except Exception:  # noqa: BLE001
            raw = None
        if isinstance(raw, str):
            try:
                self._current_args = json.loads(raw)
            except json.JSONDecodeError:
                self._current_args = {"raw": raw}
        elif isinstance(raw, dict):
            self._current_args = raw
        else:
            # Fallback: tool.args (some tool families don't populate context)
            raw_tool_args = getattr(tool, "args", None)
            if isinstance(raw_tool_args, dict):
                self._current_args = raw_tool_args

    async def on_tool_end(self, context, agent, tool, result) -> None:  # type: ignore[no-untyped-def]
        try:
            latency = (
                int((time.monotonic() - self._current_start) * 1000)
                if self._current_start
                else None
            )
            output_str = str(result)
            self.steps.append(
                StepRecord(
                    index=self.step_index,
                    tool=self._current_tool,
                    input=self._current_args,
                    output=output_str,
                    timestamp=datetime.now(UTC).isoformat(),
                    latency_ms=latency,
                )
            )
            logger.info(
                "step:{idx} | {tool} | {ms}ms | {out}",
                idx=self.step_index,
                tool=self._current_tool,
                ms=latency or "?",
                out=output_str[:200],
            )
            self.step_index += 1
        except Exception:  # noqa: BLE001 — hooks must never break the run
            pass
        finally:
            self._current_start = 0.0

    async def on_llm_end(self, context, agent, response) -> None:  # type: ignore[no-untyped-def]
        try:
            usage = getattr(response, "usage", None)
            if usage is not None:
                inp = getattr(usage, "input_tokens", 0) or 0
                out = getattr(usage, "output_tokens", 0) or 0
                self.total_input_tokens += inp
                self.total_output_tokens += out
                logger.debug("llm:end | in={} out={} total={}", inp, out, inp + out)
        except Exception:  # noqa: BLE001
            pass
