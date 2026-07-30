#!/usr/bin/env python3
"""Prepare the reviewed policy files for a released Artie API specification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from policy_contract import (
    PolicyContractError,
    compile_policy,
    snapshot_policy_contract,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BUNDLE_DIR = _REPOSITORY_ROOT / "contract"
_RELEASE_URL_TEMPLATE = (
    "https://github.com/artie-labs/artie-api-spec/releases/download/{tag}/openapi.yaml"
)
_RELEASE_TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class PrepareResult:
    changed: bool
    release_tag: str
    policy_sha256: str


def prepare_policy_update(release_tag: str, bundle_dir: Path) -> PrepareResult:
    """Verify a released policy artifact and update the reviewed local metadata."""
    _validate_release_tag(release_tag)
    policy_bytes = _download_policy(release_tag)
    policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    spec = _parse_policy(policy_bytes, release_tag)
    contract = compile_policy(spec)
    lock = _policy_lock(release_tag, policy_sha256)
    snapshot = snapshot_policy_contract(release_tag, policy_sha256, contract)

    lock_path = bundle_dir / "policy.lock.json"
    snapshot_path = bundle_dir / "policy.contract.json"
    lock_text = _pretty_json(lock)
    snapshot_text = _pretty_json(snapshot)
    changed = (
        _read_text(lock_path) != lock_text or _read_text(snapshot_path) != snapshot_text
    )
    if changed:
        lock_path.write_text(lock_text)
        snapshot_path.write_text(snapshot_text)

    return PrepareResult(changed, release_tag, policy_sha256)


def _validate_release_tag(release_tag: str) -> None:
    if not _RELEASE_TAG_PATTERN.fullmatch(release_tag):
        raise PolicyContractError(
            "release tag must use the v<major>.<minor>.<patch> format"
        )


def _download_policy(release_tag: str) -> bytes:
    url = _RELEASE_URL_TEMPLATE.format(tag=release_tag)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except OSError as error:
        raise PolicyContractError(
            f"failed to download policy artifact for {release_tag}: {error}"
        ) from error


def _parse_policy(policy_bytes: bytes, release_tag: str) -> dict[str, Any]:
    try:
        spec = yaml.safe_load(policy_bytes)
    except yaml.YAMLError as error:
        raise PolicyContractError(
            f"policy artifact is malformed YAML: {error}"
        ) from error
    if not isinstance(spec, dict):
        raise PolicyContractError("policy artifact must be an object")
    info = spec.get("info")
    if not isinstance(info, dict) or info.get("version") != release_tag:
        raise PolicyContractError(
            "policy artifact info version must match the release tag"
        )
    return spec


def _policy_lock(release_tag: str, policy_sha256: str) -> dict[str, Any]:
    return {
        "formatVersion": 1,
        "policySHA256": policy_sha256,
        "release": {
            "tag": release_tag,
            "asset": "openapi.yaml",
            "url": _RELEASE_URL_TEMPLATE.format(tag=release_tag),
        },
    }


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--bundle-dir", type=Path, default=_DEFAULT_BUNDLE_DIR)
    arguments = parser.parse_args()

    try:
        result = prepare_policy_update(arguments.release_tag, arguments.bundle_dir)
    except (OSError, PolicyContractError) as error:
        print(f"policy update preparation failed: {error}", file=sys.stderr)
        return 1

    outcome = "updated" if result.changed else "already current"
    print(f"policy update {outcome}: {result.release_tag} ({result.policy_sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
