# tacit server for Fly.io (SPEC §16): API, PWA, landing page, Vapi and Stripe webhooks.
# One machine, one volume at /data. No band kit, no secrets, no tests in the image.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    TACIT_DATA_DIR=/data

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY pwa/ ./pwa/
COPY landing/ ./landing/
COPY design-system/ ./design-system/
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 tacit \
    && mkdir -p /data && chown -R tacit:tacit /data /app
USER tacit

EXPOSE 8000
CMD ["/app/.venv/bin/tacit", "serve", "--host", "0.0.0.0", "--port", "8000"]
