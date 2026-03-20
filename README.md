# artie-mcp

MCP server for managing your real-time data pipelines in Artie

[API Reference](https://www.artie.com/docs/api/overview)

## Setup
```bash
uv sync
```

## Run Server Locally
```bash
uv run server.py
```

## MCP Client Configuration

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://your-deployed-host.com/mcp",
      "headers": {
        "Authorization": "Bearer <artie-api-key>"
      }
    }
  }
}
```
