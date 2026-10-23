"""Deterministic policy evaluation for endpoint telemetry."""

from __future__ import annotations

from pathlib import Path

import yaml


def _matches(event: dict, conditions: dict) -> bool:
    return all(event.get(key) == value for key, value in conditions.items())


def evaluate_policy(events: list[dict], policy_path: Path) -> list[dict]:
    if not policy_path.exists():
        return []
    policy = yaml.safe_load(policy_path.read_text()) or {}
    findings: list[dict] = []
    for rule in policy.get("rules", []):
        matches = [event for event in events if _matches(event, rule.get("when", {}))]
        min_matches = int(rule.get("min_matches", 1))
        if len(matches) < min_matches:
            continue
        findings.append(
            {
                "rule_id": rule["id"],
                "failure": bool(rule.get("failure", False)),
                "severity": rule.get("severity", "info"),
                "reason": rule.get("reason", "endpoint policy matched"),
                "match_count": len(matches),
            }
        )
    return findings
