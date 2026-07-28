# ADR-0002: PostgreSQL metadata와 NAS artifact 분리

- 상태: accepted
- 날짜: 2026-07-28

## Context

이미지, 모델과 checkpoint는 크기가 크고 filesystem/GPU 도구가 직접 읽어야 한다. 반면 관계, revision, 승인, job state와 digest는 transaction과 검색이 필요하다. Git 또는 DB 한 곳에 모두 보관하면 각각 대용량 또는 일관성 문제를 만든다.

## Decision

- PostgreSQL을 metadata source of truth로 사용한다.
- NAS를 immutable artifact source of truth로 사용한다.
- DB에는 `nas://` logical URI, SHA-256, size, media type과 provenance를 저장한다.
- 실제 mount path는 배포 설정에서 namespace별로 해석한다.
- publish는 temporary write, hash verification, atomic rename, DB state transition으로 수행한다.
- sealed manifest와 완료 run manifest는 immutable artifact다.

## Consequences

- 서비스와 host별 mount path 차이를 숨길 수 있다.
- DB transaction과 filesystem operation 사이의 불일치를 reconciliation해야 한다.
- backup은 DB와 NAS를 함께 고려해야 하며 restore 후 integrity scan이 필요하다.
- S3 호환 저장소는 같은 port의 추가 adapter로 도입할 수 있다.

## Alternatives

- PostgreSQL large object: 대형 모델과 일반 ML tool 연동에 부적합하다.
- Git LFS: 빈번하고 큰 개인 실험 결과의 catalog/retention에 적합하지 않다.
- 처음부터 MinIO: 좋은 object semantics를 제공하지만 현재 NAS 위에 운영 요소를 추가한다.

## Revisit triggers

- 원자적 rename을 보장하지 않는 NAS backend를 사용한다.
- remote executor가 NAS를 직접 mount할 수 없다.
- signed URL, lifecycle policy 또는 object versioning 요구가 커진다.
