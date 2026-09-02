# Local AuthKit stand-in

Local contributor stack. Not a supported Artie product and not what
`mcp.artie.com` runs.

WorkOS Emulate covers authorize / authenticate / JWKS. FastMCP's
`AuthKitProvider` and MCP clients also need OIDC discovery and dynamic
client registration, which the emulator does not serve. `shim.py` fills
those gaps and translates `POST /oauth2/token` into the emulator's
`POST /user_management/authenticate`.

## Run

From the repository root:

```bash
docker compose up --build
```

That starts:

- Emulator login UI: `http://127.0.0.1:4100`
- AuthKit shim (JWT issuer): `http://host.docker.internal:4110`
- MCP: `http://127.0.0.1:9000/mcp` (hot-reloads this checkout)

Dashboard stays on the host. Point it at the same issuer and audience:

```bash
WORKOS_AUTHKIT_ISSUER=http://host.docker.internal:4110
MCP_RESOURCE_URL=http://127.0.0.1:9000/mcp
```

Stop any host uvicorn on `:9000` first so Compose can bind that port.

Cursor: `http://127.0.0.1:9000/mcp`. Seeded login is in
`workos-emulate.config.yaml`.

If you change the MCP port, also change `jwtTemplate.aud` in
`workos-emulate.config.yaml` to `{MCP_PUBLIC_BASE_URL}/mcp` and recreate
the emulator container so it reseeds.
