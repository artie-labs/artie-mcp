#!/usr/bin/env python3
"""Verify the committed Artie API policy bundle and generated contract snapshot."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from policy_contract import (
    PolicyContractError,
    compile_policy,
    load_policy_bundle,
    snapshot_policy_contract,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_DIR = _REPOSITORY_ROOT / "contract"
_SNAPSHOT_PATH = _BUNDLE_DIR / "policy.contract.json"


def main() -> int:
    try:
        bundle = load_policy_bundle(_BUNDLE_DIR)
        policy_sha256 = hashlib.sha256(
            (_BUNDLE_DIR / "policy.openapi.yaml").read_bytes()
        ).hexdigest()
        actual = snapshot_policy_contract(
            bundle.release_tag,
            policy_sha256,
            compile_policy(bundle.spec),
        )
        expected = json.loads(_SNAPSHOT_PATH.read_text())
    except (OSError, json.JSONDecodeError, PolicyContractError) as error:
        print(f"policy contract verification failed: {error}", file=sys.stderr)
        return 1

    if actual != expected:
        print(
            "policy contract verification failed: snapshot is out of date",
            file=sys.stderr,
        )
        return 1

    print(
        "verified policy contract "
        f"{bundle.release_tag} ({len(actual['tools'])} exposed tools)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
