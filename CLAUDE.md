# AGENTS.md

Artie MCP is a Model Context Protocol server that exposes a reviewed set of Artie pipeline and infrastructure operations to coding agents. The supported endpoint is `https://mcp.artie.com/mcp`.

<!-- intuition:olympus:start -->
## The component map (Olympus)

This repo is indexed into a component map derived from the compiler, not from guesses.
Prefer it over grepping when you need to know where something lives or what depends on what.

- `olympus_map` — the components and the links between them. Start here to orient.
  Pass `focus` with a block id or name plus `depth` to see one neighbourhood.
- `olympus_entries` — for one component, the symbols other components call, with
  `path:line`. This is the "what crosses this boundary" question.
- `olympus_propose` — draw a component or a link that SHOULD exist but does not yet.
  It records an intention; it never asserts the code is there.
- `olympus_highlight` — dim the user's map to the components you are talking about.
  Use it whenever an answer names specific components; it is a gesture at their
  screen, cleared by their next click.

Blocks are `solid` when the compiler found them and `dashed` when someone only asserted
them. Anything you propose stays dashed until real code exists and the next index finds it,
so build the code as well as the proposal.

The map is a snapshot written by the IDE. If it looks stale, say so rather than working
around it.
<!-- intuition:olympus:end -->

## Constraints

- **Hosted service**: `mcp.artie.com` is the supported product. Do not document self-hosting as supported.
- **No credential tools**: do not expose `connector_create` or unsaved-connector credential paths.
- **Policy pin**: tools come from `contract/policy.lock.json`, not a hand-written allowlist in `server.py`.
- **Quality gate**: `uv lock --check && uv run ruff format --check . && uv run ruff check . && uv run python -m unittest discover -s tests -v` must pass before committing.

## Repository structure

```
artie-mcp/
├── server.py              # FastMCP process (auth, OpenAPI tools, shaping)
├── policy_contract.py     # compile the pinned spec into the tool contract
├── policy_adapter.py      # request/response shaping
├── contract/              # lock + committed contract snapshot
├── plugins/artie/         # Claude/Cursor plugin (MCP URL, skills, subagent)
├── docs/                  # contributor documentation
└── tests/                 # unit tests + container smoke client
```

## Documentation map

- [docs/README.md](docs/README.md) — full index
- [docs/architecture/overview.md](docs/architecture/overview.md) — system design
- [docs/contributing/policy-contract.md](docs/contributing/policy-contract.md) — how tools are exposed
- [docs/integrations/claude-code-plugin.md](docs/integrations/claude-code-plugin.md) — plugin layout

Customer setup: [https://www.artie.com/docs/api/mcp](https://www.artie.com/docs/api/mcp)

## Commands

```bash
uv sync --locked --all-groups
uv run python -m scripts.download_policy_bundle
uv run python -m unittest discover -s tests -v
```

## Workflow

1. Match neighboring files before inventing a new pattern.
2. Tool inventory changes go through the API spec + policy pin, not new Python tool functions.
3. Update `docs/` when behavior that contributors rely on changes.
