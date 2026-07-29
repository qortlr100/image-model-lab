# Architecture Decision Records

ADR은 여러 서비스, 장기 보존 데이터, 실행 protocol 또는 배포 계약에 영향을 주는 결정을 기록한다.

## 상태

- `proposed`: 검토 중
- `accepted`: 현재 구현 기준
- `superseded`: 새 ADR로 대체됨
- `rejected`: 검토했지만 채택하지 않음

## 목록

- [0001 — Control plane과 execution plane 분리](0001-control-execution-plane.md)
- [0002 — PostgreSQL metadata와 NAS artifact 분리](0002-metadata-artifact-separation.md)
- [0003 — 외부 학습 엔진을 process adapter로 격리](0003-training-engine-process-adapters.md)
- [0004 — Artifact reference 계약과 `nas://` key 문법](0004-artifact-reference-contract.md)

새 ADR은 context, decision, consequences, alternatives, revisit triggers를 포함한다.
