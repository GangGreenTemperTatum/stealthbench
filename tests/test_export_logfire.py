"""Tests for scripts/export-logfire.py incremental export logic."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the export script as a module
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib

export_logfire = importlib.import_module("export-logfire")


def test_columns_to_rows_converts_columnar_to_row_format() -> None:
    data = {
        "columns": [
            {"name": "span_id", "datatype": "Utf8", "values": ["a1", "a2"]},
            {"name": "message", "datatype": "Utf8", "values": ["hello", "world"]},
        ]
    }
    rows = export_logfire.columns_to_rows(data)
    assert len(rows) == 2
    assert rows[0] == {"span_id": "a1", "message": "hello"}
    assert rows[1] == {"span_id": "a2", "message": "world"}


def test_columns_to_rows_handles_empty() -> None:
    assert export_logfire.columns_to_rows({}) == []
    assert export_logfire.columns_to_rows({"columns": []}) == []


def test_checkpoint_round_trip(tmp_path: Path) -> None:
    checkpoint = {
        "last_timestamp": "2026-07-25T12:00:00Z",
        "total_exported": 500,
        "updated_at": "2026-07-25T12:05:00Z",
    }
    export_logfire.save_checkpoint(tmp_path, checkpoint)
    loaded = export_logfire.load_checkpoint(tmp_path)
    assert loaded == checkpoint


def test_checkpoint_missing_returns_empty(tmp_path: Path) -> None:
    assert export_logfire.load_checkpoint(tmp_path) == {}


def test_incremental_deduplicates_by_span_id(tmp_path: Path) -> None:
    """Spans already in the file should not be written again on resume."""
    data_path = tmp_path / export_logfire.DATA_FILE

    # Pre-populate with one span
    existing = {"span_id": "existing-1", "start_timestamp": "2026-07-25T10:00:00Z", "message": "old"}
    data_path.write_text(json.dumps(existing) + "\n")

    # Mock query to return the existing span + a new one
    page_data = {
        "columns": [
            {"name": col, "datatype": "Utf8", "values": []}
            for col in export_logfire.COLUMNS
        ]
    }
    # Fill in values
    new_span = {c: "" for c in export_logfire.COLUMNS}
    new_span["span_id"] = "new-1"
    new_span["start_timestamp"] = "2026-07-25T11:00:00Z"
    new_span["message"] = "new"

    dup_span = {c: "" for c in export_logfire.COLUMNS}
    dup_span["span_id"] = "existing-1"
    dup_span["start_timestamp"] = "2026-07-25T10:00:00Z"
    dup_span["message"] = "old"

    for col_def in page_data["columns"]:
        col_name = col_def["name"]
        col_def["values"] = [dup_span.get(col_name, ""), new_span.get(col_name, "")]

    count_data = {"columns": [{"name": "count(*)", "datatype": "Int64", "values": [2]}]}

    call_count = 0

    def mock_query(token, sql, limit=1000):
        nonlocal call_count
        call_count += 1
        if "count(*)" in sql:
            return count_data
        return page_data

    with patch.object(export_logfire, "query", side_effect=mock_query):
        exported = export_logfire.export(
            "fake-token", tmp_path, since="2026-07-25T09:00:00Z"
        )

    # Read the file — should have 2 lines total (1 existing + 1 new), not 3
    lines = data_path.read_text().strip().split("\n")
    assert len(lines) == 2
    span_ids = [json.loads(line)["span_id"] for line in lines]
    assert "existing-1" in span_ids
    assert "new-1" in span_ids


def test_checkpoint_saved_during_export(tmp_path: Path) -> None:
    """Checkpoint should be written during export for crash recovery."""
    page_data = {
        "columns": [
            {"name": col, "datatype": "Utf8", "values": [f"val-{i}" if col != "start_timestamp" else f"2026-07-25T12:0{i}:00Z" for i in range(3)]}
            for col in export_logfire.COLUMNS
        ]
    }
    count_data = {"columns": [{"name": "count(*)", "datatype": "Int64", "values": [3]}]}

    def mock_query(token, sql, limit=1000):
        if "count(*)" in sql:
            return count_data
        return page_data

    with patch.object(export_logfire, "query", side_effect=mock_query):
        with patch("time.sleep"):  # skip rate limit delays
            export_logfire.export("fake-token", tmp_path)

    # Checkpoint should exist
    cp = export_logfire.load_checkpoint(tmp_path)
    assert "last_timestamp" in cp
    assert cp["total_exported"] > 0

    # Data file should exist with 3 lines
    data_path = tmp_path / export_logfire.DATA_FILE
    assert data_path.exists()
    lines = data_path.read_text().strip().split("\n")
    assert len(lines) == 3
