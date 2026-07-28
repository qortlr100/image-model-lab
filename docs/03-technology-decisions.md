# 기술 스택 후보 비교 및 결정

결정 시점은 2026-07-28이다. 라이브러리의 `latest`를 실행 기록에 저장하지 않고, 구현 시 lockfile과 immutable upstream revision을 함께 기록한다.

## 결정 요약

| 영역 | 결정 | 이유 |
|---|---|---|
| Web | React + Vite + TypeScript | 별도 API가 source of truth인 단일 사용자 SPA에 적합 |
| API | FastAPI + Pydantic | Python 도메인과 자연스럽게 연결되고 OpenAPI client 생성이 쉬움 |
| DB | PostgreSQL + SQLAlchemy 2 + Alembic | 여러 서비스, job lease, JSON metadata와 제약 처리 |
| Worker/Agent | Python 3.13, 별도 프로세스 | 이미지·ML 생태계 활용, GPU 환경 격리 |
| Python workspace | uv | 빠른 lock/sync와 workspace 지원 |
| TypeScript workspace | pnpm | 엄격한 workspace dependency 관리 |
| Queue | PostgreSQL durable job + API lease | 개인 규모에서 운영 요소를 줄이고 재현 가능한 상태 유지 |
| Artifact store | NAS POSIX adapter + logical URI | 현재 인프라를 사용하면서 경로 결합 방지 |
| Schema | OpenAPI + versioned JSON Schema | HTTP client와 장기 보존 manifest를 분리 |
| Observability | structured JSON log + DB run event | 초기 운영 복잡도를 낮추고 실행 추적 보존 |

## Web: React/Vite 선택

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| React + Vite SPA | API 경계가 명확하고 배포가 단순함 | SSR 기본 제공 없음 | **선택** |
| Next.js | routing, SSR, server 기능 통합 | 별도 FastAPI와 책임 중복 가능 | 공개 SEO/SSR 요구가 생기면 재검토 |
| SvelteKit | 작은 bundle과 간결한 UI | 프로젝트 내 표준화와 생태계 선택 비용 | 보류 |

초기 UI는 React, TypeScript strict, TanStack Query, 가상화 가능한 image grid, 접근 가능한 component primitives로 구성한다. router와 component kit은 첫 UI vertical slice에서 작은 spike 후 고정한다.

## API: FastAPI 선택

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| FastAPI | Python, Pydantic, OpenAPI, async I/O | admin UI를 직접 구현 | **선택** |
| Django + DRF | ORM/admin/migration 통합 | domain/adapter 경계가 무거워질 수 있음 | 빠른 내부 admin이 최우선이면 재검토 |
| NestJS | 강한 TypeScript 구조 | ML·이미지 Python 계층과 계약이 하나 더 생김 | 제외 |

[FastAPI 공식 문서](https://fastapi.tiangolo.com/)가 제공하는 OpenAPI를 contract artifact로 export하고, TypeScript client를 deterministic하게 생성한다. Pydantic 모델은 API와 durable schema 경계에서 사용하고 순수 domain object 전체에 확산시키지 않는다.

## Python과 JavaScript workspace

- first-party Python 서비스는 Python 3.13과 [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)를 사용한다.
- Web과 생성 client는 [pnpm workspace](https://pnpm.io/workspaces)를 사용한다.
- root task runner는 `just`를 우선 사용해 `check`, `test`, `dev` 명령을 통합한다.
- 각 service image는 필요한 workspace package만 설치한다.
- GPU engine은 first-party workspace에 포함하지 않고 자체 lockfile 환경을 유지한다.

Python 3.13 또는 ARM64 wheel 호환성 문제가 발견되면 control plane만 3.12로 내릴 수 있다. 이 결정은 Phase 0 compatibility spike에서 lock과 container build로 검증한다.

## Metadata: PostgreSQL 선택

SQLite는 단일 프로세스 prototype에는 적합하지만 API, Worker, Agent가 동시에 상태를 변경하고 job lease를 다루는 구조에는 제약이 크다. PostgreSQL은 transaction, row locking, JSONB, partial index와 제약 조건을 제공하므로 metadata source of truth로 선택한다.

- SQLAlchemy 2 repository와 Alembic migration 사용
- UTC timestamp 저장, UI에서 local timezone 변환
- UUID primary key
- engine-specific raw config는 version과 함께 JSONB 저장
- digest, 상태, 관계 등 핵심 검색 필드는 정규 column 사용

[PostgreSQL 공식 문서](https://www.postgresql.org/docs/current/index.html)의 지원 버전 중 homeserver에서 운영하는 major를 명시적으로 pin한다.

## Queue: PostgreSQL lease 선택

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| PostgreSQL queue + API lease | 단일 source of truth, 적은 운영 요소 | 매우 높은 처리량에는 부적합 | **초기 선택** |
| Redis + Celery/Dramatiq | 익숙한 worker ecosystem | durable 상태와 broker 상태 조정 필요 | 성능 근거가 생기면 검토 |
| NATS JetStream | 견고한 event/consumer 모델 | 개인 시스템에는 초기 운영 비용이 큼 | 다수 agent/fan-out 시 검토 |

Agent가 DB에 직접 접속하지 않고 API를 통해 lease하도록 해 네트워크와 권한 경계를 단순화한다. Worker는 내부용 동일 application service를 사용하되 job claim 규칙은 공통 domain/application package에 둔다.

## Artifact: NAS filesystem 선택

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| NAS POSIX | 기존 인프라, rename과 일반 도구 활용 | mount/config 차이 | **초기 선택** |
| S3/MinIO | object semantics, signed URL, lifecycle | 추가 서비스와 migration 비용 | adapter로 후속 지원 |
| DB blob | transaction 단순화 | 대용량 모델/이미지에 부적합 | 제외 |

DB에는 `nas://` URI만 저장하고 실제 mount root는 서비스 설정으로 주입한다. 모든 artifact는 SHA-256을 필수로 한다. 유사 이미지 탐지는 별도 perceptual hash를 사용하며 content identity를 대체하지 않는다.

## Captioning adapter

### WD EVA02 Large Tagger v3

[모델 카드](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3)에 따르면 rating, character, general tag를 제공하는 Danbooru 기반 태거다.

- 장점: 구조화 tag, threshold 기반 재현성, 비교적 낮은 실행 비용
- 용도: 1차 tag proposal과 duplicate/review filter 보조
- 보존값: 정확한 model revision, tag CSV revision, general/character threshold, preprocessing
- 제한: 자연어 관계·구도 설명과 데이터셋 밖 개념에 약함

### JoyCaption Beta One

[모델 카드](https://huggingface.co/fancyfeast/llama-joycaption-beta-one-hf-llava)는 diffusion 학습용 caption VLM이며 Transformers, vLLM, SGLang 경로를 제시한다.

- 장점: 자연어와 지시형 caption, prompt template로 목적 조정 가능
- 용도: WD tags를 보조 입력으로 받은 상세 caption proposal
- 보존값: model revision, inference server/runtime, system/user template, decoding params, raw response
- 제한: 더 큰 VRAM/시간, prompt 변화에 따른 출력 편차

두 결과를 자동으로 하나의 정답으로 합치지 않는다. 독립 proposal로 저장한 뒤 template-versioned merge 또는 사람 편집을 거쳐 승인한다.

## Training engine

### `sorryhyun/anima_lora`

[공식 저장소](https://github.com/sorryhyun/anima_lora)는 Anima 전용 LoRA/T-LoRA 엔진, dataset browser와 training monitor를 제공하고, 자체 Python·PyTorch·CUDA 조합과 `uv.lock` 사용을 요구한다.

- Anima 최적화와 빠른 실험을 위해 **첫 번째 POC 후보**
- upstream을 fork/vendor하지 않고 pinned external checkout 또는 release environment로 설치
- adapter는 config chain과 CLI를 입력 bundle로 렌더링하고 outputs를 정규화
- ComfyUI 호환 export 원본과 변환본의 digest를 각각 보존
- upstream의 빠른 변화에 대비해 adapter contract test와 golden fixture 필수

### `kohya-ss/sd-scripts`

[공식 저장소](https://github.com/kohya-ss/sd-scripts)는 범용 LoRA 학습 script 모음이며 Anima 관련 구현 경로가 발전 중이다.

- 장점: 넓은 생태계와 비교 가능한 표준 옵션
- 단점: Anima 지원 branch/commit과 output key compatibility를 실제로 검증해야 함
- 두 번째 POC 후보로 같은 dataset/recipe의 parity test 수행
- “범용이므로 기본값”으로 가정하지 않고 검증 완료 후 adapter를 production-ready로 승격

### 결정 조건

첫 production-ready adapter는 다음을 모두 만족한 후보로 정한다.

1. DGX Spark에서 clean install과 100-step smoke training 성공
2. 중단, 재시도, checkpoint 수집과 종료 코드 처리 성공
3. ComfyUI에서 별도 key rewrite 없이 로드되거나, 재현 가능한 공식 변환 단계 제공
4. 같은 입력에서 manifest와 output digest를 완전히 기록
5. upstream revision pin과 reinstall 가능

현재 우선순위는 `anima_lora`지만 검증 전 확정된 기본 엔진으로 표현하지 않는다.

## ComfyUI integration

[ComfyUI workflow 문서](https://docs.comfy.org/development/core-concepts/workflow)는 generated image metadata와 JSON 파일에 workflow를 보존할 수 있음을 설명한다. 초기에는 다음 순서로 통합한다.

1. PNG metadata와 별도 workflow JSON offline ingest
2. raw workflow 보존과 normalization
3. ComfyUI API-format workflow import/export
4. 필요할 때만 custom node 또는 event hook 검토

ComfyUI 내부 DB나 폴더 layout에 직접 결합하지 않는다.

## 품질 도구

- Python: Ruff, Pyright, pytest
- TypeScript: ESLint, Prettier, Vitest
- End-to-end: Playwright
- DB integration: disposable PostgreSQL container
- Contract: JSON Schema fixtures와 OpenAPI breaking-change check
- Security: dependency audit, secret scan, subprocess argument test

CI는 GPU와 NAS 없이 실행돼야 한다. GPU/NAS smoke test는 DGX Agent의 명시적 수동/예약 검증 job으로 분리한다.

## 보류한 결정

- UI component library와 router
- thumbnail format/size matrix
- perceptual hash 알고리즘과 거리 threshold
- Postgres major version
- Agent polling interval과 backoff
- first production-ready training adapter
- ComfyUI custom node 필요 여부

각 항목은 관련 vertical slice에서 측정 가능한 spike와 ADR로 결정한다.
