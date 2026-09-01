# Policy contract

Do not add MCP tools by registering functions in `server.py`. The inventory is compiled from a pinned Artie API spec.

1. Dashboard/API ships an OpenAPI document with `x-artie-mcp` on each operation (`exposure`, `operationId`, annotations, scopes, sensitivity).
2. `artie-api-spec` publishes a tagged `openapi.yaml`.
3. This repo pins that tag in `contract/policy.lock.json` (URL + SHA-256).
4. `scripts.download_policy_bundle` fetches the asset and verifies the checksum.
5. `compile_policy` keeps only `exposure: exposed` operations, rejects `restricted-credentials` except for a small explicit allowlist, and writes `contract/policy.contract.json`.
6. `FastMCP.from_openapi` publishes those tools. CI smoke compares `tools/list` to the committed contract (`tests/smoke_client.py --contract-path contract/policy.contract.json`).

To change what agents can call, change the spec annotation and pin a new release — not a hand-maintained route list.