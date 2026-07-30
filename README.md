# image-model-lab

개인 이미지 생성 모델 작업을 한곳에서 추적하는 모노레포입니다. 데이터셋 준비, LoRA 학습, ComfyUI 생성 결과와 평가를 하나의 재현 가능한 흐름으로 연결하는 것이 목표입니다.

현재 저장소는 **기반 구현 단계**입니다. 네 배포 단위의 최소 service skeleton만 실행 가능하며, 제품 기능은 아직 구현되지 않았습니다. 구현 범위와 경계는 [`docs/00-scope.md`](docs/00-scope.md), 전체 구조는 [`docs/01-architecture.md`](docs/01-architecture.md)를 기준으로 합니다.

## 목표

- 이미지 수집, 분류, 중복 후보 탐지, WD/JoyCaption 캡셔닝과 검수
- 승인된 캡션과 원본 해시를 고정한 불변 데이터셋 스냅샷
- DGX Spark에서 Anima LoRA 학습 실행 및 엔진 교체가 가능한 어댑터
- 설정, 로그, 체크포인트, 결과 이미지, ComfyUI workflow와 생성 설정의 추적
- 체크포인트 비교, 평가, 생성 결과의 데이터셋 후보 재등록

## 배포 경계

- 이 저장소: 애플리케이션 코드, 서비스별 이미지 빌드 정의, 스키마, 마이그레이션, 개발용 실행 구성
- `qortlr100/homeserver`: 홈서버 및 DGX Spark의 실제 배포 설정과 비밀값 연결
- NAS: 이미지, 모델, 로그, 체크포인트, 생성 결과 등 대용량 아티팩트
- Git: 코드와 작은 텍스트 매니페스트만 저장

## 문서

- [범위와 비범위](docs/00-scope.md)
- [시스템 아키텍처와 데이터 흐름](docs/01-architecture.md)
- [핵심 도메인 모델](docs/02-domain-model.md)
- [기술 스택 결정](docs/03-technology-decisions.md)
- [단계별 구현 로드맵](docs/04-roadmap.md)
- [다음 구현 작업](docs/05-next-work-items.md)
- [아키텍처 결정 기록](docs/adr/README.md)

## 개발 환경

필수 도구:

- Python 3.13과 `uv`
- Node.js 24와 Corepack
- `just`

고정된 lockfile만 사용해 의존성을 설치하고 전체 검사를 실행합니다.

```bash
just check
```

개별 공통 명령은 `just format`, `just lint`, `just typecheck`, `just test`, `just build`입니다. `just check`는 먼저 `uv sync --frozen --all-packages`와 `pnpm install --frozen-lockfile`을 실행하므로, clean checkout에서도 별도 bootstrap 명령이 필요하지 않습니다.

## 검증과 저장소 정책

`just check`는 저장소 정책, lockfile, 생성 contract drift, format, lint, typecheck, test, build를 순서대로 실행합니다. GitHub Actions의 `CI` workflow가 같은 명령을 CPU runner에서 실행하고, 네 service image build와 API/Worker image에 training engine dependency가 없다는 확인을 별도 job으로 수행합니다. GPU와 NAS가 필요한 검증은 CI에 넣지 않습니다.

저장소 정책 검사(`tools/repo_policy.py`)는 다음을 거부합니다.

- 모델 가중치와 checkpoint 확장자(`.safetensors`, `.ckpt`, `.pt`, `.onnx`, `.gguf` 등)
- `docs/` 밖의 이미지와 모든 동영상 파일
- 1 MiB를 넘는 추적 파일
- `.pem`, `.key` 같은 키 자료와 `.env.example`이 아닌 환경 파일
- 커밋된 것으로 보이는 token, 비밀번호, private key block

의도적으로 남겨야 하는 한 줄에는 `repo-policy: allow-secret` 표시를 붙입니다. commit 시점에 같은 검사를 실행하려면 hook을 설치합니다.

```bash
just install-hooks   # git config core.hooksPath tools/hooks
just policy          # 추적 파일 전체 검사
just contract-check  # 생성 contract와 재생성 결과 비교
```

생성 contract drift 검사는 현재 `tools/contract_drift.py`의 registry가 비어 있어 확인할 대상이 없다고 보고합니다. M1-04에서 OpenAPI export와 TypeScript client 생성기를 registry에 등록하면 같은 명령이 commit된 파일과 재생성 결과를 비교합니다.

## Service skeleton

개발용 최소 실행 명령은 다음과 같습니다. Worker와 DGX Agent의 `run`은 process와 종료 처리만 검증하는 idle loop이며 아직 job을 claim하지 않습니다.

```bash
corepack pnpm --filter @image-model-lab/web dev
uv run image-model-lab-api
uv run image-model-lab-worker run
uv run image-model-lab-dgx-agent run
```

상태와 버전은 Web의 `/health.json`, `/version.json`, API의 `/health`, `/version`, 그리고 두 background service의 `health`, `version` subcommand로 확인합니다.

각 image는 저장소 root를 build context로 사용합니다.

```bash
docker build -f apps/web/Dockerfile .
docker build -f services/api/Dockerfile .
docker build -f services/worker/Dockerfile .
docker build -f services/dgx-agent/Dockerfile .
```

## 모노레포 구조

```text
apps/
  web/
services/
  api/
  worker/
  dgx-agent/
packages/
  python/
    domain/
    application/
    persistence/
    artifact-store/
  typescript/
    api-client/
contracts/
  schemas/
  examples/
ops/
  dev/
tools/
docs/
```

현재 네 service skeleton과 `packages/python/domain`, `packages/python/application`, `packages/python/persistence`, `packages/typescript/api-client`가 구현되어 있고, `tools/`에는 저장소 정책과 contract drift 검사가 있습니다. `contracts/`에는 첫 durable schema인 artifact reference와 그 fixture가, `ops/dev/`에는 개발용 PostgreSQL compose 파일이 있습니다. 나머지 구조는 해당 vertical slice에서 생성하며, 빈 디렉터리를 보존하기 위한 placeholder는 추가하지 않습니다.

## Artifact 참조

`packages/python/domain`의 `ArtifactUri`, `Sha256Digest`, `MediaType`, `ArtifactReference`는 저장된 artifact를 가리키는 유일한 방법입니다. 주소는 `nas://<namespace>/<key>`이며 machine mount path, 경로 traversal, percent-encoding, 대문자 key는 value object 단계에서 거부됩니다. 직렬화 형태는 `schema_version`을 포함하고 [`contracts/schemas/artifact-reference-v1.schema.json`](contracts/schemas/artifact-reference-v1.schema.json)에 published schema로 있습니다. 규칙과 근거는 [ADR-0004](docs/adr/0004-artifact-reference-contract.md)를 참고하세요.

## 도메인 생명주기

`packages/python/domain`은 `Artifact`, `ExecutionJob`, `RunAttempt`, `DatasetSnapshot`의 상태 전이를 framework 없이 강제합니다. entity는 불변이고 전이는 새 값을 돌려주므로, 이전 값을 들고 있는 호출자는 자신이 확인한 상태를 계속 읽습니다. 허용되지 않은 전이와 불변식 위반은 `DomainError` 하위 예외로 거부됩니다.

- 완료된 `RunAttempt`와 sealed `DatasetSnapshot`은 다시 열리지 않습니다. 재시도는 다음 attempt, 수정은 새 snapshot입니다.
- lease를 잃은 job은 `queued`로 돌아가고, 완료 보고가 중복 도착하면 전이가 거부됩니다. 중복인지 충돌인지는 idempotency key를 아는 use case가 판단합니다.
- 모든 `Artifact`는 provenance를 최소 한 건 가집니다. 나중에 복원할 수 없는 정보이므로 생성 시점에 기록하고, 같은 bytes가 다른 출처로 다시 들어오면 append만 합니다. machine mount path는 출처 label이 될 수 없습니다.
- 각 entity의 전이표는 `ARTIFACT_TRANSITIONS`처럼 공개돼 있어, test가 상태 몇 개가 아니라 표 전체와 표 밖의 모든 전이를 검사합니다.

전이 규칙과 근거는 [핵심 도메인 모델](docs/02-domain-model.md)의 생명주기 절에 있습니다.

## 메타데이터 저장

`packages/python/application`은 use case가 저장소에 요구하는 것을 `Protocol` port로 선언하고, `packages/python/persistence`가 PostgreSQL adapter로 구현합니다. SQLAlchemy와 Alembic은 이 package와 service composition root 밖에 나타나지 않으며, domain package가 framework를 import하지 않는다는 사실은 allowlist 기반 import 검사가 강제합니다.

- 생명주기를 가진 네 entity(`Artifact`, `ExecutionJob`, `RunAttempt`, `DatasetSnapshot`)와 순서를 가진 두 child table(artifact provenance, snapshot item)이 mapping되어 있습니다.
- domain entity는 그대로 mapping되지 않고 별도 row class와 명시적 변환을 거칩니다. 읽기는 entity 생성자를 다시 통과하므로 불변식을 어긴 row는 읽는 시점에 거부됩니다.
- repository는 aggregate 단위로 write하고 commit하지 않습니다. transaction 경계는 composition root가 소유합니다.
- 모든 write는 저장된 state가 그 write를 허용하는지 domain 전이표에 대조합니다. `FOR UPDATE`만으로는 낡은 결정이 새 row 위에 쓰이는 것을 막지 못하므로, record가 이미 떠난 state로 되돌리는 write는 `RecordIsFinal`(종료 상태) 또는 `RecordChangedElsewhere`(다시 읽으면 성공 가능)로 거부됩니다. lock을 잡은 read는 identity map을 갱신해 caller가 이미 알던 state가 아니라 database의 state를 검사합니다.
- 완료된 `RunAttempt`, sealed/rejected `DatasetSnapshot`, quarantine된 `Artifact`, 이미 기록된 provenance는 그래서 덮어써지지 않습니다.
- insert는 savepoint 안에서 실행되므로 `RecordAlreadyExists`를 받은 caller가 같은 transaction에서 기존 record를 조회해 중복을 확인할 수 있습니다. state를 유지하는 동시 편집(예: 같은 draft snapshot의 item)은 아직 감지되지 않습니다 — [ADR-0005](docs/adr/0005-relational-mapping-and-repository-boundary.md)의 Consequences를 참고하세요.
- 상태 column의 허용 값과 column 폭은 domain 상수에서 생성되고, 배포된 CHECK 제약이 domain enum과 일치하는지는 live database를 읽는 test가 검사합니다.

근거와 대안은 [ADR-0005](docs/adr/0005-relational-mapping-and-repository-boundary.md)에 있습니다.

### 개발용 데이터베이스와 마이그레이션

```bash
just db-up                                   # ops/dev/compose.yaml의 PostgreSQL 기동
export IMAGE_MODEL_LAB_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/image_model_lab
just migrate upgrade head
just migrate downgrade base
just db-down
```

`IMAGE_MODEL_LAB_DATABASE_URL`은 모든 service와 migration runner가 읽는 유일한 설정 지점이며, PostgreSQL 이외의 backend는 거부됩니다. Alembic 설정과 revision은 package 안에 있으므로 service image가 자신의 schema를 올릴 수 있습니다.

### Persistence integration test

repository와 migration test는 database를 만들고 지울 수 있는 PostgreSQL server를 요구합니다. server 위치는 `IMAGE_MODEL_LAB_TEST_DATABASE_URL`로 전달하며, 각 test 실행은 고유한 이름의 database를 만들고 끝나면 지웁니다.

```bash
just db-up
IMAGE_MODEL_LAB_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres \
  uv run pytest packages/python/persistence
```

변수가 없으면 해당 test는 이유와 함께 skip되므로 `just check`는 database 없이도 성공합니다. CI는 PostgreSQL service container를 붙인 별도 job에서 실제로 실행하고, 그 job은 `IMAGE_MODEL_LAB_REQUIRE_DATABASE=1`을 설정해 skip을 실패로 취급합니다.

## 라이선스 주의

저장소 코드의 라이선스와 외부 모델·학습 엔진·생성물의 라이선스는 별개입니다. 특히 Anima 기반 파생 모델의 사용 조건은 [CircleStone Labs Anima 모델 카드와 라이선스](https://huggingface.co/circlestone-labs/Anima)를 각 학습 실행 시점의 정확한 revision 기준으로 기록해야 합니다.
