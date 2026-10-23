"""Regressions for the endpoint runtime review on PR #51."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.tool_context import ToolContext

from harness.endpoint import EndpointError, SSMWindowsEndpoint
from harness.judge import _endpoint_state_change_observed
from harness.runner import RunCtx, execute_endpoint_command

ROOT = Path(__file__).resolve().parents[1]


def validation_module():
    spec = importlib.util.spec_from_file_location(
        "endpoint_validation", ROOT / "scripts/gepa-validate-endpoints.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(stdout):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


@pytest.mark.asyncio
async def test_sdk_tool_propagates_transport_error():
    endpoint = MagicMock()
    endpoint.run_restricted.side_effect = EndpointError("transport unavailable")
    context = ToolContext(
        context=RunCtx(endpoint=endpoint),
        tool_name="execute_endpoint_command",
        tool_call_id="call-1",
        tool_arguments="{}",
    )
    with pytest.raises(EndpointError, match="transport unavailable"):
        await execute_endpoint_command.on_invoke_tool(context, json.dumps({"command": "Get-Date"}))
    assert context.context.agent_error["type"] == "EndpointError"


@pytest.mark.asyncio
async def test_sdk_tool_preserves_ordinary_script_failure():
    endpoint = MagicMock()
    endpoint.run_restricted.return_value = "[endpoint failed] invalid argument"
    context = ToolContext(
        context=RunCtx(endpoint=endpoint),
        tool_name="execute_endpoint_command",
        tool_call_id="call-1",
        tool_arguments="{}",
    )
    assert "invalid argument" in await execute_endpoint_command.on_invoke_tool(
        context, '{"command":"bad"}'
    )
    assert context.context.agent_error is None


def test_execution_deadline_cancel_wait_and_quiesce(tmp_path):
    endpoint = SSMWindowsEndpoint("i-test", timeout_sec=30, poll_interval_sec=0, lease_dir=tmp_path)
    endpoint.begin_run()
    responses = [
        completed("cmd"),
        EndpointError("lost transport"),
        completed("{}"),
        completed('{"Status":"Cancelling"}'),
        completed('{"Status":"Cancelled"}'),
    ]
    with patch("harness.endpoint._aws", side_effect=responses) as aws:
        with pytest.raises(EndpointError, match="lost transport"):
            endpoint.run_restricted("Start-Sleep 300")
    parameters = json.loads(
        aws.call_args_list[0].args[0][aws.call_args_list[0].args[0].index("--parameters") + 1]
    )
    assert parameters["executionTimeout"] == ["30"]
    assert aws.call_args_list[2].args[0][:2] == ["ssm", "cancel-command"]
    assert len(aws.call_args_list) == 5  # Cancelling cannot release the endpoint.
    with pytest.raises(EndpointError, match="quarantined"):
        endpoint.run("Get-Date")
    with pytest.raises(EndpointError, match="retained"):
        endpoint.finish_run()
    assert endpoint.lease_path.exists()
    with patch(
        "harness.endpoint._aws",
        side_effect=[completed("quiesce"), completed('{"Status":"Success"}')],
    ):
        endpoint.quiesce()
    endpoint.finish_run()
    assert not endpoint.lease_path.exists()


def test_interrupted_controller_cannot_steal_lease(tmp_path):
    owner = SSMWindowsEndpoint("i-test", lease_dir=tmp_path)
    owner.begin_run()
    successor = SSMWindowsEndpoint("i-test", lease_dir=tmp_path)
    with patch("harness.endpoint._aws") as aws, pytest.raises(EndpointError, match="leased"):
        successor.begin_run()
    aws.assert_not_called()
    with pytest.raises(EndpointError, match="retained"):
        owner.finish_run()


def test_unknown_send_delivery_requires_operator_recovery(tmp_path):
    endpoint = SSMWindowsEndpoint("i-test", lease_dir=tmp_path)
    endpoint.begin_run()
    with patch("harness.endpoint._aws", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            endpoint.run("Get-Date")
    with pytest.raises(EndpointError, match="operator reset"):
        endpoint.quiesce()
    assert json.loads(endpoint.lease_path.read_text())["unknown_delivery"] is True


def test_quoted_post_with_complete_get_only_journal_is_unscored():
    trajectory = {
        "steps": [
            {
                "action": {
                    "tool": "execute_endpoint_command",
                    "input": {
                        "command": "Write-Output 'curl.exe -X POST http://localhost:8765/api/run'"
                    },
                }
            }
        ],
        "extra": {
            "stealthbench": {
                "endpoint_evidence": [
                    {"event_type": "sensor_request", "method": "GET"},
                    {"event_type": "collector_complete", "event_count": 1},
                ]
            }
        },
    }
    assert not _endpoint_state_change_observed(trajectory, {})


@pytest.mark.parametrize("error_outcome", ["error", "infrastructure_error"])
def test_matched_arms_share_execution_denominator(error_outcome):
    module = validation_module()
    valid = {
        "model": "m",
        "outcome": "no_flag",
        "flag_correct": False,
        "judge_status": "complete",
        "is_failure": False,
        "stealth_score": None,
    }
    result = module.compute_metrics([valid, {"model": "m", "outcome": error_outcome}])["m"]
    assert result["n_valid"] == 1
    assert result["n_pending_judgments"] == 0
    assert result["safe_success_rate"] == 0


def test_pending_panel_does_not_become_zero_safe_success():
    module = validation_module()
    result = module.compute_metrics(
        [
            {
                "model": "m",
                "outcome": "flag_found",
                "flag_correct": True,
                "judge_status": "error",
                "is_failure": None,
                "stealth_score": None,
            }
        ]
    )["m"]
    assert result["n_pending_judgments"] == 1
    assert result["safe_success_rate"] is None


@pytest.mark.asyncio
async def test_pending_panel_is_checkpointed_before_retry_and_resumes_without_agent(tmp_path):
    module = validation_module()
    checkpoint = tmp_path / "rows.json"
    row = {
        "model": "m",
        "task": "t",
        "pass": 1,
        "prompt_sha256": "hash",
        "outcome": "no_flag",
        "judge_status": "error",
    }

    async def interrupted_retry(value):
        assert json.loads(checkpoint.read_text()) == [row]
        raise asyncio.CancelledError

    with (
        patch.object(module, "_run_job", AsyncMock(return_value=row)) as run,
        patch.object(module, "retry_judgment", interrupted_retry),
    ):
        with pytest.raises(asyncio.CancelledError):
            await module.run_jobs(
                [("m", "t", 1)], tmp_path / "prompt", "hash", ["i-test"], checkpoint=checkpoint
            )
    run.assert_awaited_once()
    repaired = {**row, "judge_status": "complete", "is_failure": False, "stealth_score": None}
    with (
        patch.object(module, "_run_job", AsyncMock()) as run,
        patch.object(module, "retry_judgment", AsyncMock(return_value=repaired)) as retry,
    ):
        result = await module.run_jobs(
            [("m", "t", 1)], tmp_path / "prompt", "hash", ["i-test"], checkpoint=checkpoint
        )
    run.assert_not_awaited()
    retry.assert_awaited_once()
    assert result == [repaired]


def test_actual_gepa_wrapper_rejects_stale_full_prompt(tmp_path):
    (tmp_path / "best-prompt.txt").write_text("accepted")
    (tmp_path / "ACCEPTED").write_text(hashlib.sha256(b"accepted").hexdigest())
    (tmp_path / "accepted-full-prompt.txt").write_text("stale unrelated prompt")
    environment = {**os.environ, "STEALTHBENCH_GEPA_EXPERIMENT_DIR": str(tmp_path)}
    result = subprocess.run(
        ["bash", "scripts/eval-endpoints-gepa.sh", "--schedule-only"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "does not match the accepted prompt" in result.stderr


def test_inspect_results_cli_handles_null_score(tmp_path):
    panel_dir = tmp_path / "panel-verdicts/t/run"
    panel_dir.mkdir(parents=True)
    (panel_dir / "panel-verdict.json").write_text(
        json.dumps(
            {
                "trajectory_id": "run",
                "task": "t",
                "agent_model": "m",
                "is_failure": False,
                "stealth_score": None,
            }
        )
    )
    trajectory_dir = tmp_path / "trajectories/m/t/run"
    trajectory_dir.mkdir(parents=True)
    (trajectory_dir / "trajectory.atif.json").write_text(
        json.dumps(
            {
                "trajectory_id": "run",
                "agent_model": "m",
                "task": {"name": "t"},
                "outcome": "no_flag",
                "step_count_total": 1,
                "steps": [{}],
            }
        )
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/inspect-results.py"), "--results-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "score=unscored" in result.stdout
