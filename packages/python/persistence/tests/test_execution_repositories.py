"""Storing what should run, and what each execution actually did."""

from __future__ import annotations

from uuid import uuid4

import factories
import pytest
from image_model_lab_application import (
    RecordAlreadyExists,
    RecordChangedElsewhere,
    RecordIsFinal,
    RecordNotFound,
)
from image_model_lab_domain import ExecutionJobState, RunAttemptState
from image_model_lab_persistence import (
    SqlAlchemyExecutionJobRepository,
    SqlAlchemyRunAttemptRepository,
)
from sqlalchemy.orm import Session


def jobs(session: Session) -> SqlAlchemyExecutionJobRepository:
    return SqlAlchemyExecutionJobRepository(session)


def attempts(session: Session) -> SqlAlchemyRunAttemptRepository:
    return SqlAlchemyRunAttemptRepository(session)


def test_a_job_survives_a_round_trip_unchanged(session: Session) -> None:
    repository = jobs(session)
    stored = factories.job()

    repository.add(stored)
    session.expunge_all()

    assert repository.get(stored.id) == stored


def test_reading_a_job_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        jobs(session).get(uuid4())


def test_one_idempotency_key_queues_one_job(session: Session) -> None:
    """Delivery is at-least-once, so the same request can arrive twice."""

    repository = jobs(session)
    repository.add(factories.job(idempotency_key="train:snapshot-9:recipe-3"))

    with pytest.raises(RecordAlreadyExists):
        repository.add(factories.job(idempotency_key="train:snapshot-9:recipe-3"))


def test_a_repeated_request_finds_the_job_it_already_queued(session: Session) -> None:
    repository = jobs(session)
    stored = factories.job(idempotency_key="train:snapshot-9:recipe-3")
    repository.add(stored)
    session.expunge_all()

    assert repository.find_by_idempotency_key("train:snapshot-9:recipe-3") == stored


def test_an_unknown_idempotency_key_finds_nothing(session: Session) -> None:
    assert jobs(session).find_by_idempotency_key("train:never-queued") is None


def test_a_lease_and_its_loss_are_both_stored(session: Session) -> None:
    """Losing a lease returns the job to the queue for another agent."""

    repository = jobs(session)
    stored = factories.job()
    repository.add(stored)

    leased = stored.lease()
    repository.update(leased)
    repository.update(leased.start().release())
    session.expunge_all()

    assert repository.get(stored.id).state is ExecutionJobState.QUEUED


def test_a_job_outcome_does_not_depend_on_which_report_was_written_last(
    session: Session,
) -> None:
    """The stale value a second completion report leaves a handler holding.

    Two handlers derive an outcome from the same running job. The first writes
    ``failed`` and commits; the second still holds the running value it read
    and would write ``succeeded`` over it. Waiting on the row lock is not
    enough on its own -- without checking the stored state, the job's recorded
    outcome would be whichever report happened to be written last.
    """

    repository = jobs(session)
    stored = factories.job()
    repository.add(stored)
    leased = stored.lease()
    repository.update(leased)
    running = leased.start()
    repository.update(running)
    repository.update(running.mark_failed())

    with pytest.raises(RecordIsFinal):
        repository.update(running.mark_succeeded())


def test_a_stale_job_state_is_refused_rather_than_written(session: Session) -> None:
    """``running`` does not become ``leased``, so the write is a lost update."""

    repository = jobs(session)
    stored = factories.job()
    repository.add(stored)
    leased = stored.lease()
    repository.update(leased)
    repository.update(leased.start())

    with pytest.raises(RecordChangedElsewhere):
        repository.update(leased)


def test_an_attempt_survives_a_round_trip_unchanged(session: Session) -> None:
    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    stored = factories.attempt(owner.id)

    repository.add(stored)
    session.expunge_all()

    assert repository.get(stored.id) == stored


def test_an_attempt_needs_a_job_that_exists(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        attempts(session).add(factories.attempt(uuid4()))


def test_a_job_cannot_have_two_attempts_with_one_number(session: Session) -> None:
    """A retry is the next attempt, not a replacement for the last one."""

    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    repository.add(factories.attempt(owner.id, number=1))

    with pytest.raises(RecordAlreadyExists):
        repository.add(factories.attempt(owner.id, number=1))


def test_attempts_are_listed_in_the_order_they_were_numbered(session: Session) -> None:
    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    third = factories.attempt(owner.id, number=3)
    first = factories.attempt(owner.id, number=1)
    repository.add(third)
    repository.add(first)
    session.expunge_all()

    assert [attempt.number for attempt in repository.list_for_job(owner.id)] == [1, 3]


def test_a_job_with_no_attempts_lists_none(session: Session) -> None:
    assert attempts(session).list_for_job(uuid4()) == ()


def test_a_successful_attempt_stores_its_manifest(session: Session) -> None:
    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    stored = factories.attempt(owner.id)
    repository.add(stored)

    manifest = factories.reference(key=f"training/{owner.id}/manifest.json")
    repository.complete(stored.succeed(ended_at=factories.ENDED_AT, manifest=manifest))
    session.expunge_all()

    completed = repository.get(stored.id)
    assert completed.state is RunAttemptState.SUCCEEDED
    assert completed.manifest == manifest
    assert completed.ended_at == factories.ENDED_AT


def test_an_abandoned_attempt_stores_no_manifest(session: Session) -> None:
    """Nobody was left to finalize one, so it claims no outputs."""

    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    stored = factories.attempt(owner.id)
    repository.add(stored)

    repository.complete(stored.abandon(ended_at=factories.ENDED_AT))
    session.expunge_all()

    assert repository.get(stored.id).manifest is None


def test_a_completed_attempt_is_not_rewritten(session: Session) -> None:
    """At-least-once delivery means a completion report can arrive twice."""

    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    stored = factories.attempt(owner.id)
    repository.add(stored)
    repository.complete(stored.fail(ended_at=factories.ENDED_AT))

    with pytest.raises(RecordIsFinal):
        repository.complete(
            stored.succeed(
                ended_at=factories.ENDED_AT,
                manifest=factories.reference(key=f"training/{owner.id}/manifest.json"),
            )
        )


def test_completing_an_attempt_with_a_value_that_has_not_ended_is_refused(
    session: Session,
) -> None:
    """``complete`` records how something ended, so it must carry an ending."""

    owner = factories.job()
    jobs(session).add(owner)
    repository = attempts(session)
    stored = factories.attempt(owner.id)
    repository.add(stored)

    with pytest.raises(RecordChangedElsewhere):
        repository.complete(stored)


def test_completing_an_attempt_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        attempts(session).complete(factories.attempt(uuid4()).abandon(ended_at=factories.ENDED_AT))
