# artie-mcp

MCP server for managing your real-time data pipelines in Artie

[API Reference](https://www.artie.com/docs/api/overview)

## MCP Client Configuration

Point an OAuth-capable client (Claude Code, Cursor, Codex, and similar) at the server URL. The client discovers AuthKit from protected-resource metadata, signs you in, and on first tool use may ask you to link an Artie environment and scopes in the Dashboard.

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://mcp.artie.com/mcp"
    }
  }
}
```

## Skills

The pipeline-setup skill lives at `plugins/artie/skills/pipeline-setup/`.

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

## Smoke-test the production image

This check verifies that `tools/list` renders the OpenAPI `x-artie-mcp` annotation shapes without relying on a route or tool-name allowlist.

```bash
docker build --tag artie-mcp:local .
docker run --detach --rm --name artie-mcp-local -p 127.0.0.1::8000 artie-mcp:local
port="$(docker port artie-mcp-local 8000/tcp | awk -F: '{print $NF}')"
trap 'docker logs artie-mcp-local; docker rm --force artie-mcp-local' EXIT
until curl --fail --silent "http://127.0.0.1:${port}/health" && curl --fail --silent "http://127.0.0.1:${port}/ready"; do sleep 1; done
uv run python tests/smoke_client.py --url "http://127.0.0.1:${port}/mcp" --openapi-url "https://raw.githubusercontent.com/artie-labs/artie-api-spec/refs/heads/master/openapi.yaml"
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
