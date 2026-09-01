# AGENTS.md

Artie MCP is a Model Context Protocol server that exposes a reviewed set of Artie pipeline and infrastructure operations to coding agents. The supported endpoint is `https://mcp.artie.com/mcp`.

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

Fetch the policy bundle when `contract/policy.openapi.yaml` is missing; it is not committed.

Smoke-test a local image against the **committed** contract, not a mutable upstream OpenAPI URL:

```bash
docker build --tag artie-mcp:local .
docker run --detach --rm --name artie-mcp-local -p 127.0.0.1::8000 artie-mcp:local
port="$(docker port artie-mcp-local 8000/tcp | awk -F: '{print $NF}')"
trap 'docker logs artie-mcp-local; docker rm --force artie-mcp-local' EXIT
until curl --fail --silent "http://127.0.0.1:${port}/health" && curl --fail --silent "http://127.0.0.1:${port}/ready"; do sleep 1; done
uv run python tests/smoke_client.py --url "http://127.0.0.1:${port}/mcp" --contract-path contract/policy.contract.json
```

This is a contributor workflow. Running the process yourself is not a supported Artie product.

## Workflow

1. Match neighboring files before inventing a new pattern.
2. Tool inventory changes go through the API spec + policy pin, not new Python tool functions.
3. Update `docs/` when behavior that contributors rely on changes.
