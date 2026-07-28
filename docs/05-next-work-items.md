# 다음 구현 작업

아래 항목은 가능한 한 하나의 Draft PR로 검토 가능한 크기로 나눈 초기 backlog다. 번호는 의존 순서를 나타내며 GitHub issue 번호가 아니다.

## M0. 저장소 기반

### M0-01 — Dual workspace와 공통 명령

상태: 구현 완료

범위:

- root `pyproject.toml`, `uv.lock`, `pnpm-workspace.yaml`, `package.json`, lockfile
- `justfile`의 `format`, `lint`, `typecheck`, `test`, `check`
- Python/TypeScript 최소 package 하나씩

완료 조건:

- clean checkout에서 `just check`가 GPU와 NAS 없이 성공한다.
- lockfile 없는 설치를 CI가 허용하지 않는다.

### M0-02 — Service skeleton

범위:

- `apps/web`, `services/api`, `services/worker`, `services/dgx-agent`
- 각 서비스의 health/version endpoint 또는 command
- 서비스별 최소 Dockerfile

완료 조건:

- 네 서비스가 독립 실행·build된다.
- API/Worker image에 PyTorch나 engine dependency가 없다.

### M0-03 — CI와 repository policy

범위:

- format/lint/type/test/build workflow
- secret scan과 대용량 binary 방지 check
- generated contract drift check 자리 마련

완료 조건:

- `.safetensors`와 임계 크기 초과 파일 commit이 차단된다.
- 모든 check가 CPU runner에서 성공한다.

## M1. Contract와 persistence

### M1-01 — Artifact URI와 digest value object

범위:

- `nas://` parser/formatter
- SHA-256, size, media type validation
- path traversal과 invalid namespace tests

완료 조건:

- machine mount path가 domain object에 들어갈 수 없다.
- serialization fixture가 versioned schema를 통과한다.

### M1-02 — Domain lifecycle seed

범위:

- `Artifact`, `ExecutionJob`, `RunAttempt`, `DatasetSnapshot` 최소 domain model
- 상태 전이와 sealed immutability tests

완료 조건:

- invalid transition이 framework와 무관한 unit test에서 거부된다.

### M1-03 — PostgreSQL baseline

범위:

- SQLAlchemy mapping, repository ports/adapter
- Alembic baseline migration
- disposable Postgres integration test

완료 조건:

- migration upgrade/downgrade가 빈 DB에서 성공한다.
- domain package가 SQLAlchemy를 import하지 않는다.

### M1-04 — OpenAPI와 TypeScript client generation

범위:

- health/version과 artifact contract
- deterministic OpenAPI export
- generated TypeScript client

완료 조건:

- 생성 후 diff가 없음을 CI가 확인한다.
- Web은 hand-written API response type을 만들지 않는다.

## M2. 위험 제거 spike

### M2-01 — DGX Spark engine compatibility matrix

범위:

- `anima_lora` pinned release/commit clean install
- Anima 지원 `sd-scripts` pinned commit clean install
- architecture, CUDA, Python, PyTorch, flash-attention 기록

완료 조건:

- 재실행 가능한 명령과 redacted environment report가 있다.
- 성공/실패를 추측하지 않고 raw log artifact로 남긴다.

### M2-02 — 100-step training parity fixture

범위:

- 작고 권리 확인된 test dataset snapshot
- 공통 recipe 의도와 engine별 rendered config
- checkpoint와 ComfyUI load test

완료 조건:

- output key rewrite 필요 여부가 확인된다.
- 결과 품질이 아니라 실행·호환성·provenance를 먼저 판정한다.

### M2-03 — 첫 training adapter ADR

범위:

- M2-01/02 결과 비교
- 첫 production-ready adapter와 fallback 결정
- upstream pin/update 정책

완료 조건:

- 선택 근거와 재검토 조건이 ADR로 승인된다.

## M3. 첫 vertical slice

### M3-01 — Image ingest command

범위:

- 허용된 inbox에서 한 파일 ingest
- SHA-256, metadata, artifact atomic publish
- exact duplicate idempotency

완료 조건:

- 같은 파일 두 번 ingest 시 blob은 하나다.
- 실패 주입 test에서 partial publish가 current가 되지 않는다.

### M3-02 — Asset catalog API와 grid

범위:

- pagination/filter API
- thumbnail route
- virtualized grid와 detail panel

완료 조건:

- NAS path가 API 응답에 노출되지 않는다.
- 수천 건 fixture에서 모든 원본을 한 번에 읽지 않는다.

### M3-03 — Similar duplicate review

범위:

- 한 perceptual hash 알고리즘 spike와 threshold 기록
- candidate 생성, side-by-side review, keep/relate decision

완료 조건:

- 자동 삭제 경로가 없다.
- algorithm/version/score가 decision과 함께 보존된다.

## 권장 첫 구현 순서

1. M0-01
2. M0-02
3. M0-03
4. M1-01
5. M1-02
6. M1-03
7. M1-04
8. M2-01과 M2-02
9. M2-03
10. M3-01

M2 engine spike는 M1 전체가 끝날 때까지 기다릴 필요는 없지만, 실제 training management 코드는 M2-03 결정 전에 시작하지 않는다.
