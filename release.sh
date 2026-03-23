#!/usr/bin/env bash
set -euo pipefail

VERSION=$(python3 -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(data['project']['version'])
")

IMAGE="artielabs/artie-mcp"

echo "Building ${IMAGE}:${VERSION}"
docker build --platform linux/amd64,linux/arm64 -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" -t "${IMAGE}:prod" --push .
