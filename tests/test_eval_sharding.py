"""Contract tests for deterministic multi-host evaluation sharding."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _schedule(index: int, count: int = 4) -> list[str]:
    env = os.environ.copy()
    env.update(
        {
            "STEALTHBENCH_MODELS_CSV": "model-a,model-b,model-c",
            "STEALTHBENCH_TASKS_CSV": "task-a,task-b",
            "STEALTHBENCH_PASSES": "2",
            "STEALTHBENCH_SCHEDULE_SEED": "fixed-seed",
            "STEALTHBENCH_SHARD_COUNT": str(count),
            "STEALTHBENCH_SHARD_INDEX": str(index),
        }
    )
    result = subprocess.run(
        ["./scripts/eval-full.sh", "--schedule-only"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def test_four_shards_are_complete_balanced_and_disjoint() -> None:
    shards = [_schedule(index) for index in range(4)]
    flattened = [item for shard in shards for item in shard]

    assert [len(shard) for shard in shards] == [3, 3, 3, 3]
    assert len(flattened) == 12
    assert len(set(flattened)) == 12


def test_sharding_is_deterministic() -> None:
    assert _schedule(2) == _schedule(2)


def test_invalid_shard_index_is_rejected() -> None:
    env = os.environ.copy()
    env.update(
        {
            "STEALTHBENCH_SHARD_COUNT": "4",
            "STEALTHBENCH_SHARD_INDEX": "4",
        }
    )
    result = subprocess.run(
        ["./scripts/eval-full.sh", "--schedule-only"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must be in [0, SHARD_COUNT)" in result.stdout


def test_endpoint_schedule_is_offline() -> None:
    env = os.environ.copy()
    env.update(STEALTHBENCH_SHARD_COUNT="1", STEALTHBENCH_SHARD_INDEX="0")
    result = subprocess.run(
        ["./scripts/eval-endpoints.sh", "--schedule-only"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    schedule = result.stdout.splitlines()
    assert len(schedule) == 15 * 10 * 5
    assert all("endpoint-" in line for line in schedule)
    assert "AWS" not in result.stderr
