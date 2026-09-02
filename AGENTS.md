# AGENTS.md

Artie MCP is a Model Context Protocol server that exposes a reviewed set of Artie pipeline and infrastructure operations to coding agents. The supported endpoint is `https://mcp.artie.com/mcp`.

## Constraints

- **Hosted service**: `mcp.artie.com` is the supported product. Do not document self-hosting as supported.
- **Policy pin**: tools come from `contract/policy.lock.json`, not a hand-written allowlist in `server.py`.
- **Quality gate**: `uv lock --check && uv run ruff format --check . && uv run ruff check . && uv run python -m unittest discover -s tests -v` must pass before committing.

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

## Local AuthKit stand-in

Local OAuth against WorkOS Emulate is contributor-only. See [authkit-shim/README.md](authkit-shim/README.md).

```bash
docker compose up --build
```

## Workflow

1. Match neighboring files before inventing a new pattern.
2. Tool inventory changes go through the API spec + policy pin, not new Python tool functions.
3. Keep local-run instructions in this file or `authkit-shim/`, not the public README.
