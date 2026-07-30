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

**모든 write는 caller가 읽은 state(`expected_state`)와 저장된 state가 같은지, 그리고 그 state가 쓰려는 state로 갈 수 있는지 함께 확인한다.** caller는 자신이 읽은 state를 기준으로 entity에게 다음 값을 물어보므로, 그 사이에 record가 움직였다면 그 답은 이미 지나간 state에 대한 것이다. `SELECT ... FOR UPDATE`만으로는 부족하다. 두 번째 writer는 lock을 기다린 뒤 새 row를 보고도 자신의 낡은 결정을 그 위에 쓰게 된다. 그래서 저장된 state와 들어온 state를 domain의 전이표(`ARTIFACT_TRANSITIONS` 등)에 대조하고, 지금 row가 그 state로 갈 수 없으면 거부한다. 검사 대상은 target이며 caller가 떠났다고 믿은 source는 아니다. 그 한계는 Consequences에 적어 두었다.

- 저장된 state가 종료 상태면 `RecordIsFinal`이다. 다시 읽어도 달라지지 않는다.
- 종료 상태가 아니지만 전이가 허용되지 않으면 `RecordChangedElsewhere`이다. 다시 읽고 다시 판단하면 성공할 수 있다.

lock을 잡은 read는 identity map을 갱신한다(`populate_existing`). 같은 session이 앞서 그 row를 읽었다면 `SELECT ... FOR UPDATE`만으로는 이미 load된 속성이 다시 채워지지 않으므로, guard가 database의 state가 아니라 caller가 이미 알고 있던 state를 검사하게 된다.

**insert는 savepoint 안에서 flush한다.** PostgreSQL은 statement 하나가 실패하면 transaction 전체를 abort하고 rollback 전까지 모든 statement를 거부한다. 따라서 savepoint 없이 `RecordAlreadyExists`를 올리면 "복구 가능한 조건"을 알려주면서 복구할 수단은 남기지 않는 셈이다. at-least-once 전달에서 중복 요청의 정상 처리는 "이미 queue된 job을 찾아 확인"이므로, 그 조회가 가능해야 한다. savepoint rollback은 실패한 insert만 되돌리고 composition root가 소유한 transaction과 use case가 앞서 써 둔 내용은 유지한다.

이것이 quarantine된 artifact가 새 provenance를 받지 않는 이유이고, 두 agent가 한 job에 서로 다른 outcome을 보고했을 때 결과가 write 순서로 정해지지 않는 이유이고, validating snapshot이 낡은 draft write로 다시 열리지 않는 이유다. 중복 보고인지 실제 충돌인지는 여전히 idempotency key를 아는 use case가 판단하며, 다만 그 판단을 다시 읽은 state 위에서 하게 된다.

또한 이미 기록된 artifact provenance는 append만 가능하고, 저장된 prefix가 바뀌면 `RecordHistoryRewritten`으로 거부한다.

전이표는 복사하지 않고 domain의 것을 그대로 참조한다. 어떤 state가 종료 상태가 되거나 허용되던 전이가 사라지면 이 guard가 자동으로 좁아진다.

**모든 schema 변경은 Alembic revision을 갖고 downgrade를 갖는다.** migration은 package 디렉터리 안에 두어 wheel에 포함되므로, 이 package를 설치하는 배포 단위가 자기 migration을 함께 가져간다. 현재 그런 배포 단위는 없다. API/Worker image는 `uv sync --package`로 해당 service의 dependency closure만 설치하고 어느 service도 persistence에 의존하지 않으므로, 지금 migration을 실행하는 경로는 저장소 workspace의 `just migrate`뿐이다. service가 시작 시점에 schema를 올리는 것은 API가 persistence를 실제로 사용하는 slice에서 image dependency와 함께 결정한다. baseline은 `0001_baseline_schema.py`이며 upgrade/downgrade/재upgrade와 mapping 대조를 disposable database에서 검사한다.

## Consequences

- domain은 database 없이 읽고 test할 수 있으며, 그 성질이 실수로 사라지지 않는다.
- entity가 바뀌면 변환 코드도 함께 고쳐야 한다. 자동 mapping보다 코드가 많지만, column의 의미를 한 곳에서 읽을 수 있다.
- update는 aggregate 전체를 쓴다. 큰 collection을 가진 aggregate가 생기면 부분 write가 필요해질 수 있다.
- `artifacts.sha256`은 unique가 아니다. quarantine된 row가 digest를 유지하고 정상 사본은 새 artifact로 publish되기 때문이다. 주소인 `logical_uri`가 unique다.
- **expected state는 "읽은 값이 아직 그 값인가"만 말할 수 있으므로, row가 그 값으로 돌아와 있는 낡은 write는 잡히지 않는다.** 두 경우가 여기에 해당하고 원인은 하나다.
  - *state가 아예 움직이지 않은 경우.* 두 caller가 같은 draft snapshot을 읽고 각각 item을 편집하면 둘 다 `draft`를 읽었으므로 expected state가 일치하고, 두 번째 write가 첫 번째가 commit한 편집을 덮어쓴다.
  - *cycle이 한 바퀴 돌아 같은 값으로 되돌아온 경우.* `queued → leased → running → queued`가 그렇다. 앞선 `queued`를 읽은 agent의 lease claim이 release 이후에도 통과한다. 자기 자신에게 도달할 수 있는 state가 이 성질을 가지며, artifact의 `available`·`missing`과 job의 `queued`·`leased`·`running`이 그렇다.

  두 경우 모두 state가 아니라 revision이 필요하다. 현재 port는 그것을 싣지 않으며, job lease claim에서 이 성질이 핵심이 되므로 Phase 4에서 optimistic concurrency와 함께 결정한다. 값이 달라진 낡은 write는 expected state가 잡는다. `pending`으로 읽고 검증한 artifact를 `missing`이 된 row에 쓰는 경우, 그리고 한 `queued` job을 두 agent가 동시에 claim해 두 번째가 `leased`를 만나는 경우가 그 예다.
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

- write가 expected source state 또는 revision을 싣게 한다. cycle이 있는 lifecycle의 낡은 write와 state를 유지하는 동시 편집이 모두 여기에 달려 있다. expected source state는 column이 필요 없고 revision은 필요하다. 어느 쪽이든 `image_model_lab_application.ports`의 contract 변경이다.
- job lease 조회가 `SELECT ... FOR UPDATE SKIP LOCKED`와 partial index를 요구한다.
- 한 aggregate의 child collection이 커져 전체 rewrite가 비용이 된다.
- 여러 use case가 같은 transaction 조립 코드를 반복해 Unit of Work가 실제 중복 제거가 된다.
- async I/O가 필요해져 `AsyncSession`으로 옮긴다.
- S3 호환 artifact store가 추가되어 logical URI 해석 지점이 늘어난다.
