# AGENTS.md

This repository is a design-first monorepo for a personal image-model lab. Follow these rules for every change.

## Start here

1. Read `README.md` and all documents directly relevant to the task.
2. Treat `docs/00-scope.md` as the product boundary and `docs/01-architecture.md` as the service boundary.
3. Record a new ADR when changing a durable cross-service, persistence, protocol, or deployment decision.
4. Keep PRs vertical and small. Do not scaffold unrelated future phases.

## Repository boundaries

- `apps/web` is a browser client. It talks only to the public API contract and never reads NAS paths or the database directly.
- `services/api` owns synchronous commands, queries, authorization, and OpenAPI publication.
- `services/worker` performs control-plane background work and never launches GPU training directly.
- `services/dgx-agent` leases execution jobs and runs isolated captioning or training adapters on a capable node.
- `packages/python/domain` contains pure domain rules with no framework, database, filesystem, network, PyTorch, or model imports.
- `packages/python/application` contains use cases and ports. Infrastructure depends inward on it.
- Heavy engine environments such as `anima_lora` and `sd-scripts` are external, pinned execution environments. Do not add them to the API, worker, or shared package dependency graph.

## Data and artifact rules

- Never commit images, model weights, LoRA files, checkpoints, generated outputs, caches, logs, credentials, or machine-specific NAS paths.
- Persist logical artifact URIs such as `nas://datasets/...`; resolve them through deployment configuration.
- All stored artifacts must have a byte size, media type, SHA-256 digest, and provenance.
- Never mutate a sealed dataset snapshot or a completed run manifest. Create a new revision.
- Duplicate detection creates review candidates; it must not silently delete source images.
- A generated image can become a dataset candidate only after explicit review. It must not enter a sealed snapshot automatically.
- Redact secrets and signed URLs from command captures and logs before persistence.

## Contracts and compatibility

- The API OpenAPI document is the source for the generated TypeScript client.
- Version durable JSON manifests and execution protocols explicitly.
- Readers should accept the current version and at least one preceding version during migrations when practical.
- Store both raw ComfyUI workflow JSON and a normalized fingerprint. Never discard the raw workflow.
- Adapter output must be normalized into domain events; engine-specific log text is supplemental evidence, not the primary state model.

## Python

- Target the version selected in `docs/03-technology-decisions.md`.
- Use `uv` workspaces and committed lockfiles.
- Use type annotations for public functions and Pydantic only at I/O boundaries.
- Use SQLAlchemy and Alembic only in persistence packages or service composition roots.
- Format and lint with Ruff, type-check with Pyright, and test with pytest.
- Unit tests must not require a GPU, NAS, external model download, or network access.

## TypeScript

- Use a strict TypeScript configuration.
- Use pnpm with a committed lockfile.
- Keep server state in the generated API client and query layer; do not duplicate domain rules in the UI.
- Format with Prettier, lint with ESLint, test components with Vitest, and reserve Playwright for critical flows.

## Database and migrations

- PostgreSQL is the metadata system of record.
- Every schema change requires an Alembic migration and a downgrade path unless the PR documents why downgrade is unsafe.
- Do not encode lifecycle invariants only in UI code. Enforce them in domain code and, where useful, database constraints.
- Job claims must be idempotent and lease-based. A worker crash may produce a retry, so handlers must tolerate at-least-once execution.

## Adapters

Every training adapter must implement the common lifecycle:

1. validate engine and capabilities;
2. render an immutable engine input bundle;
3. launch without shell interpolation;
4. emit normalized progress and checkpoint events;
5. handle cancellation and lease loss;
6. collect outputs and provenance;
7. produce a final run manifest.

Pin an engine by immutable tag plus digest or commit SHA. Never execute an unpinned `latest` environment for a reproducible run.

## Validation and documentation

- Before committing, run the narrowest relevant checks and then the repository-wide check once it exists.
- A feature is incomplete without tests for its invariants and failure modes.
- Update architecture, domain, roadmap, and ADR documents when their claims change.
- Do not document planned commands as available commands. Clearly label future structure and commands until implemented.

## Git hygiene

- Keep generated clients and schemas deterministic.
- Stage only files in the requested scope.
- Use concise imperative commit subjects.
- Default to Draft PRs for multi-step work.
