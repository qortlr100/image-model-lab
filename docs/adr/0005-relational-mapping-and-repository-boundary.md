# ADR-0005: 관계형 매핑과 repository 경계

- 상태: accepted
- 날짜: 2026-07-29

## Context

[ADR-0002](0002-metadata-artifact-separation.md)는 PostgreSQL을 metadata source of truth로 정했지만 domain object를 어떤 방식으로 저장할지는 정하지 않았다. `packages/python/domain`의 entity는 frozen dataclass이고 framework를 import하지 않으며 전이는 새 값을 돌려준다. SQLAlchemy의 기본 사용 방식인 mutable identity map과 dirty tracking은 이 형태와 맞지 않는다.

M1-03에서 다음을 결정해야 했다.

- entity를 직접 mapping할 것인지, row class를 따로 둘 것인지
- `ArtifactReference`를 별도 table로 볼 것인지 column 묶음으로 볼 것인지
- transaction 경계를 누가 소유하는지
- domain 불변식을 DB 제약으로 어디까지 중복해서 표현할지

## Decision

**Row class와 명시적 변환.** entity마다 별도의 SQLAlchemy row class를 두고 `mapping.py`에서 양방향 변환을 명시한다. domain package는 SQLAlchemy를 import하지 않으며, 이는 `packages/python/domain/tests/test_domain_is_framework_free.py`의 allowlist import 검사로 강제한다.

**읽기는 entity 생성자를 통과한다.** row를 그대로 조립하지 않고 entity 생성자를 다시 거치므로, 불변식을 위반한 row는 읽는 시점에 거부된다. restore나 수동 수정으로 생긴 잘못된 row가 use case 한가운데로 들어오지 않는다.

**Repository는 aggregate 단위이고 commit하지 않는다.** port는 `packages/python/application/ports.py`에 `Protocol`로 두고, adapter는 주어진 session에 write하되 flush만 한다. transaction 경계는 composition root가 소유한다. 하나의 use case가 보통 여러 aggregate를 건드리므로 중간 commit은 어떤 규칙도 검증하지 않은 상태를 공개하게 된다.

**`ArtifactReference`는 column 묶음으로 embed한다.** manifest는 `manifest_logical_uri`, `manifest_sha256`, `manifest_size_bytes`, `manifest_media_type` 네 column으로 저장하고 `artifacts` table을 FK로 참조하지 않는다. entity가 artifact id가 아니라 value object를 들고 있고, publish가 아직 `pending`인 동안에도 manifest는 읽을 수 있어야 한다.

**상태는 CHECK가 붙은 text이며 PostgreSQL `ENUM` type을 쓰지 않는다.** 허용 값 목록과 column 폭은 domain 상수와 `StrEnum`에서 생성한다. 배포된 제약과 domain enum의 일치는 live database를 읽는 integration test가 검사하므로, 상태를 추가하면 migration을 쓸 때까지 test가 실패한다.

**끝난 기록은 repository가 다시 쓰지 않는다.** 완료된 `RunAttempt`, sealed/rejected `DatasetSnapshot`, 이미 기록된 artifact provenance는 update 경로에서 거부한다. guard는 `SELECT ... FOR UPDATE`로 읽은 저장된 row를 기준으로 판단한다.

**모든 schema 변경은 Alembic revision을 갖고 downgrade를 갖는다.** migration은 package 안에 있어 service image가 자기 schema를 올릴 수 있다. baseline은 `0001_baseline_schema.py`이며 upgrade/downgrade/재upgrade와 mapping 대조를 disposable database에서 검사한다.

## Consequences

- domain은 database 없이 읽고 test할 수 있으며, 그 성질이 실수로 사라지지 않는다.
- entity가 바뀌면 변환 코드도 함께 고쳐야 한다. 자동 mapping보다 코드가 많지만, column의 의미를 한 곳에서 읽을 수 있다.
- update는 aggregate 전체를 쓴다. 큰 collection을 가진 aggregate가 생기면 부분 write가 필요해질 수 있다.
- `artifacts.sha256`은 unique가 아니다. quarantine된 row가 digest를 유지하고 정상 사본은 새 artifact로 publish되기 때문이다. 주소인 `logical_uri`가 unique다.
- lease 기반 job claim에 필요한 `SKIP LOCKED` 조회, `JobLease`, `ExecutionAgent`, `RunEvent` table은 아직 없다. Phase 4에서 protocol과 함께 추가한다.
- integration test는 PostgreSQL server를 요구한다. `just test`는 server 없이도 성공하며 해당 test는 이유와 함께 skip되고, 전용 CI job이 실제로 실행한다.

## Alternatives

- **SQLAlchemy imperative mapping으로 entity를 직접 mapping**: entity가 mutable해지거나 mapper가 frozen dataclass를 우회해야 한다. 불변성과 전이 규칙이 저장 방식에 종속된다.
- **entity를 Pydantic model로 바꾸고 그대로 저장**: I/O 경계 밖으로 Pydantic을 확산시키며, `docs/03-technology-decisions.md`의 결정과 어긋난다.
- **PostgreSQL `ENUM` type**: 값 목록이 DDL로만 바뀌는 두 번째 장소에 생기고, transactional migration 안에서 값 추가가 까다롭다.
- **manifest를 `artifacts` FK로 참조**: publish가 `pending`이거나 row가 아직 없는 정상 상황에서 manifest를 저장할 수 없다.
- **Unit of Work 객체 도입**: 현재 use case가 없어 검증할 대상이 없다. session을 그대로 넘기는 편이 경계를 덜 숨긴다.
- **`metadata.create_all()`로 test schema 생성**: migration과 mapping이 어긋나도 test가 통과한다.

## Revisit triggers

- job lease 조회가 `SELECT ... FOR UPDATE SKIP LOCKED`와 partial index를 요구한다.
- 한 aggregate의 child collection이 커져 전체 rewrite가 비용이 된다.
- 여러 use case가 같은 transaction 조립 코드를 반복해 Unit of Work가 실제 중복 제거가 된다.
- async I/O가 필요해져 `AsyncSession`으로 옮긴다.
- S3 호환 artifact store가 추가되어 logical URI 해석 지점이 늘어난다.
