FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY openapi_contract.py ./
COPY scripts/download_openapi.py ./scripts/download_openapi.py
RUN python scripts/download_openapi.py
COPY server.py ./

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "python", "server.py"]
