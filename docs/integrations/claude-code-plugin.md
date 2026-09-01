# Claude Code and Cursor plugin

How the `artie` plugin is structured and how to change it.

## Overview

One plugin is published: `artie`. It registers an `artie-mcp` subagent that Claude Code (and Cursor) can delegate to for Artie pipelines, connectors, schema changes, lag, and warehouse replication.

The subagent connects to the hosted MCP server. Tools are whatever `https://mcp.artie.com/mcp` exposes from the policy contract — there is no `allowedTools` list and no generate-definitions script.

Install (Claude Code):

```shell
claude plugin marketplace add artie-labs/artie-mcp
claude plugin install artie@artie-mcp
```

Cursor: add the marketplace from `.cursor-plugin/marketplace.json` and install `artie`, or point the client at `https://mcp.artie.com/mcp`.

## Directory layout

```
.claude-plugin/marketplace.json   # Claude marketplace — one plugin, category database
.cursor-plugin/marketplace.json   # Cursor marketplace — same plugin

plugins/artie/
├── .claude-plugin/plugin.json    # Claude plugin metadata
├── .cursor-plugin/plugin.json    # Cursor plugin metadata
├── .mcp.json                     # Claude MCP entry: { "artie": { "type": "http", "url": "..." } }
├── mcp.json                      # Cursor MCP entry: { "mcpServers": { "artie": { ... } } }
├── agents/artie-mcp.md           # subagent prompt + YAML frontmatter
└── skills/
    ├── pipeline-setup/
    ├── monitoring/
    ├── connector-compatibility/
    └── migration/
```

Both MCP JSON files must keep `url` at `https://mcp.artie.com/mcp`. The server key must stay `artie` so it matches `mcpServers` in the agent frontmatter. Do not point the published plugin at localhost.

## Agent frontmatter

`plugins/artie/agents/artie-mcp.md` starts with:

```yaml
---
name: artie-mcp
description: Artie real-time CDC pipelines. Use when the user asks about pipelines, connectors, sources, destinations, schema changes, pipeline health, lag, alerts, backfills, SSH tunnels, PrivateLink, or replication into a warehouse. Do not use for warehouse SQL, Fivetran SaaS extractors, or claiming that a row landed in the destination.
mcpServers:
  - artie
---
```

- **`name`** — subagent name used for delegation.
- **`description`** — when Claude should route here. Keep the trigger phrases (pipelines, connectors, lag, schema changes, and so on).
- **`mcpServers`** — must match the key in `.mcp.json` / `mcp.json` (`artie`).

The body below the frontmatter is the system prompt: workflow (intent, UUID resolution, what is not a tool), **Key Tool Distinctions** (`list` vs FullPipeline, create-from-source vs fan-out, detect vs apply schema changes), and output rules. Skills still own the long sequences (setup, monitoring, compatibility, migration).

## Skills

Each skill is `plugins/artie/skills/<name>/SKILL.md` with its own `name` / `description` frontmatter for routing.

| Skill | When |
| --- | --- |
| `pipeline-setup` | First pipeline from a **saved** connector through `pipeline_start` |
| `monitoring` | Health from `pipeline_list`; schema-change detect/trigger; Dashboard for lag, error logs, monitors |
| `connector-compatibility` | Type / capture method / network support from published docs |
| `migration` | Fivetran lift-and-shift plan |

## How to modify

1. **Prompt** — edit the body of `plugins/artie/agents/artie-mcp.md` (below the `---`).
2. **Routing** — edit that file’s `description`.
3. **A skill** — edit `plugins/artie/skills/<name>/SKILL.md`. Add a folder only if you also list it in the agent workflow and this page.
4. **MCP URL** — change both `.mcp.json` and `mcp.json` together.
5. **Marketplace listing** — `.claude-plugin/marketplace.json` and `.cursor-plugin/marketplace.json` (`source`, `category`).
