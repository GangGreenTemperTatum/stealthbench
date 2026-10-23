#!/usr/bin/env python3
"""Fail fast when an OpenRouter model slug is absent from the current catalog."""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    requested = {
        model.removeprefix("openrouter/")
        for model in sys.argv[1:]
        if model.startswith("openrouter/")
    }
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as response:
        catalog = json.load(response)
    available = {item["id"] for item in catalog.get("data", [])}
    missing = sorted(requested - available)
    if missing:
        print("OpenRouter model IDs not found:", *missing, sep="\n  ", file=sys.stderr)
        return 1
    print(f"OpenRouter catalog verified: {len(requested)} model IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
