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

현재 네 service skeleton과 `packages/python/domain`, `packages/typescript/api-client`가 workspace와 품질 도구를 검증하는 최소 단위로 구현되어 있습니다. 나머지 구조는 해당 vertical slice에서 생성하며, 빈 디렉터리를 보존하기 위한 placeholder는 추가하지 않습니다.

## 라이선스 주의

저장소 코드의 라이선스와 외부 모델·학습 엔진·생성물의 라이선스는 별개입니다. 특히 Anima 기반 파생 모델의 사용 조건은 [CircleStone Labs Anima 모델 카드와 라이선스](https://huggingface.co/circlestone-labs/Anima)를 각 학습 실행 시점의 정확한 revision 기준으로 기록해야 합니다.
