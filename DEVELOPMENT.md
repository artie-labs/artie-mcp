# Development

Contributor workflow for this repository. Running the process yourself is not a supported Artie product. The hosted service is <https://mcp.artie.com>.

## Setup

```bash
uv sync --locked --all-groups
```

Fetch the pinned policy bundle if `contract/policy.openapi.yaml` is missing; it is not committed:

```bash
uv run python -m scripts.download_policy_bundle
```

## Run locally

```bash
uv run python server.py
```

Listens on `0.0.0.0:8000`. Leave `WORKOS_AUTHKIT_DOMAIN` and `MCP_PUBLIC_BASE_URL` unset to use the debug token verifier. Set both together to enable AuthKit.

## Verify

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q server.py tests
uv run python -m unittest discover -s tests -v
```

## Smoke-test the image

Smoke-test a local image against the **committed** contract, not a mutable upstream OpenAPI URL:

```bash
docker build --tag artie-mcp:local .
docker run --detach --rm --name artie-mcp-local -p 127.0.0.1::8000 artie-mcp:local
port="$(docker port artie-mcp-local 8000/tcp | awk -F: '{print $NF}')"
trap 'docker logs artie-mcp-local; docker rm --force artie-mcp-local' EXIT
until curl --fail --silent "http://127.0.0.1:${port}/health" && curl --fail --silent "http://127.0.0.1:${port}/ready"; do sleep 1; done
uv run python tests/smoke_client.py --url "http://127.0.0.1:${port}/mcp" --contract-path contract/policy.contract.json
```

## Release

1. Update the version in `pyproject.toml`.
2. Update the lockfile:

   ```bash
   uv lock
   ```

3. Commit with message `Release vx.x.x`:

   ```bash
   git add pyproject.toml uv.lock
   git commit --message "Release vx.x.x"
   ```

4. Run the release script, which builds and pushes a Docker image:

   ```bash
   ./release.sh
   ```
