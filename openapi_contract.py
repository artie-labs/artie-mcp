from pathlib import Path

ARTIE_API_SPEC_VERSION = "v1.0.53"
ARTIE_API_SPEC_SHA256 = (
    "fbd57a5d2b0a741022df2f577c7fd98647989cb93cbc292a182498a7fdc14495"
)
ARTIE_API_SPEC_URL = (
    "https://github.com/artie-labs/artie-api-spec/releases/download/"
    f"{ARTIE_API_SPEC_VERSION}/openapi.yaml"
)
PINNED_SPEC_PATH = Path(__file__).parent / "openapi" / "openapi.yaml"
