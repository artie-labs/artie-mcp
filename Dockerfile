FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY contract/policy.lock.json contract/policy.contract.json ./contract/
COPY scripts/download_policy_bundle.py ./scripts/
COPY policy_adapter.py policy_contract.py published_contract.py server.py ./
RUN uv run --no-dev python -m scripts.download_policy_bundle

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "python", "server.py"]
