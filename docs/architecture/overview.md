# Architecture

System design for the Artie MCP server — how a coding agent reaches the Artie API, and what this repository is responsible for.

## Overview

Artie MCP is a Model Context Protocol server that exposes a reviewed subset of Artie pipeline and infrastructure operations to AI assistants. It is middleware: agents do not talk to the Dashboard API with a raw key from this process. The process authenticates the client, exchanges a short-lived Artie credential, and forwards only the operations the policy contract allows.

The supported product is the hosted Streamable HTTP endpoint [`https://mcp.artie.com/mcp`](https://mcp.artie.com/mcp). This repository is the source for that service. Self-hosting it is not a supported Artie product. Customer setup stays on [artie.com/docs/api/mcp](https://www.artie.com/docs/api/mcp).

```
LLM / IDE
  ↓  MCP tools/call (Streamable HTTP)
artie-mcp  (this repo)
  ↓  OAuth: verify AuthKit JWT, RFC 8693 exchange
  ↓  legacy: forward opaque Artie API key
Artie API  (Dashboard remains identity, grants, scopes, audit)
```

## Repository structure

This is a single Python process, not a package monorepo. There is no stdio transport and no published npm package.

```
artie-mcp/
├── server.py              # FastMCP process: auth, OpenAPI tools, HTTP app
├── policy_contract.py     # compile pinned OpenAPI + x-artie-mcp into the tool contract
├── policy_adapter.py      # shape upstream successes; strip unapproved fields
├── mcp_observability.py   # initialize / tools/call metrics and JSON logs
├── contract/              # policy.lock.json + committed contract snapshot
├── scripts/               # download / pin / verify the policy bundle
├── plugins/artie/         # Claude Code / Cursor plugin (URL, subagent, skills)
├── docs/                  # contributor documentation
└── tests/                 # unit tests + container smoke client
```

### `server.py`

The process. FastMCP implements MCP. This file does **not** register one Python function per Artie route.

**Responsibilities:**

- AuthKit (WorkOS) as the OAuth verifier, plus accept-and-forward for legacy opaque API keys
- RFC 8693 token exchange so tool calls hit the Artie API with a short-lived credential
- `FastMCP.from_openapi` using the pinned spec, filtered by the contract
- HTTP response hook that shapes successes and sanitizes errors
- Server card, health, and ready routes
- `stateless_http=True` Streamable HTTP app (any replica can serve any request)

### `policy_contract.py`

Compiles `contract/policy.openapi.yaml` into `PolicyContract`. Only `x-artie-mcp.exposure: exposed` operations become tools. `restricted-credentials` input or output is rejected unless the `operationId` is on a small explicit allowlist — that allowlist is not a tool inventory, and adding a name there does not publish a tool until the spec marks it exposed.

### `policy_adapter.py`

`SafeTrafficAdapter` maps method + path to an approved tool and projects JSON successes onto the committed schema. Bodiless 202/204 successes become `{"success": true}`. A success we cannot shape is a server defect: the client sees a generic tool error; the operator log gets `response_shaping_error`.

### `contract/`

- `policy.lock.json` — release tag, asset URL, SHA-256
- `policy.openapi.yaml` — downloaded spec (gitignored if missing; `scripts.download_policy_bundle` restores it)
- `policy.contract.json` — committed tool list CI compares to `tools/list`

How a pin is cut: [contributing/policy-contract.md](../contributing/policy-contract.md).

### `plugins/artie/`

Not a second server. Claude Code and Cursor install this plugin so a subagent (`agents/artie-mcp.md`) and skills attach to `https://mcp.artie.com/mcp`. Tools still come from the hosted contract. Layout: [integrations/claude-code-plugin.md](../integrations/claude-code-plugin.md).

### `tests/`

Unit tests cover compile, shaping, auth helpers, and observability. `tests/smoke_client.py` starts against a local image and asserts `tools/list` matches the committed contract. That is the inventory gate, not a live Artie API eval suite.

## Key architectural decisions

### 1. Protocol implementation

Uses FastMCP (official MCP SDK under the hood) so `tools/list` / `tools/call` stay compatible with Claude Code, Cursor, Codex, and other Streamable HTTP clients.

Tools are generated from OpenAPI:

```python
mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    route_map_fn=_route_map,      # only contract (method, path) pairs
    mcp_component_fn=_configure_tool,  # title, trigger text, annotations
    strict_input_validation=True,
)
```

Do not add MCP tools by decorating functions in `server.py`. Change the API spec annotation and pin a new release.

### 2. Transport

**Streamable HTTP only**, hosted at `/mcp`. There is no stdio binary and no SSE compatibility endpoint.

`http_app(..., stateless_http=True)` is deliberate: token exchange is per-request (cached by a hash of the bearer, not by a server session). Replicas do not share MCP session state.

Discovery extras on this origin:

- `GET /mcp/server-card` — MCP server card (`application/mcp-server-card+json`)
- `GET /health`, `GET /ready` — load balancer probes
- Protected-resource metadata from AuthKit so OAuth clients find the authorization server

### 3. Authentication

Identity and authorization live in Artie Dashboard (AuthKit login, environment linking, scopes, grants, audit). This process verifies the bearer and obtains an Artie API credential.

| Client credential | What this process does |
| --- | --- |
| AuthKit JWT (OAuth) | Verify, then RFC 8693 token-exchange for a short-lived Artie credential against the user's durable grant. Pending grants return `authorization_pending` + `user_code`. |
| Opaque Artie API key | Forward as-is during the OAuth migration. New integrations must use OAuth. |

WorkOS tokens are JWTs (three dot-separated parts). API keys are not. The dual verifier must not let an expired JWT fall through as a “key.”

Exchange and tool calls use the same `ARTIE_API_BASE_URL`. No long-lived Artie token is stored; only the short-lived credential is cached until near expiry.

### 4. Tool inventory

The allowlist is the pinned spec, not a Python list of handlers.

1. Dashboard OpenAPI carries `x-artie-mcp` on every external operation.
2. `artie-api-spec` publishes a tagged `openapi.yaml`.
3. This repo pins that tag in `contract/policy.lock.json`.
4. `compile_policy` keeps `exposed` operations and writes `contract/policy.contract.json`.
5. FastMCP publishes those tools. CI smoke compares `tools/list` to the snapshot.

Titles, trigger descriptions, scopes, and MCP annotations (`readOnlyHint`, `destructiveHint`, …) come from the spec extension, applied in `_configure_tool`.

### 5. Response shaping

Upstream JSON is not passed through verbatim. The adapter keeps fields the success schema allows so agents do not see connector secrets or Dashboard-only wrappers (for example `includeRelatedObjects` on a pipeline GET).

Shaping runs on the httpx response hook before FastMCP turns the body into a tool result.

### 6. Error handling

Two audiences: the agent, and the operator log.

| Upstream | Client sees | Operator log |
| --- | --- | --- |
| 4xx with `{"error": "..."}` | that error string (truncated) | `upstream_error` with the same string |
| 5xx or unreadable body | `{"error":"upstream request failed"}` | status + body *shape* (content-type, byte length) — sibling fields on an error object can hold credentials |
| Shaping failure on 2xx | generic tool error | `response_shaping_error` |

Do not log raw upstream error JSON. Auth failures happen before the tool-call hook; they are not `mcp.operation:tool_call` rows.

### 7. Observability

`MCPObservability` middleware records `initialize` and `tools/call` duration and outcome (`mcp.request`, `mcp.request.duration`) via OTLP. Unknown tool names are tagged `unknown` rather than echoing arbitrary strings as metric attributes.

## Data flow

```
1. Client tools/call  (Authorization: Bearer …)
   ↓
2. FastMCP verifies AuthKit JWT or accepts a legacy API key
   ↓
3. _DeviceLinkAuth attaches an Artie credential
   (exchange for JWTs, forward for opaque keys)
   ↓
4. httpx calls ARTIE_API_BASE_URL on the contract path
   ↓
5. Response hook: shape success or sanitize error
   ↓
6. FastMCP returns the MCP tool result to the client
```

Dashboard remains authoritative for whether that credential may touch the pipeline. This process does not re-implement grants.

## Tools

MCP **tools** are the exposed Artie API operations. Examples (names come from `operationId`; the live set is `contract/policy.contract.json`):

- `connector_list` / `connector_fetch_databases` / `connector_fetch_tables` — saved-connector discovery
- `pipeline_create_from_source` / `pipeline_update` / `pipeline_start` — draft, attach dest+tables, deploy
- `pipeline_list` / `pipeline_detect_schema_changes` — inventory and a source schema check
- `data_catalog_search` — ingested catalog metadata, not a live source walk

There is no `search_artie_tools` catalog gateway. If an operation is not in `tools/list`, it is not callable. Skills in `plugins/artie/skills/` tell the subagent *which* of those tools to use; they do not add tools.

Saved connectors are created in the [Artie Dashboard](https://app.artie.com). Do not treat credential-entry routes as the supported agent path even if a future spec pin exposes one.

## Performance and operations

- Stateless HTTP: no sticky MCP sessions across replicas.
- Token-exchange cache is in-process, keyed by a hash of the full bearer, with single-flight locks per key.
- No response cache of Artie API bodies between requests.
- Upstream client timeout and TLS verify are env-driven (`ARTIE_API_INSECURE_SKIP_VERIFY` is local-only against a self-signed Dashboard).

## Related

- Policy pin workflow: [contributing/policy-contract.md](../contributing/policy-contract.md)
- Plugin / subagent: [integrations/claude-code-plugin.md](../integrations/claude-code-plugin.md)
