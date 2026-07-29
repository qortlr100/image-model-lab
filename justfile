set shell := ["bash", "-euo", "pipefail", "-c"]

default: check

install:
    uv sync --frozen --all-packages
    corepack pnpm install --frozen-lockfile

format: install
    uv run ruff format packages/python services tools
    corepack pnpm format

format-check: install
    uv run ruff format --check packages/python services tools
    corepack pnpm format:check

lint: install
    uv run ruff check packages/python services tools
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

# Reject artifacts, oversized files and credentials in tracked content.
policy:
    uv run --frozen python tools/repo_policy.py

# Verify committed generated contracts match a fresh generation.
contract-check:
    uv run --frozen python tools/contract_drift.py

# Run the repository policy check on every commit in this clone.
install-hooks:
    git config core.hooksPath tools/hooks

check: policy lock-check contract-check format-check lint typecheck test build
