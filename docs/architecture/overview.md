# Architecture

Artie MCP is a remote Streamable HTTP server in front of the Artie Dashboard API. It is not a second control plane.

```
MCP client  --OAuth / API key-->  artie-mcp  --short-lived Artie credential-->  Artie API
                                      |
                                      +-- policy contract (pinned OpenAPI + x-artie-mcp)
```

- **Identity and authorization** live in Dashboard: AuthKit login, environment linking, scopes, grants. This process verifies the bearer and exchanges a WorkOS JWT for a short-lived Artie credential (legacy opaque API keys are forwarded during the OAuth migration).
- **Tool surface** is compiled from a checksum-pinned OpenAPI release (`contract/policy.lock.json` → `artie-api-spec`). Only operations annotated `x-artie-mcp.exposure: exposed` become tools. Request and response bodies are shaped to that contract.
- **Hosted endpoint** is `https://mcp.artie.com/mcp`. This repository is the source for that service. Self-hosting it is not a supported product.

Related: [contributing/policy-contract.md](../contributing/policy-contract.md).
