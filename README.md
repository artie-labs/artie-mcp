# artie-mcp

Artie's MCP service is for human-in-the-loop coding agents. Tool selection is focused on pipeline setup, connector metadata, and infrastructure operations — not every Dashboard or API action.

This remote MCP server is middleware to the [Artie API](https://www.artie.com/docs/api/overview). Artie Dashboard remains authoritative for identity, grants, environment binding, scopes, audit, and resource authorization.

## Getting Started

OAuth is the supported auth path. Point an OAuth-capable client (Claude Code, Cursor, Codex, and similar) at the server URL. The client discovers AuthKit from protected-resource metadata, signs you in, and on first tool use may ask you to link an Artie environment and scopes in the Dashboard. Artie API keys are not accepted.

Use the hosted service:

<https://mcp.artie.com>

Client setup, OAuth, and what the tools can do: [MCP documentation](https://www.artie.com/docs/api/mcp).

This repository is the source for that hosted integration. Running the process yourself is not a supported Artie product.

### Claude Code plugin

Install as a Claude Code plugin so the Artie subagent comes with the MCP connection:

```shell
claude plugin marketplace add artie-labs/artie-mcp
claude plugin install artie@artie-mcp
```

That registers `https://mcp.artie.com/mcp` and the Artie subagent.

### Cursor

Add the marketplace from this repository (`.cursor-plugin/marketplace.json`) and install the `artie` plugin, or add the server directly:

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://mcp.artie.com/mcp"
    }
  }
}
```

On first tool use, Artie may ask you to sign in, link an environment, and approve scopes. Do not add an API key for a new setup.

Codex and other OAuth clients: see the [MCP documentation](https://www.artie.com/docs/api/mcp).

## Help

| Topic | Route |
| --- | --- |
| Hosted product, OAuth, pipelines | [MCP docs](https://www.artie.com/docs/api/mcp), [Dashboard](https://app.artie.com) |
| Code or protocol bug in this repo | GitHub issue |

## License

MIT. See [LICENSE](LICENSE).
