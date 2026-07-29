FROM ghcr.io/astral-sh/uv:0.11.29 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /uvx /bin/
ENV PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/python packages/python
COPY services services
RUN uv sync --frozen --no-dev --package image-model-lab-worker

RUN useradd --system --create-home image-model-lab
USER image-model-lab

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD image-model-lab-worker health || exit 1

CMD ["image-model-lab-worker", "run"]
