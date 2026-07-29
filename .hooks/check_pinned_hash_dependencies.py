#!/usr/bin/env python3
import re
import sys
from pathlib import Path

PINNED_PATTERN = re.compile(r"uses:\s+([^@\s]+)@([a-f0-9]{40})")
UNPINNED_TAG_PATTERN = re.compile(r"uses:\s+([^@\s]+)@(v\d+(?:\.\d+)*(?:-[a-zA-Z0-9]+(?:\.\d+)*)?)")
ALL_USES_PATTERN = re.compile(r"uses:\s+([^@\s]+)@([^\s\n]+)")


def matches_with_lines(content: str, pattern: re.Pattern[str]) -> list[tuple[str, int]]:
    matches: list[tuple[str, int]] = []
    for line_number, line in enumerate(content.splitlines(), 1):
        matches.extend((match.group(0), line_number) for match in pattern.finditer(line))
    return matches


def check_file(file_path: str) -> bool:
    path = Path(file_path)
    try:
        content = path.read_text()
    except OSError as exc:
        print(f"Error reading {file_path}: {exc}", file=sys.stderr)
        return False

    pinned = matches_with_lines(content, PINNED_PATTERN)
    unpinned_tags = matches_with_lines(content, UNPINNED_TAG_PATTERN)
    all_uses = matches_with_lines(content, ALL_USES_PATTERN)
    unpinned_other = [
        (match, line)
        for match, line in all_uses
        if match not in {item for item, _ in pinned}
        and match not in {item for item, _ in unpinned_tags}
    ]

    if pinned:
        print(f"\nPinned actions in {file_path}:")
        for match, line in pinned:
            print(f"  {match} ({file_path}:{line})")

    if unpinned_tags or unpinned_other:
        print(f"\nUnpinned GitHub Actions in {file_path}:")
        for match, line in unpinned_tags + unpinned_other:
            print(f"  {match} ({file_path}:{line})")
        return False

    return True


def main() -> None:
    files = sys.argv[1:]
    if not files:
        print("Usage: check_pinned_hash_dependencies.py <workflow...>", file=sys.stderr)
        sys.exit(1)

    if not all(check_file(file_path) for file_path in files):
        sys.exit(1)


if __name__ == "__main__":
    main()
