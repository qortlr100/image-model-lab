# ADR-0003: 외부 학습 엔진을 process adapter로 격리

- 상태: accepted
- 날짜: 2026-07-28

## Context

Anima 전용 도구와 `sd-scripts`는 Python, PyTorch, CUDA, flash-attention과 config/output 형식이 다르며 빠르게 변한다. 특히 `anima_lora`는 자체 `uv.lock`과 고정된 runtime 조합을 애플리케이션 환경으로 사용한다. 이를 shared library로 import하면 한 엔진의 dependency가 API, Worker와 다른 엔진을 제약한다.

## Decision

- training engine을 first-party Python dependency로 import하지 않는다.
- DGX Agent adapter가 pinned external checkout, release environment 또는 container를 subprocess로 실행한다.
- adapter는 validate, render, launch, observe, cancel, collect, finalize lifecycle을 구현한다.
- rendered input bundle, argv, redacted environment, engine revision과 lock digest를 artifact로 보존한다.
- engine raw output은 보존하고 progress/checkpoint/result는 versioned domain event로 정규화한다.
- `latest` 참조는 설치 편의에는 사용할 수 있어도 재현 가능한 run에는 사용할 수 없다.

## Consequences

- engine별 dependency와 update cadence를 격리할 수 있다.
- subprocess와 filesystem contract를 위한 더 강한 integration test가 필요하다.
- upstream log 형식 변경이 parser에 영향을 주지만 raw log로 복구할 수 있다.
- 공통 설정과 engine-specific 설정 사이의 손실 없는 mapping이 필요하다.

## Alternatives

- engine 코드를 vendor/fork: 통제력은 높지만 upstream 병합과 라이선스 유지 비용이 크다.
- shared Python virtualenv: 초기 설정은 단순하지만 dependency 충돌과 재현성 위험이 크다.
- shell script만 저장: 실행은 되지만 capability, validation, cancellation과 normalized provenance가 부족하다.

## Revisit triggers

- upstream이 안정된 library API와 semantic versioning을 제공한다.
- container runtime이 DGX Spark의 성능/driver 요구를 안정적으로 만족한다.
- adapter 공통 코드보다 각 엔진의 유지 비용이 훨씬 커진다.
