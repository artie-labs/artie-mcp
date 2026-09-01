# artie-mcp

Source for Artie's **hosted** [Model Context Protocol](https://modelcontextprotocol.io/) server. Compatible MCP clients can manage approved Artie pipeline and infrastructure operations through the Artie API.

The supported endpoint is:

```text
https://mcp.artie.com/mcp
```

Artie Dashboard and API remain authoritative for identity, grants, environment binding, scopes, audit, and resource authorization. This repository is a reference implementation of that hosted integration, not a supported self-hosted Artie product.

Client setup: [MCP documentation](https://www.artie.com/docs/api/mcp). API: [API reference](https://www.artie.com/docs/api/overview).

## Connect with OAuth

OAuth is the supported authentication path. Point an OAuth-capable client (Cursor, Claude Code, Codex, and similar) at the server URL. Do not add an Artie API key or bearer-token header for a new setup. The client discovers AuthKit from protected-resource metadata, signs you in, and on first tool use may ask you to link an Artie environment and scopes in the Dashboard.

```json
{
  "mcpServers": {
    "artie": {
      "url": "https://mcp.artie.com/mcp"
    }
  }
}
```

Client-specific snippets are in the [MCP documentation](https://www.artie.com/docs/api/mcp).

## Legacy API keys

API keys still work during the OAuth migration so existing automations are not cut over blindly. **New integrations must use OAuth.** Artie Engineering owns the remaining compatibility window; there is no public sunset date yet.

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

## What is not supported

- Running this server yourself in production, or treating a local process as an Artie product
- Creating or updating connector credentials through MCP — configure those in the [Dashboard](https://app.artie.com), then use approved MCP tools for pipeline work
- Filing account, pipeline, or security issues as public GitHub issues

## Help and security

| Topic | Route |
| --- | --- |
| Hosted product help, OAuth, pipelines | [SUPPORT.md](SUPPORT.md), [docs](https://www.artie.com/docs/api/mcp), [Dashboard](https://app.artie.com) |
| Vulnerability | [SECURITY.md](SECURITY.md) — private reporting only |
| Code or protocol bug in this repo | GitHub issue |

## Development

This project is not a supported self-hosted deployment. The commands below are for contributors working on this source.

```bash
uv sync --locked --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q server.py tests
uv run python -m unittest discover -s tests -v
```

### Smoke-test a local image

This check verifies that `tools/list` matches the **committed** policy contract, not a mutable upstream OpenAPI URL.

```bash
docker build --tag artie-mcp:local .
docker run --detach --rm --name artie-mcp-local -p 127.0.0.1::8000 artie-mcp:local
port="$(docker port artie-mcp-local 8000/tcp | awk -F: '{print $NF}')"
trap 'docker logs artie-mcp-local; docker rm --force artie-mcp-local' EXIT
until curl --fail --silent "http://127.0.0.1:${port}/health" && curl --fail --silent "http://127.0.0.1:${port}/ready"; do sleep 1; done
uv run python tests/smoke_client.py --url "http://127.0.0.1:${port}/mcp" --contract-path contract/policy.contract.json
```

## License

MIT. See [LICENSE](LICENSE).
