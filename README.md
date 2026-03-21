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
uv run server.py
```

## Release

Update version in pyproject.toml, commit with message "Release vx.x.x", then run release script which builds and pushes a Docker image.

```bash
./release.sh
```