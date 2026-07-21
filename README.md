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

## OpenAPI contract

`openapi.yaml` is the pinned `artie-api-spec` release used at runtime. Update it only from a released, immutable `artie-api-spec` version.

## Setup
```bash
uv sync
```

## Run Server Locally
```bash
uvicorn server:app --reload
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
