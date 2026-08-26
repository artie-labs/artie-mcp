#!/usr/bin/env python3
"""Generate the checked-in static benchmark manifest from the policy snapshot."""

from __future__ import annotations

import json
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPOSITORY_ROOT / "contract" / "policy.contract.json"
_MANIFEST_PATH = _REPOSITORY_ROOT / "benchmark" / "manifest.json"


def _classification(tool: dict) -> str:
    if tool["annotations"]["readOnlyHint"]:
        return "execution_scenario_required"
    return "blocked_by_fixture"


def main() -> int:
    contract = json.loads(_CONTRACT_PATH.read_text())
    scenarios = []
    for tool in contract["tools"]:
        scenarios.append(
            {
                "classification": _classification(tool),
                "cleanupAction": None,
                "cleanupRead": None,
                "connectorType": None,
                "directArgumentsRef": None,
                "expectedFailure": None,
                "expectedResult": None,
                "fixtureAlias": None,
                "job": None,
                "method": tool["method"].upper(),
                "path": tool["path"],
                "postconditionRead": None,
                "precondition": None,
                "requiredScope": tool["requiredScopes"],
                "scenarioId": f"tool-{tool['name']}",
                "tool": tool["name"],
            }
        )
    manifest = {
        "formatVersion": 1,
        "policyRelease": contract["releaseTag"],
        "policySHA256": contract["policySHA256"],
        "scenarios": scenarios,
    }
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
