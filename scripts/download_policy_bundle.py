from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_DIR = _REPOSITORY_ROOT / "contract"
_POLICY_PATH = _BUNDLE_DIR / "policy.openapi.yaml"


def main() -> int:
    try:
        lock = json.loads((_BUNDLE_DIR / "policy.lock.json").read_text())
        release = lock["release"]
        with urllib.request.urlopen(release["url"], timeout=30) as response:
            policy_bytes = response.read()
        if hashlib.sha256(policy_bytes).hexdigest() != lock["policySHA256"]:
            raise ValueError("downloaded policy checksum does not match policy lock")
        _POLICY_PATH.write_bytes(policy_bytes)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"policy bundle download failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
