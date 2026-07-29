# ADR-0004: Artifact reference 계약과 `nas://` key 문법

- 상태: accepted
- 날짜: 2026-07-29

## Context

ADR-0002는 metadata를 PostgreSQL에, artifact를 NAS에 두고 DB에는 `nas://` logical URI와 SHA-256, size, media type을 저장하기로 정했다. 정확한 문법과 직렬화 형태는 정하지 않았다.

이 값은 DB row와 sealed snapshot manifest, run manifest에 함께 들어가 코드보다 오래 남는다. 나중에 문법을 넓히는 것은 하위 호환이지만 좁히는 것은 이미 저장된 값을 무효로 만든다. 또한 key는 API, Worker, DGX Agent가 각자의 mount root와 결합해 실제 경로로 만들기 때문에 traversal과 case 충돌은 서비스 하나의 문제가 아니다. SMB나 macOS처럼 case-insensitive한 backend에서는 대소문자만 다른 두 URI가 같은 파일을 가리킬 수 있다.

## Decision

- artifact 참조의 최소 단위는 `logical_uri`, `sha256`, `size_bytes`, `media_type` 네 값이며 `schema_version`과 함께 직렬화한다. 현재 형태는 `contracts/schemas/artifact-reference-v1.schema.json`에 published schema로 둔다.
- logical URI는 `nas://<namespace>/<key>`만 허용한다. scheme은 소문자 `nas`이며 host, port, query, fragment를 쓰지 않는다.
- namespace는 고정 집합(`assets`, `datasets`, `models`, `runs`, `workflows`)이다. namespace 추가는 코드 변경이자 배포 설정 변경이다.
- key segment는 `[a-z0-9][a-z0-9._-]*`이고 segment당 255자, key 전체 1024자를 넘지 않는다.
- 다음은 거부한다: `.`과 `..` segment, 빈 segment, 절대 경로, backslash, percent-encoding, 후행 `/`, 대문자.
- digest는 소문자 hex 64자로 저장한다. reader는 `sha256:` prefix와 대문자 표기를 받아들이지만 writer는 항상 정규형만 쓴다.
- media type은 parameter와 wildcard 없는 소문자 `<type>/<subtype>`이다.
- reader는 지원하지 않는 `schema_version`과 알 수 없는 field를 거부한다. migration 중에는 현재 version과 직전 version을 함께 지원한다.

## Consequences

- machine mount path는 domain object가 될 수 없다. value object를 거치지 않고 참조를 만들 방법이 없으므로 DB와 manifest에 host 경로가 들어가지 않는다.
- percent-encoding을 금지했으므로 storage adapter는 decode 단계 없이 key를 mount root에 결합한다. adapter는 여전히 결합 결과가 root 하위인지 확인한다.
- ingest는 원본 파일명을 key로 쓰지 못하고 SHA-256이나 UUID 같은 생성 식별자로 매핑해야 한다. 원본 이름은 metadata로 보존한다.
- 문법을 넓히는 변경은 기존 값을 그대로 두지만, 좁히는 변경은 새 schema version과 migration을 요구한다.
- schema, fixture, domain code가 같은 fixture로 함께 검증되므로 셋 중 하나만 바뀌면 test가 실패한다.

## Alternatives

- RFC 3986 전체 문법과 percent-encoding 허용: decode 이후에야 `%2e%2e`가 traversal이 되므로 검증 지점이 서비스마다 흩어진다.
- 원본 파일명을 유지하는 자유 형식 key: 사람이 읽기 좋지만 case-insensitive backend에서 충돌하고 공백·비ASCII·shell 특수문자 처리를 모든 adapter가 반복해야 한다.
- mount 상대 경로 저장: ADR-0002가 이미 거부했다. host별 mount 차이가 데이터에 남는다.
- version 없는 참조 object: manifest가 코드보다 오래 남는다는 전제와 맞지 않는다.

## Revisit triggers

- artifact key가 사람이 읽는 이름이나 비ASCII 문자를 담아야 한다.
- 특정 namespace가 다른 주소 체계를 요구한다. 예를 들어 S3 호환 adapter가 자체 key 규칙을 강제한다.
- SHA-256 외의 digest algorithm이 필요해진다.
