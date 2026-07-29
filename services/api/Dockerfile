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
RUN uv sync --frozen --no-dev --package image-model-lab-api

RUN useradd --system --create-home image-model-lab
USER image-model-lab

ENV IMAGE_MODEL_LAB_API_HOST=0.0.0.0 \
    IMAGE_MODEL_LAB_API_PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["image-model-lab-api"]
