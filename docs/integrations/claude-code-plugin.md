# Claude Code and Cursor plugin

The public plugin lives in `plugins/artie`, the same layout [sentry-mcp](https://github.com/getsentry/sentry-mcp) uses for `plugins/sentry-mcp`.

```
plugins/artie/
├── .claude-plugin/plugin.json   # Claude plugin manifest
├── .cursor-plugin/plugin.json   # Cursor plugin manifest
├── .mcp.json                    # Claude MCP server entry
├── mcp.json                     # Cursor MCP server entry
├── agents/artie-mcp.md          # subagent prompt
└── skills/
    ├── pipeline-setup/
    ├── connector-compatibility/
    └── migration/
```

Repo-root marketplaces point at that folder:

- `.claude-plugin/marketplace.json`
- `.cursor-plugin/marketplace.json`

Install (Claude Code):

```shell
claude plugin marketplace add artie-labs/artie-mcp
claude plugin install artie@artie-mcp
```

Both MCP JSON files must keep `url` at `https://mcp.artie.com/mcp`. Do not point the published plugin at localhost.

Skills describe golden-path tool sequences. They must not tell the agent to call `connector_create` or `unsaved_*`.
