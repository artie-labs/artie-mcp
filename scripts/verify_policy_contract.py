#!/usr/bin/env python3
"""Verify the committed Artie API policy bundle and generated contract snapshot."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import yaml

from policy_contract import (
    PolicyContractError,
    compile_policy,
    validate_policy_snapshot,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_DIR = _REPOSITORY_ROOT / "contract"
_SNAPSHOT_PATH = _BUNDLE_DIR / "policy.contract.json"


def main() -> int:
    try:
        lock = json.loads((_BUNDLE_DIR / "policy.lock.json").read_text())
        release = lock["release"]
        with urllib.request.urlopen(release["url"], timeout=30) as response:
            policy_bytes = response.read()
        policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
        if policy_sha256 != lock["policySHA256"]:
            raise PolicyContractError(
                "downloaded policy artifact checksum does not match policy lock"
            )
        spec = yaml.safe_load(policy_bytes)
        if (
            not isinstance(spec, dict)
            or spec.get("info", {}).get("version") != release["tag"]
        ):
            raise PolicyContractError(
                "downloaded policy artifact version does not match policy lock"
            )
        actual_contract = compile_policy(spec)
        expected = json.loads(_SNAPSHOT_PATH.read_text())
        validate_policy_snapshot(
            release["tag"], policy_sha256, actual_contract, expected
        )
    except (OSError, json.JSONDecodeError, PolicyContractError) as error:
        print(f"policy contract verification failed: {error}", file=sys.stderr)
        return 1

    print(
        "verified policy contract "
        f"{release['tag']} ({len(actual_contract.tools)} exposed tools)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
