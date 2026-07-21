FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY scripts/download_openapi_spec.py ./scripts/download_openapi_spec.py
RUN uv run --no-dev python scripts/download_openapi_spec.py /app/openapi.yaml

COPY server.py ./

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "python", "server.py"]
