# ADR-0001: Control plane과 execution plane 분리

- 상태: accepted
- 날짜: 2026-07-28

## Context

Web/API/Worker는 홈서버에서 상시 동작해야 하고, 학습과 일부 캡셔닝은 DGX Spark의 GPU, CUDA와 무거운 model environment가 필요하다. 하나의 process 또는 배포 단위로 합치면 홈서버 서비스가 GPU dependency와 장시간 실행 실패에 결합된다.

## Decision

- Web/API/Worker를 홈서버 control plane으로 둔다.
- DGX Agent를 독립 execution plane service로 둔다.
- Agent는 API를 통해 capability를 등록하고 job을 lease한다.
- Agent가 DB에 직접 접속하지 않는다.
- 대용량 입력과 결과는 logical URI로 NAS를 통해 교환한다.
- 서비스 build 정의는 이 저장소에, 실제 배포 연결은 `qortlr100/homeserver`에 둔다.

## Consequences

- GPU environment 변경이 API 가용성에 영향을 주지 않는다.
- 네트워크 단절, lease 만료, retry와 idempotency가 필수 설계 요소가 된다.
- control plane과 Agent 사이에 versioned protocol이 필요하다.
- NAS의 shared access와 권한 구성이 운영 선행 조건이다.

## Alternatives

- API가 SSH로 DGX command 실행: 단순하지만 상태, 취소, 보안과 복구가 취약하다.
- Agent가 PostgreSQL을 직접 polling: 구현은 짧지만 DB credential과 schema coupling이 DGX로 확산된다.
- Kubernetes: 현재 개인 규모와 두 host 구성에 비해 운영 비용이 크다.

## Revisit triggers

- 여러 DGX 또는 cloud executor가 추가돼 scheduling 요구가 크게 증가한다.
- NAS shared mount가 성능 또는 보안 병목이 된다.
- API polling latency가 실제 작업에 문제를 만든다.
