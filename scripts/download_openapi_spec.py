import hashlib
import sys
import urllib.request
from pathlib import Path

OPENAPI_SPEC_URL = "https://github.com/artie-labs/artie-api-spec/releases/download/v1.0.53/openapi.yaml"
OPENAPI_SPEC_SHA256 = "fbd57a5d2b0a741022df2f577c7fd98647989cb93cbc292a182498a7fdc14495"


def download_openapi_spec(destination: Path) -> None:
    try:
        spec = urllib.request.urlopen(OPENAPI_SPEC_URL, timeout=30).read()
    except OSError as error:
        raise RuntimeError(
            f"failed to download OpenAPI spec from {OPENAPI_SPEC_URL}"
        ) from error

    actual_checksum = hashlib.sha256(spec).hexdigest()
    if actual_checksum != OPENAPI_SPEC_SHA256:
        raise ValueError(
            f"OpenAPI spec checksum mismatch: expected {OPENAPI_SPEC_SHA256}, got {actual_checksum}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(spec)


if __name__ == "__main__":
    download_openapi_spec(Path(sys.argv[1]))
