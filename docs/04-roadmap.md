# 단계별 구현 로드맵

각 단계는 이전 단계의 artifact와 contract를 사용하지만, 큰 일괄 구현 대신 독립적으로 검증 가능한 vertical slice로 나눈다.

## Phase 0 — 저장소 기반과 호환성 검증

목표: 개발 환경과 외부 engine 선택의 불확실성을 먼저 줄인다.

- pnpm/uv workspace, root task, lint/test/typecheck, CI
- Web/API/Worker/DGX Agent 최소 health/version endpoint
- PostgreSQL local dev 구성과 첫 migration
- versioned contract fixture와 artifact URI package
- DGX Spark에서 `anima_lora`와 `sd-scripts` clean-install matrix
- 각 후보의 100-step smoke run, output key와 ComfyUI load 확인

완료 기준:

- clean checkout에서 GPU 없이 repository-wide check가 성공한다.
- 각 service가 독립 image로 build된다.
- engine POC 결과와 production-ready 후보 결정 ADR이 있다.

## Phase 1 — Asset catalog와 ingest

목표: 원본을 안전하게 등록하고 중복 후보를 검수한다.

- inbox 기반 ingest request
- SHA-256, media metadata, thumbnail, perceptual hash
- exact duplicate deduplication과 provenance 추가
- similar duplicate candidate 목록과 판단 UI
- logical artifact URI와 pending/available reconciliation

완료 기준:

- 같은 파일을 반복 ingest해도 blob과 logical asset가 불필요하게 증가하지 않는다.
- 유사 이미지는 자동 삭제 없이 검수 후보로만 표시된다.
- 실패한 NAS publish를 재조정할 수 있다.

## Phase 2 — Captioning과 사람 검수

목표: 자동 결과와 승인본을 분리해 caption provenance를 보존한다.

- caption adapter contract
- WD adapter와 threshold 설정
- JoyCaption adapter와 prompt template revision
- batch job, raw output, normalized proposal
- 편집, diff, approve/reject, bulk review

완료 기준:

- caption 한 줄에서 model revision, template, decoding 설정과 원문까지 추적된다.
- 편집이 기존 자동 결과를 덮어쓰지 않는다.
- engine이 없어도 fixture 기반 adapter contract test가 동작한다.

## Phase 3 — 재현 가능한 dataset snapshot

목표: 학습에 전달되는 정확한 입력 집합을 봉인한다.

- dataset과 draft snapshot builder
- validation rule: missing caption, duplicate, license note, broken artifact
- canonical manifest와 digest
- engine-neutral export bundle
- snapshot compare와 lineage

완료 기준:

- 동일 입력은 동일 digest를 만든다.
- sealed snapshot은 변경할 수 없다.
- NAS의 export bundle만으로 asset/caption pairing을 재구성할 수 있다.

## Phase 4 — Job protocol과 DGX Agent

목표: 홈서버와 DGX를 안전한 장시간 실행 경계로 연결한다.

- Agent registration, capabilities, heartbeat
- compatible job lease, expiry, retry, cancellation
- subprocess sandbox, redaction, structured events
- local scratch materialization과 atomic publish
- interrupted attempt recovery
- aggregate optimistic concurrency: version column과 expected revision을 싣는 repository port

완료 기준:

- Agent 강제 종료 후 lease가 회수되고 새 attempt가 실행된다.
- 중복 완료 보고가 결과를 두 번 current로 만들지 않는다.
- API와 Agent가 서로 다른 release version일 때 protocol version 오류가 명확하다.
- state를 유지하는 동시 편집이 조용히 덮어써지지 않는다. M1-03의 write guard는 domain 전이표를 대조하므로 `draft → draft`처럼 state가 그대로인 변경은 잡지 못하며, 근거와 범위는 [ADR-0005](adr/0005-relational-mapping-and-repository-boundary.md)에 있다.

## Phase 5 — Anima LoRA training 관리

목표: 검증된 engine adapter로 학습 전체 provenance를 기록한다.

- TrainingRecipe와 revision UI/API
- Phase 0에서 선택한 첫 engine adapter
- snapshot export → training → checkpoint registration
- logs/metrics viewer
- result manifest와 model catalog 등록
- 두 번째 adapter parity spike

완료 기준:

- 한 training run에서 snapshot, recipe, base model, engine revision, environment와 모든 checkpoint를 추적한다.
- 동일 checkpoint 파일을 중복 등록하지 않는다.
- 실패/취소 attempt의 partial outputs가 성공 결과와 혼동되지 않는다.

## Phase 6 — ComfyUI 결과와 비교 평가

목표: 생성 provenance와 학습 checkpoint를 연결한다.

- PNG/workflow JSON ingest
- workflow raw 보존, normalization, model reference resolution
- generation setting extraction과 unresolved reference queue
- comparison set, declared variable axes, grid view
- rubric과 평가 revision

완료 기준:

- no-LoRA/LoRA, trigger 유무, strength, checkpoint 비교를 명시적 축으로 구성한다.
- 모델 파일명이 같아도 digest가 다르면 별도 revision으로 취급한다.
- 알 수 없는 custom node가 있어도 raw workflow와 output ingest는 성공한다.

## Phase 7 — 데이터셋 피드백과 운영 강화

목표: 평가된 결과를 통제된 방식으로 다음 dataset에 반영한다.

- generation output → dataset candidate
- review, source labeling, accepted collection
- backup/restore drill과 artifact integrity scan
- retention/GC dry-run
- metrics, alert, audit export

완료 기준:

- 생성물이 어느 모델의 파생 결과인지 lineage가 유지된다.
- 사람 승인 없이 snapshot에 들어가지 않는다.
- DB restore 후 NAS artifact reconciliation을 수행할 수 있다.

## Phase 간 우선순위

Phase 0의 engine POC는 조기에 수행하되, 전체 학습 UI 구현은 Phase 3 snapshot과 Phase 4 execution protocol 이후로 미룬다. 재현 가능한 입력과 실행 경계 없이 학습 버튼부터 만들면 기존 수동 폴더 작업을 UI로 옮기는 데 그치기 때문이다.

## 로드맵에서 제외된 운영 작업

프로덕션 reverse proxy, volume mount, secret injection, backup schedule, service restart policy는 이 저장소의 service interface가 안정된 뒤 `qortlr100/homeserver`에서 별도 진행한다. 이 저장소는 필요한 환경 변수와 volume contract까지만 문서화한다.
