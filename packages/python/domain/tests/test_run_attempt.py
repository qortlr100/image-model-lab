from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from image_model_lab_domain import (
    RUN_ATTEMPT_TRANSITIONS,
    ArtifactNamespace,
    ArtifactReference,
    ArtifactUri,
    MediaType,
    RunAttempt,
    RunAttemptError,
    RunAttemptState,
    Sha256Digest,
)

STARTED_AT = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 7, 29, 11, 30, tzinfo=UTC)

MANIFEST = ArtifactReference(
    uri=ArtifactUri(
        namespace=ArtifactNamespace.RUNS, key="training/1f2e/attempts/3a4b/manifest.json"
    ),
    digest=Sha256Digest("5d41402abc4b2a76b9719d911017c5920b6f7c4e8a3d2f1e0c9b8a7d6e5f4a3b"),
    size_bytes=4096,
    media_type=MediaType("application/json"),
)

_CHANGES: dict[str, tuple[RunAttemptState, Callable[[RunAttempt], RunAttempt]]] = {
    "succeed": (
        RunAttemptState.SUCCEEDED,
        lambda attempt: attempt.succeed(ended_at=ENDED_AT, manifest=MANIFEST),
    ),
    "fail": (RunAttemptState.FAILED, lambda attempt: attempt.fail(ended_at=ENDED_AT)),
    "cancel": (RunAttemptState.CANCELLED, lambda attempt: attempt.cancel(ended_at=ENDED_AT)),
    "abandon": (RunAttemptState.ABANDONED, lambda attempt: attempt.abandon(ended_at=ENDED_AT)),
}

LEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in RunAttemptState
    if target in RUN_ATTEMPT_TRANSITIONS[state]
]
ILLEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in RunAttemptState
    if target not in RUN_ATTEMPT_TRANSITIONS[state]
]


def attempt_in(state: RunAttemptState, *, number: int = 1) -> RunAttempt:
    running = state is RunAttemptState.RUNNING
    keeps_manifest = state is RunAttemptState.SUCCEEDED
    return RunAttempt(
        id=uuid4(),
        job_id=uuid4(),
        agent_id=uuid4(),
        number=number,
        started_at=STARTED_AT,
        state=state,
        ended_at=None if running else ENDED_AT,
        manifest=MANIFEST if keeps_manifest else None,
    )


def test_a_new_attempt_is_running_with_no_outcome() -> None:
    attempt = attempt_in(RunAttemptState.RUNNING)

    assert attempt.state is RunAttemptState.RUNNING
    assert attempt.outcome is None
    assert not attempt.is_complete


def test_the_transition_table_covers_every_state() -> None:
    assert set(RUN_ATTEMPT_TRANSITIONS) == set(RunAttemptState)


def test_every_allowed_transition_has_a_method() -> None:
    """No entry in the table is unreachable through the attempt's API."""

    declared = {
        (state, target) for state, targets in RUN_ATTEMPT_TRANSITIONS.items() for target in targets
    }
    covered = {(state, _CHANGES[name][0]) for state, name in LEGAL}

    assert covered == declared


@pytest.mark.parametrize(("state", "name"), LEGAL)
def test_allowed_transition_records_the_outcome(state: RunAttemptState, name: str) -> None:
    attempt = attempt_in(state)
    target, change = _CHANGES[name]

    ended = change(attempt)

    assert ended.state is target
    assert ended.outcome is target
    assert ended.is_complete
    assert ended.ended_at == ENDED_AT
    assert ended.id == attempt.id
    assert attempt.state is state


@pytest.mark.parametrize(("state", "name"), ILLEGAL)
def test_rejects_every_transition_outside_the_table(state: RunAttemptState, name: str) -> None:
    attempt = attempt_in(state)
    _, change = _CHANGES[name]

    with pytest.raises(RunAttemptError):
        change(attempt)


def test_a_completed_attempt_is_never_rewritten() -> None:
    """A retry is the next attempt, so the record of this one stays as it was."""

    failed = attempt_in(RunAttemptState.RUNNING).fail(ended_at=ENDED_AT)

    with pytest.raises(RunAttemptError):
        failed.succeed(ended_at=ENDED_AT, manifest=MANIFEST)


def test_a_succeeded_attempt_carries_its_run_manifest() -> None:
    succeeded = attempt_in(RunAttemptState.RUNNING).succeed(ended_at=ENDED_AT, manifest=MANIFEST)

    assert succeeded.manifest == MANIFEST


def test_a_succeeded_attempt_without_a_manifest_cannot_exist() -> None:
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=1,
            started_at=STARTED_AT,
            state=RunAttemptState.SUCCEEDED,
            ended_at=ENDED_AT,
        )


def test_a_stopped_attempt_may_still_own_its_partial_outputs() -> None:
    cancelled = attempt_in(RunAttemptState.RUNNING).cancel(ended_at=ENDED_AT, manifest=MANIFEST)

    assert cancelled.manifest == MANIFEST


def test_an_abandoned_attempt_has_no_manifest_because_nobody_finalized_one() -> None:
    abandoned = attempt_in(RunAttemptState.RUNNING).abandon(ended_at=ENDED_AT)

    assert abandoned.manifest is None
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=1,
            started_at=STARTED_AT,
            state=RunAttemptState.ABANDONED,
            ended_at=ENDED_AT,
            manifest=MANIFEST,
        )


def test_a_running_attempt_has_neither_an_end_nor_a_manifest() -> None:
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=1,
            started_at=STARTED_AT,
            ended_at=ENDED_AT,
        )
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=1,
            started_at=STARTED_AT,
            manifest=MANIFEST,
        )


def test_rejects_an_attempt_that_ended_before_it_started() -> None:
    attempt = attempt_in(RunAttemptState.RUNNING)

    with pytest.raises(RunAttemptError):
        attempt.fail(ended_at=STARTED_AT - timedelta(seconds=1))


def test_an_attempt_may_end_in_the_same_instant_it_started() -> None:
    attempt = attempt_in(RunAttemptState.RUNNING).fail(ended_at=STARTED_AT)

    assert attempt.ended_at == STARTED_AT


def test_normalizes_instants_to_utc() -> None:
    """The same instant written in another zone is the same recorded instant."""

    elsewhere = ENDED_AT.astimezone(timezone(timedelta(hours=9)))

    attempt = attempt_in(RunAttemptState.RUNNING).fail(ended_at=elsewhere)

    assert attempt.ended_at == ENDED_AT
    assert attempt.ended_at is not None
    assert attempt.ended_at.tzinfo is UTC


@pytest.mark.parametrize("started_at", [STARTED_AT.replace(tzinfo=None), "2026-07-29T10:00:00Z"])
def test_rejects_a_start_that_is_not_an_instant(started_at: object) -> None:
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=1,
            started_at=started_at,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("number", [0, -1, True, 1.0, "1"])
def test_rejects_an_attempt_number_that_cannot_order_the_retries(number: object) -> None:
    with pytest.raises(RunAttemptError):
        RunAttempt(
            id=uuid4(),
            job_id=uuid4(),
            agent_id=uuid4(),
            number=number,  # type: ignore[arg-type]
            started_at=STARTED_AT,
        )


def test_is_immutable() -> None:
    attempt = attempt_in(RunAttemptState.RUNNING)

    with pytest.raises(AttributeError):
        attempt.state = RunAttemptState.SUCCEEDED  # type: ignore[misc]
