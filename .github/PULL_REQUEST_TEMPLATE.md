## Summary

<!-- What does this change, and why? -->

## Test plan

- [ ] `uv lock --check`
- [ ] `uv run ruff format --check . && uv run ruff check .`
- [ ] `uv run python -m unittest discover -s tests -v`

## Notes for reviewers

- This repository is the hosted MCP integration, not a supported self-hosted product.
- Do not include credentials, customer fixtures, or live transcripts.
