# Contributing

Thanks for wanting to contribute. This repository is the source for Artie's **hosted** MCP server at `https://mcp.artie.com/mcp`. Dashboard/API remain authoritative for identity, grants, scopes, and resource authorization.

Self-hosting this process is not a supported contribution goal.

Contributor workflows, repo map, and commands: [AGENTS.md](AGENTS.md). Topic guides: [docs/README.md](docs/README.md).

## Before you start

1. Read [SUPPORT.md](SUPPORT.md) so the change belongs in this repository.
2. Search existing issues and pull requests.
3. For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening an issue or PR.

## Development

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q server.py tests
uv run python -m unittest discover -s tests -v
```

The unit tests compile the pinned policy contract. Download the bundle first if `contract/policy.openapi.yaml` is missing:

```bash
uv run python -m scripts.download_policy_bundle
```

Do not point smoke tests at a mutable upstream OpenAPI URL. Use the committed contract:

```bash
uv run python tests/smoke_client.py \
  --url "http://127.0.0.1:${port}/mcp" \
  --contract-path contract/policy.contract.json
```

## Pull requests

- Keep the change scoped. Do not mix policy-allowlist, documentation, and unrelated refactors.
- Policy exposure (`x-artie-mcp`) lives in the Artie API spec release, not as an ad-hoc tool list in this server. This repo pins a released spec in `contract/policy.lock.json`.
- Do not commit credentials, `.envrc`, personal overrides, customer fixtures, or live tool transcripts.
- Fill in the pull request template. A maintainer from [@artie-labs/engineering](https://github.com/orgs/artie-labs/teams/engineering) reviews.

## Code of conduct

Participation is covered by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
