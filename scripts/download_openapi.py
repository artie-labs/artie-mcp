import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openapi_contract import ARTIE_API_SPEC_SHA256, ARTIE_API_SPEC_URL, PINNED_SPEC_PATH


def main() -> None:
    try:
        with urllib.request.urlopen(ARTIE_API_SPEC_URL, timeout=30) as response:
            spec_bytes = response.read()
    except OSError as exc:
        raise RuntimeError(
            f"failed to download pinned OpenAPI spec: {ARTIE_API_SPEC_URL}"
        ) from exc

    actual_sha256 = hashlib.sha256(spec_bytes).hexdigest()
    if actual_sha256 != ARTIE_API_SPEC_SHA256:
        raise RuntimeError(
            f"pinned OpenAPI spec checksum mismatch: expected {ARTIE_API_SPEC_SHA256}, got {actual_sha256}"
        )

    PINNED_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    PINNED_SPEC_PATH.write_bytes(spec_bytes)


if __name__ == "__main__":
    main()
