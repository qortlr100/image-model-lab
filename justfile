set shell := ["bash", "-euo", "pipefail", "-c"]

default: check

install:
    uv sync --frozen --all-packages
    corepack pnpm install --frozen-lockfile

format: install
    uv run ruff format packages/python
    corepack pnpm format

format-check: install
    uv run ruff format --check packages/python
    corepack pnpm format:check

lint: install
    uv run ruff check packages/python
    corepack pnpm lint

typecheck: install
    uv run pyright
    corepack pnpm typecheck

test: install
    uv run pytest
    corepack pnpm test

build: install
    uv build --all-packages --out-dir dist/python
    corepack pnpm build

lock-check:
    uv lock --check
    corepack pnpm install --lockfile-only --frozen-lockfile

check: lock-check format-check lint typecheck test build
