from collections.abc import Callable
from uuid import uuid4

import pytest
from image_model_lab_domain import (
    EXECUTION_JOB_TRANSITIONS,
    ExecutionJob,
    ExecutionJobError,
    ExecutionJobKind,
    ExecutionJobState,
)
from image_model_lab_domain.execution.job import MAX_IDEMPOTENCY_KEY_LENGTH

IDEMPOTENCY_KEY = "training:9f8d0c1a-4b2e-4f6a-9c3d-7e5b1a2c3d4e:1"

_CHANGES: dict[str, tuple[ExecutionJobState, Callable[[ExecutionJob], ExecutionJob]]] = {
    "lease": (ExecutionJobState.LEASED, lambda job: job.lease()),
    "start": (ExecutionJobState.RUNNING, lambda job: job.start()),
    "release": (ExecutionJobState.QUEUED, lambda job: job.release()),
    "request_cancellation": (
        ExecutionJobState.CANCEL_REQUESTED,
        lambda job: job.request_cancellation(),
    ),
    "mark_cancelled": (ExecutionJobState.CANCELLED, lambda job: job.mark_cancelled()),
    "mark_succeeded": (ExecutionJobState.SUCCEEDED, lambda job: job.mark_succeeded()),
    "mark_failed": (ExecutionJobState.FAILED, lambda job: job.mark_failed()),
}

LEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in ExecutionJobState
    if target in EXECUTION_JOB_TRANSITIONS[state]
]
ILLEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in ExecutionJobState
    if target not in EXECUTION_JOB_TRANSITIONS[state]
]


def job_in(state: ExecutionJobState) -> ExecutionJob:
    return ExecutionJob(
        id=uuid4(),
        kind=ExecutionJobKind.TRAINING,
        idempotency_key=IDEMPOTENCY_KEY,
        state=state,
    )


def test_a_new_job_is_queued_and_claimable() -> None:
    job = ExecutionJob(id=uuid4(), kind=ExecutionJobKind.CAPTION, idempotency_key=IDEMPOTENCY_KEY)

    assert job.state is ExecutionJobState.QUEUED
    assert job.is_claimable
    assert not job.is_terminal
    assert job.priority == 0


def test_the_transition_table_covers_every_state() -> None:
    assert set(EXECUTION_JOB_TRANSITIONS) == set(ExecutionJobState)


def test_every_allowed_transition_has_a_method() -> None:
    """No entry in the table is unreachable through the job's API."""

    declared = {
        (state, target)
        for state, targets in EXECUTION_JOB_TRANSITIONS.items()
        for target in targets
    }
    covered = {(state, _CHANGES[name][0]) for state, name in LEGAL}

    assert covered == declared


@pytest.mark.parametrize(("state", "name"), LEGAL)
def test_allowed_transition_keeps_identity(state: ExecutionJobState, name: str) -> None:
    job = job_in(state)
    target, change = _CHANGES[name]

    moved = change(job)

    assert moved.state is target
    assert moved.id == job.id
    assert moved.idempotency_key == job.idempotency_key
    assert job.state is state


@pytest.mark.parametrize(("state", "name"), ILLEGAL)
def test_rejects_every_transition_outside_the_table(state: ExecutionJobState, name: str) -> None:
    job = job_in(state)
    _, change = _CHANGES[name]

    with pytest.raises(ExecutionJobError):
        change(job)


def test_a_leased_job_runs_and_succeeds() -> None:
    job = job_in(ExecutionJobState.QUEUED).lease().start().mark_succeeded()

    assert job.state is ExecutionJobState.SUCCEEDED
    assert job.is_terminal
    assert not job.is_claimable


def test_a_lost_lease_returns_the_job_to_the_queue() -> None:
    """A crashed agent must not strand a job; the next lease opens a new attempt."""

    running = job_in(ExecutionJobState.QUEUED).lease().start()

    requeued = running.release()

    assert requeued.state is ExecutionJobState.QUEUED
    assert requeued.is_claimable


def test_cancellation_is_two_step_and_cooperative() -> None:
    requested = job_in(ExecutionJobState.RUNNING).request_cancellation()

    assert requested.state is ExecutionJobState.CANCEL_REQUESTED
    assert not requested.is_terminal
    assert requested.mark_cancelled().state is ExecutionJobState.CANCELLED


def test_a_job_that_finished_before_the_cancellation_landed_still_reports_its_outcome() -> None:
    """The work happened and its outputs exist, so it is not reported as cancelled."""

    requested = job_in(ExecutionJobState.RUNNING).request_cancellation()

    assert requested.mark_succeeded().state is ExecutionJobState.SUCCEEDED
    assert requested.mark_failed().state is ExecutionJobState.FAILED


@pytest.mark.parametrize(
    "state", [ExecutionJobState.SUCCEEDED, ExecutionJobState.FAILED, ExecutionJobState.CANCELLED]
)
def test_a_finished_job_never_runs_again(state: ExecutionJobState) -> None:
    job = job_in(state)

    assert job.is_terminal
    assert EXECUTION_JOB_TRANSITIONS[state] == frozenset()
    with pytest.raises(ExecutionJobError):
        job.lease()


def test_a_repeated_completion_report_is_refused_rather_than_ignored() -> None:
    """At-least-once delivery means the caller decides what a duplicate means."""

    succeeded = job_in(ExecutionJobState.RUNNING).mark_succeeded()

    with pytest.raises(ExecutionJobError):
        succeeded.mark_succeeded()


def test_is_immutable() -> None:
    job = job_in(ExecutionJobState.QUEUED)

    with pytest.raises(AttributeError):
        job.state = ExecutionJobState.RUNNING  # type: ignore[misc]


def test_accepts_the_plain_string_spelling_of_a_kind_and_a_state() -> None:
    job = ExecutionJob(
        id=uuid4(),
        kind="caption",  # type: ignore[arg-type]
        idempotency_key=IDEMPOTENCY_KEY,
        state="leased",  # type: ignore[arg-type]
    )

    assert job.kind is ExecutionJobKind.CAPTION
    assert job.state is ExecutionJobState.LEASED


@pytest.mark.parametrize("kind", ["", "thumbnail", "TRAINING", None])
def test_rejects_a_kind_no_agent_can_claim(kind: object) -> None:
    with pytest.raises(ExecutionJobError):
        ExecutionJob(id=uuid4(), kind=kind, idempotency_key=IDEMPOTENCY_KEY)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key",
    [
        "",
        " ",
        f" {IDEMPOTENCY_KEY}",
        f"{IDEMPOTENCY_KEY}\n",
        "k" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1),
        None,
    ],
)
def test_rejects_an_idempotency_key_that_cannot_deduplicate(key: object) -> None:
    with pytest.raises(ExecutionJobError):
        ExecutionJob(id=uuid4(), kind=ExecutionJobKind.TRAINING, idempotency_key=key)  # type: ignore[arg-type]


@pytest.mark.parametrize("priority", [-1, 1.0, True, "high"])
def test_rejects_a_priority_that_is_not_a_non_negative_int(priority: object) -> None:
    with pytest.raises(ExecutionJobError):
        ExecutionJob(
            id=uuid4(),
            kind=ExecutionJobKind.TRAINING,
            idempotency_key=IDEMPOTENCY_KEY,
            priority=priority,  # type: ignore[arg-type]
        )
