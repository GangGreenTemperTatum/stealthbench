#!/usr/bin/env python3
"""Incremental Logfire OTEL span export to local JSONL.

Exports spans from Logfire's read API into a single append-only JSONL file.
Tracks the last exported timestamp in a checkpoint file so subsequent runs
only fetch new spans. Handles rate limits (429/502/503) with exponential
backoff and can resume mid-export after crashes.

Uses timestamp-cursor pagination (min_timestamp) instead of OFFSET,
and 10,000-row pages (the API maximum) to minimise request count.

Requires LOGFIRE_READ_TOKEN in .env or environment.

Usage:
    # First export — pulls everything
    python3 scripts/export-logfire.py --output ~/git/stealthbench-results/otel/

    # Subsequent runs — only pulls new spans since last checkpoint
    python3 scripts/export-logfire.py --output ~/git/stealthbench-results/otel/

    # Force full re-export (ignores checkpoint)
    python3 scripts/export-logfire.py --output ~/git/stealthbench-results/otel/ --full

    # Dry run — show what would be exported
    python3 scripts/export-logfire.py --output ~/git/stealthbench-results/otel/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOGFIRE_API = "https://logfire-api.pydantic.dev/v1"
PAGE_SIZE = 500  # attributes column is ~28KB/row avg; 500 rows stays under 100MB response limit
MAX_RETRIES = 8
COLUMNS = [
    "span_id",
    "trace_id",
    "parent_span_id",
    "span_name",
    "message",
    "start_timestamp",
    "end_timestamp",
    "duration",
    "level",
    "otel_status_code",
    "service_name",
    "attributes",
]
CHECKPOINT_FILE = "logfire-export-checkpoint.json"
DATA_FILE = "stealthbench-logfire.jsonl"


def load_token() -> str:
    token = os.environ.get("LOGFIRE_READ_TOKEN", "")
    if token:
        return token
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("LOGFIRE_READ_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def query(token: str, sql: str, limit: int = PAGE_SIZE) -> dict:
    encoded = urllib.parse.quote(sql)
    url = f"{LOGFIRE_API}/query?sql={encoded}&limit={limit}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503) and attempt < MAX_RETRIES:
                delay = min(2**attempt, 60)
                print(
                    f"\n  [{exc.code}] waiting {delay}s (attempt {attempt}/{MAX_RETRIES})...",
                    end="",
                    flush=True,
                )
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < MAX_RETRIES:
                delay = min(2**attempt, 60)
                print(
                    f"\n  [network] waiting {delay}s (attempt {attempt}/{MAX_RETRIES}): {exc}...",
                    end="",
                    flush=True,
                )
                time.sleep(delay)
                continue
            raise
    return {}


def columns_to_rows(data: dict) -> list[dict]:
    columns = data.get("columns", [])
    if not columns:
        return []
    names = [c["name"] for c in columns]
    value_lists = [c["values"] for c in columns]
    row_count = len(value_lists[0]) if value_lists else 0
    return [{names[i]: value_lists[i][j] for i in range(len(names))} for j in range(row_count)]


def load_checkpoint(output_dir: Path) -> dict:
    cp_path = output_dir / CHECKPOINT_FILE
    if cp_path.exists():
        return json.loads(cp_path.read_text())
    return {}


def save_checkpoint(output_dir: Path, checkpoint: dict) -> None:
    cp_path = output_dir / CHECKPOINT_FILE
    cp_path.write_text(json.dumps(checkpoint, indent=2, default=str))


def get_span_count(token: str, since: str | None = None) -> int:
    where = f" WHERE start_timestamp > '{since}'" if since else ""
    data = query(token, f"SELECT count(*) FROM records{where}")
    return data["columns"][0]["values"][0]


def export(
    token: str,
    output_dir: Path,
    since: str | None = None,
    dry_run: bool = False,
) -> int:
    col_list = ", ".join(COLUMNS)

    total = get_span_count(token, since)
    mode = "incremental" if since else "full"
    print(f"Mode: {mode}")
    if since:
        print(f"Since: {since}")
    print(f"Spans to export: {total:,}")
    print(f"Pages (~{PAGE_SIZE:,}/page): ~{(total // PAGE_SIZE) + 1}")

    if total == 0:
        print("Nothing new to export.")
        return 0

    if dry_run:
        print("Dry run — no data written.")
        return 0

    data_path = output_dir / DATA_FILE
    exported = 0
    page = 0
    # Cursor: advance min_timestamp each page to avoid OFFSET
    cursor_ts = since
    span_ids_seen: set[str] = set()

    # If resuming into existing file, load seen span_ids for dedup
    existing_lines = 0
    if data_path.exists():
        with open(data_path) as f:
            for line in f:
                existing_lines += 1
                try:
                    row = json.loads(line)
                    span_ids_seen.add(row.get("span_id", ""))
                except json.JSONDecodeError:
                    pass
        print(f"Existing spans in file: {existing_lines:,}")

    with open(data_path, "a") as f:
        current_page_size = PAGE_SIZE
        while True:
            requested_size = current_page_size
            where = f" WHERE start_timestamp > '{cursor_ts}'" if cursor_ts else ""
            sql = (
                f"SELECT {col_list} FROM records{where} "
                f"ORDER BY start_timestamp ASC "
                f"LIMIT {requested_size}"
            )

            try:
                data = query(token, sql)
            except urllib.error.HTTPError as exc:
                if exc.code == 400 and current_page_size > 50:
                    # Response too large — halve page size and retry
                    current_page_size = max(50, current_page_size // 2)
                    print(
                        f"\n  [400] response too large, reducing to {current_page_size}/page...",
                        end="",
                        flush=True,
                    )
                    continue
                print(f"\n\nAPI error after {exported:,} spans: {exc}")
                print("Run again to resume — checkpoint saved.")
                break
            except Exception as exc:
                print(f"\n\nAPI error after {exported:,} spans: {exc}")
                print("Run again to resume — checkpoint saved.")
                break

            rows = columns_to_rows(data)
            if not rows:
                break

            new_in_page = 0
            for row in rows:
                sid = row.get("span_id", "")
                if sid and sid in span_ids_seen:
                    continue
                span_ids_seen.add(sid)
                f.write(json.dumps(row, default=str) + "\n")
                new_in_page += 1

            # Advance cursor to last timestamp in this page
            last_ts = rows[-1].get("start_timestamp")
            if last_ts:
                cursor_ts = last_ts

            f.flush()
            exported += len(rows)
            page += 1

            pct = min(100, 100 * exported / total) if total else 0
            print(
                f"\r  [{exported:,}/{total:,}] {pct:.0f}% ({page} pages, +{new_in_page} new)",
                end="",
                flush=True,
            )

            # Save checkpoint every page for crash recovery
            if cursor_ts:
                save_checkpoint(
                    output_dir,
                    {
                        "last_timestamp": cursor_ts,
                        "total_exported": existing_lines + exported,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

            # If we got fewer rows than requested, we've reached the end
            if len(rows) < requested_size:
                break

            # Gradually restore page size after successful smaller pages
            if current_page_size < PAGE_SIZE:
                current_page_size = min(current_page_size * 2, PAGE_SIZE)

            # Rate limit courtesy — 8s between pages
            time.sleep(8.0)

    # Final checkpoint
    if cursor_ts:
        save_checkpoint(
            output_dir,
            {
                "last_timestamp": cursor_ts,
                "total_exported": existing_lines + exported,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    file_size = data_path.stat().st_size
    size_str = (
        f"{file_size / 1_000_000:.1f} MB"
        if file_size > 1_000_000
        else f"{file_size / 1_000:.1f} KB"
    )
    print(f"\n\nExported {exported:,} spans ({page} pages)")
    print(f"File: {data_path} ({size_str})")
    print(f"Checkpoint: {output_dir / CHECKPOINT_FILE}")
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        required=True,
        help="output directory (checkpoint + data file stored here)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="ignore checkpoint, export all spans from scratch",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be exported without writing",
    )
    args = parser.parse_args()

    token = load_token()
    if not token:
        print(
            "ERROR: LOGFIRE_READ_TOKEN not found in .env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Verify connectivity
    try:
        query(token, "SELECT 1", limit=1)
    except Exception as exc:
        print(f"ERROR: Cannot connect to Logfire API: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load checkpoint for incremental export
    since = None
    if not args.full:
        checkpoint = load_checkpoint(output_dir)
        since = checkpoint.get("last_timestamp")
        if since:
            print(f"Resuming from checkpoint: {since}")
            print(f"Previous export: {checkpoint.get('total_exported', '?')} spans")
        else:
            print("No checkpoint found — full export.")
    else:
        print("Full export requested (ignoring checkpoint).")

    print()
    exported = export(token, output_dir, since=since, dry_run=args.dry_run)

    if exported == 0 and not args.dry_run:
        print("\nAll caught up — no new spans since last export.")


if __name__ == "__main__":
    main()
