#!/usr/bin/env python3
"""Prepare the reviewed policy files for a released Artie API specification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
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
        _write_bundle(lock_path, lock_text, snapshot_path, snapshot_text)

    return PrepareResult(changed, release_tag, policy_sha256)


def _write_bundle(
    lock_path: Path,
    lock_text: str,
    snapshot_path: Path,
    snapshot_text: str,
) -> None:
    lock_update = _write_temporary_file(lock_path.parent, lock_text)
    snapshot_update = _write_temporary_file(snapshot_path.parent, snapshot_text)
    lock_backup = _copy_to_temporary_file(lock_path)
    snapshot_backup = _copy_to_temporary_file(snapshot_path)
    published_paths: list[Path] = []

    try:
        _replace(lock_update, lock_path)
        published_paths.append(lock_path)
        _replace(snapshot_update, snapshot_path)
        published_paths.append(snapshot_path)
        _fsync_directory(lock_path.parent)
    except OSError as error:
        try:
            if snapshot_path in published_paths:
                _restore(snapshot_path, snapshot_backup)
            if lock_path in published_paths:
                _restore(lock_path, lock_backup)
            _fsync_directory(lock_path.parent)
        except OSError as rollback_error:
            raise PolicyContractError(
                "failed to restore policy files after an update error"
            ) from rollback_error
        raise error
    finally:
        for path in (lock_update, snapshot_update, lock_backup, snapshot_backup):
            if path is not None:
                path.unlink(missing_ok=True)


def _write_temporary_file(directory: Path, contents: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", dir=directory, prefix=".policy-update-", delete=False
    ) as file:
        file.write(contents)
        file.flush()
        os.fsync(file.fileno())
        return Path(file.name)


def _copy_to_temporary_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    return _write_temporary_file(path.parent, path.read_text())


def _restore(path: Path, backup: Path | None) -> None:
    if backup is None:
        path.unlink(missing_ok=True)
        return
    _replace(backup, path)


def _replace(source: Path, destination: Path) -> None:
    source.replace(destination)


def _fsync_directory(directory: Path) -> None:
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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
