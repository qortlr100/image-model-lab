# 핵심 도메인 모델

## 모델링 원칙

- DB row보다 먼저 불변식과 생명주기를 정의한다.
- 파일과 실행 결과는 수정 대신 revision/attempt를 추가한다.
- engine 고유 설정을 잃지 않되 공통 검색 필드는 별도로 정규화한다.
- 모든 중요한 관계는 이름이나 경로가 아니라 stable ID와 artifact digest로 확정한다.

## 데이터셋 영역

| 모델 | 역할 | 핵심 필드 |
|---|---|---|
| `Asset` | 논리적 이미지 정체성 | id, kind, current revision, created_at |
| `AssetRevision` | 불변 파일 revision | artifact_id, sha256, dimensions, perceptual_hash, provenance |
| `Collection` | 작업용 분류 묶음 | name, purpose, lifecycle state |
| `CollectionItem` | collection과 asset 관계 | collection_id, asset_revision_id, labels, position |
| `DuplicateCandidate` | 유사 또는 동일 후보 | left/right revision, algorithm, score, decision |
| `CaptionRun` | caption engine 실행 | adapter, model revision, config digest, status |
| `CaptionRevision` | 자동/수동 caption 한 버전 | asset revision, raw text, normalized form, parent, author kind |
| `CaptionReview` | 승인 판단 | caption revision, decision, reason, reviewed_at |
| `Dataset` | 지속되는 데이터셋 정체성 | name, intended use, license notes |
| `DatasetSnapshot` | 봉인된 학습 입력 | dataset, schema version, manifest artifact, digest, sealed_at |
| `SnapshotItem` | snapshot의 정확한 항목 | asset revision, caption revision, order, repeat/weight |

### 불변식

- `AssetRevision.sha256`는 저장된 bytes와 일치해야 한다.
- `DuplicateCandidate`는 원본을 삭제하지 않는다.
- snapshot item은 승인된 caption revision만 참조한다. 예외는 명시적인 override reason이 필요하다.
- sealed snapshot은 item 추가, 삭제, 순서 변경이 불가능하다.
- 같은 canonical manifest는 같은 digest를 만든다.

## 실행과 artifact 영역

| 모델 | 역할 | 핵심 필드 |
|---|---|---|
| `Artifact` | NAS의 불변 객체 | logical_uri, sha256, size_bytes, media_type, state, provenance |
| `Model` | base model 또는 adapter의 논리 정체성 | kind, name, provider, license reference |
| `ModelRevision` | 실제 가중치 revision | model, artifact, upstream revision, format |
| `ExecutionJob` | 예약 가능한 명령 | kind, requirements, priority, idempotency key, state |
| `JobLease` | Agent의 제한 시간 소유권 | job, agent, attempt, expires_at, heartbeat_at |
| `ExecutionAgent` | 실행 노드 | node ID, capabilities, adapter versions, last_seen |
| `RunAttempt` | 한 번의 실제 실행 | job, agent, started/ended, outcome, input/output manifest |
| `RunEvent` | 정규화된 진행 이벤트 | attempt, sequence, type, timestamp, payload version |

`Artifact.state`는 최소 `pending`, `available`, `quarantined`, `missing`을 가진다. DB에서 참조가 사라져도 즉시 물리 삭제하지 않고 별도의 garbage collection 정책을 따른다.

`logical_uri`, `sha256`, `size_bytes`, `media_type` 네 값은 `Artifact`뿐 아니라 manifest와 API 응답에서 함께 움직이므로 `ArtifactReference` value object와 versioned schema로 고정한다. URI 문법, digest 정규형, 직렬화 규칙은 [ADR-0004](adr/0004-artifact-reference-contract.md)에 있다.

## 학습 영역

| 모델 | 역할 | 핵심 필드 |
|---|---|---|
| `TrainingRecipe` | 재사용 가능한 학습 의도 | name, target family, description |
| `TrainingRecipeRevision` | 불변 설정 revision | common config, engine config, config digest |
| `TrainingRun` | snapshot과 recipe의 실행 | snapshot, recipe revision, base model revision, job |
| `EngineBinding` | adapter와 외부 engine 고정 | adapter ID/version, engine source ref, environment digest |
| `Checkpoint` | run 중간/최종 가중치 | training run, attempt, step/epoch, artifact, metrics |
| `TrainingMetric` | 시계열 지표 | run attempt, name, step, value, recorded_at |

### 공통 학습 설정

초기 공통 필드는 target model family, resolution policy, batch/accumulation, precision, seed, max steps/epochs, learning rate, optimizer, network rank/alpha, checkpoint policy다. 엔진에서 표현이 다르거나 공통화가 손실을 만드는 값은 `engine_config`에 schema-versioned raw form으로 둔다.

### Training adapter contract

```text
descriptor() -> capabilities and config schema
validate(context, recipe) -> diagnostics
render_input(context, recipe) -> immutable bundle
launch(bundle, runtime) -> process handle
observe(process) -> normalized events
cancel(process) -> cancellation result
collect(process, output_dir) -> artifact candidates
finalize(candidates) -> run manifest
```

Adapter는 engine 내부 Python 객체에 의존하지 않는다. 외부 checkout/container의 pinned CLI를 호출하고 argv, environment allowlist, source revision과 lock digest를 기록한다.

## 생성과 평가 영역

| 모델 | 역할 | 핵심 필드 |
|---|---|---|
| `Workflow` | ComfyUI graph의 논리 정체성 | name, purpose |
| `WorkflowRevision` | raw workflow 한 버전 | artifact, raw digest, normalized fingerprint, schema version |
| `GenerationRun` | 한 prompt/workflow 실행 | workflow revision, prompt, seed, normalized settings |
| `GenerationModelUse` | 생성에 사용된 모델 | generation run, model revision/checkpoint, role, strength |
| `GenerationOutput` | 생성된 이미지 | generation run, artifact, batch index, embedded metadata |
| `ComparisonSet` | 공정 비교 묶음 | name, baseline, declared variable axes |
| `ComparisonMember` | 비교 대상 | set, generation output, axis values |
| `EvaluationRevision` | 사람의 평가 | subject, rubric version, scores, notes, supersedes |
| `DatasetCandidate` | 생성 결과의 재등록 제안 | output, target dataset, reason, review state |

### 정규화 우선순위

1. artifact digest로 model/checkpoint를 확정한다.
2. digest가 없으면 canonical path mapping과 catalog alias를 사용한다.
3. 파일명만 일치하면 `unresolved` 후보이며 확정 관계로 저장하지 않는다.
4. ComfyUI node가 알 수 없는 custom schema여도 raw workflow ingest는 성공해야 한다.

## 주요 생명주기

### Caption

`generated → edited → approved/rejected → superseded`

자동 출력은 승인과 동일하지 않다. 승인된 revision을 편집하면 기존 승인을 변경하지 않고 새 revision이 `edited`로 시작한다.

### Dataset snapshot

`draft → validating → sealed` 또는 `draft/validating → rejected`

`sealed`에서 되돌아가지 않는다. 오류 수정은 새 snapshot을 만든다.

### Training run

`draft → queued → running → succeeded/failed/cancelled`

재시도는 같은 `TrainingRun` 아래 새 `RunAttempt`를 만들 수 있다. 단, recipe나 snapshot이 바뀌면 새 `TrainingRun`이다.

### Dataset candidate

`proposed → accepted/rejected`

accepted는 collection에 revision을 추가하는 행위이며 sealed snapshot을 수정하지 않는다.

## Manifest 최소 요건

### Dataset snapshot manifest

- schema version, snapshot ID, created/sealed timestamps
- ordered items: asset ID/revision/digest, caption ID/revision/text digest
- transform/export rules, repeats/weights
- source/license notes
- canonicalization algorithm과 전체 manifest digest

### Training run manifest

- snapshot manifest digest
- recipe revision and config digest
- base model artifact digest and license reference
- adapter ID/version, engine source ref, environment/lock digest
- rendered argv와 redacted environment
- random seed, host capability snapshot
- attempt timeline, checkpoint/output artifact digests

### Generation run manifest

- raw workflow digest and normalized fingerprint
- prompt/negative prompt
- model/checkpoint/LoRA artifact digests and strengths
- seed, sampler, scheduler, steps, CFG, dimensions
- ComfyUI version/custom node inventory when available
- output artifact digests
