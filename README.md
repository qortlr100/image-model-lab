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

현재 네 service skeleton과 `packages/python/domain`, `packages/typescript/api-client`가 구현되어 있고, `tools/`에는 저장소 정책과 contract drift 검사가 있습니다. `contracts/`에는 첫 durable schema인 artifact reference와 그 fixture가 있습니다. 나머지 구조는 해당 vertical slice에서 생성하며, 빈 디렉터리를 보존하기 위한 placeholder는 추가하지 않습니다.

## Artifact 참조

`packages/python/domain`의 `ArtifactUri`, `Sha256Digest`, `MediaType`, `ArtifactReference`는 저장된 artifact를 가리키는 유일한 방법입니다. 주소는 `nas://<namespace>/<key>`이며 machine mount path, 경로 traversal, percent-encoding, 대문자 key는 value object 단계에서 거부됩니다. 직렬화 형태는 `schema_version`을 포함하고 [`contracts/schemas/artifact-reference-v1.schema.json`](contracts/schemas/artifact-reference-v1.schema.json)에 published schema로 있습니다. 규칙과 근거는 [ADR-0004](docs/adr/0004-artifact-reference-contract.md)를 참고하세요.

## 라이선스 주의

저장소 코드의 라이선스와 외부 모델·학습 엔진·생성물의 라이선스는 별개입니다. 특히 Anima 기반 파생 모델의 사용 조건은 [CircleStone Labs Anima 모델 카드와 라이선스](https://huggingface.co/circlestone-labs/Anima)를 각 학습 실행 시점의 정확한 revision 기준으로 기록해야 합니다.
