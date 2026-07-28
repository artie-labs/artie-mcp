# artie-mcp

MCP server for managing your real-time data pipelines in Artie

[API Reference](https://www.artie.com/docs/api/overview)

## MCP Client Configuration

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://mcp.artie.com/mcp",
      "headers": {
        "Authorization": "Bearer <artie-api-key>"
      }
    }
  }
}
```

## Setup
```bash
uv sync
```

## Run Server Locally
```bash
uvicorn server:app --reload
```

## Verify
```bash
uv sync --locked --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q server.py tests
uv run python -m unittest discover -s tests -v
```

## Pinned OpenAPI contract

The image vendors `artie-api-spec` `v1.0.53` in `openapi/openapi.yaml`. `server.py`
verifies its SHA-256 before constructing FastMCP, so startup does not require GitHub.
Update the artifact, `_PINNED_SPEC_VERSION`, `_PINNED_SPEC_SHA256`, and
`tests/contract_snapshot.json` together in a reviewed PR.

## Smoke-test the production image

This check verifies that `tools/list` renders the annotations from the pinned `artie-api-spec` artifact.

```bash
docker build --tag artie-mcp:local .
docker run --detach --rm --name artie-mcp-local -p 127.0.0.1::8000 artie-mcp:local
port="$(docker port artie-mcp-local 8000/tcp | awk -F: '{print $NF}')"
trap 'docker logs artie-mcp-local; docker rm --force artie-mcp-local' EXIT
until curl --fail --silent "http://127.0.0.1:${port}/health" && curl --fail --silent "http://127.0.0.1:${port}/ready"; do sleep 1; done
uv run python tests/smoke_client.py --url "http://127.0.0.1:${port}/mcp" --openapi-path openapi/openapi.yaml
```

## Release

1. Update version in pyproject.toml

2. Update the lockfile.
   ```
   uv lock
   ```

3. Commit with message "Release vx.x.x"
   ```
   git add pyproject.toml uv.lock
   git commit --message "Release vx.x.x"
   ```
4. Run release script which builds and pushes a Docker image.
   ```bash
   ./release.sh
   ```
