FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first for layer caching
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY gateway ./gateway
COPY demo ./demo
COPY evals ./evals
COPY config ./config
RUN uv sync --frozen --no-dev

RUN useradd --create-home tollgate && chown -R tollgate /app
USER tollgate
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"
CMD ["/app/.venv/bin/uvicorn", "--factory", "gateway.main:app_factory", "--host", "0.0.0.0", "--port", "8080"]
