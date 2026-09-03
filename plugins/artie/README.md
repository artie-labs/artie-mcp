# Artie for Cursor

Official Artie plugin for Cursor. Set up and manage real-time CDC pipelines from your IDE — connect sources to warehouses, inspect schema changes, and monitor replication through Artie's hosted MCP server.

## What's included

| Component | Description |
| --- | --- |
| **MCP server** | Remote server at `https://mcp.artie.com/mcp` — pipeline, connector, and infrastructure operations |
| **Skill: `pipeline-setup`** | Step-by-step guided flow to create a CDC pipeline from source to destination and optionally start it |
| **Agent: `artie-mcp`** | Artie expert for pipelines, connectors, lag, schema changes, backfills, SSH tunnels, and PrivateLink |

The MCP server exposes a reviewed subset of Artie operations. It does not cover every Dashboard action. See [MCP documentation](https://www.artie.com/docs/api/mcp) for the full tool list and limits.

## Install

**From the Cursor Marketplace:** install the **artie** plugin from [artie-labs/artie-mcp](https://github.com/artie-labs/artie-mcp).

**Manual MCP setup:** add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://mcp.artie.com/mcp"
    }
  }
}
```

## First use

On first tool call, Cursor opens OAuth so you can sign in to Artie, link an environment, and approve scopes.

**Do not add an API key or bearer token for a new setup.** OAuth is the supported path.

If auth fails or a token expires, remove the saved Artie connection in Cursor and reconnect.

## Example prompts

- "Set up a CDC pipeline from my Postgres source to Snowflake"
- "List my Artie pipelines and their status"
- "What's the replication lag on pipeline X?"
- "Show schema changes detected on my production pipeline"
- "Pause the orders pipeline"

For end-to-end pipeline creation, the agent uses the **pipeline-setup** skill automatically when you ask for a new pipeline, sync, or replication setup.

## Authentication

OAuth is required for new integrations. Legacy API keys still work during the migration window but are not recommended for new setups. See the [repository README](../../README.md#legacy-api-keys) if you need the key-based config.

## Destructive actions

Some MCP tools delete resources or rotate keys. Review the exact action and affected resource before approving a tool call. Do not enable automatic approval for destructive tools.

## Docs and support

| Topic | Link |
| --- | --- |
| MCP setup, OAuth, and tool reference | [Artie MCP docs](https://www.artie.com/docs/api/mcp) |
| Dashboard (connectors, environments) | [app.artie.com](https://app.artie.com) |
| Bugs in this plugin or MCP server | [GitHub Issues](https://github.com/artie-labs/artie-mcp/issues) |

## License

MIT. See [LICENSE](../../LICENSE).
