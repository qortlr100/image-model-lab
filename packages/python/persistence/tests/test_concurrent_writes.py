"""What one session sees after another has committed.

Every other test in this package runs inside a transaction that is rolled back,
which keeps them independent but means nothing is ever really committed. These
use a database of their own so a second session can observe a first session's
committed work -- which is the only way to test the two failures below, because
both of them look correct from inside a single transaction.

They are not timing tests. Nothing here races: the first session commits before
the second acts, which is exactly the state the second session finds itself in
after waiting on a row lock. What is under test is what it does with that
state, not whether it waited.
"""

from __future__ import annotations

from collections.abc import Iterator

import factories
import pytest
from image_model_lab_application import (
    RecordAlreadyExists,
    RecordChangedElsewhere,
    RecordIsFinal,
)
from image_model_lab_domain import Artifact, ArtifactState, ExecutionJobState
from image_model_lab_persistence import (
    SqlAlchemyArtifactRepository,
    SqlAlchemyExecutionJobRepository,
)
from image_model_lab_persistence.tables import ArtifactRow
from sqlalchemy import Engine
from sqlalchemy.orm import Session


@pytest.fixture
def first(concurrent_engine: Engine) -> Iterator[Session]:
    with Session(concurrent_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def second(concurrent_engine: Engine) -> Iterator[Session]:
    with Session(concurrent_engine, expire_on_commit=False) as session:
        yield session


def stored_artifact(session: Session, artifact: Artifact) -> ArtifactRow:
    row = session.get(ArtifactRow, artifact.id, populate_existing=True)
    assert row is not None
    return row


def test_a_locked_read_sees_the_database_not_the_identity_map(
    first: Session, second: Session
) -> None:
    """A cached row would have the guard checking what the caller already knew.

    The first session loads the artifact, so it is in that session's identity
    map. `SELECT ... FOR UPDATE` takes the lock but does not repopulate an
    already-loaded object on its own, so without an explicit refresh the guard
    would read `available` from cache while the database says `quarantined` --
    and would then append provenance to bytes that contradict their digest.
    """

    artifacts = SqlAlchemyArtifactRepository(first)
    artifact = factories.artifact()
    artifacts.add(artifact)
    first.commit()
    available = artifact.mark_available()
    artifacts.update(available, expected_state=artifact.state)
    first.commit()
    # Load it, so the first session is holding it in its identity map.
    assert artifacts.get(artifact.id).state is ArtifactState.AVAILABLE

    SqlAlchemyArtifactRepository(second).update(
        available.quarantine(), expected_state=available.state
    )
    second.commit()

    with pytest.raises(RecordIsFinal):
        artifacts.update(
            available.record_provenance(factories.ingested("a later import")),
            expected_state=available.state,
        )


def test_a_quarantine_committed_elsewhere_leaves_the_provenance_alone(
    first: Session, second: Session
) -> None:
    """The refusal has to happen before the append, not after it."""

    artifacts = SqlAlchemyArtifactRepository(first)
    artifact = factories.artifact()
    artifacts.add(artifact)
    first.commit()
    assert artifacts.get(artifact.id).state is ArtifactState.PENDING

    SqlAlchemyArtifactRepository(second).update(
        artifact.quarantine(), expected_state=artifact.state
    )
    second.commit()

    with pytest.raises(RecordIsFinal):
        artifacts.update(
            artifact.record_provenance(factories.ingested("a later import")),
            expected_state=artifact.state,
        )
    first.rollback()

    assert len(stored_artifact(first, artifact).provenance) == 1


def test_a_duplicate_insert_leaves_the_transaction_usable(first: Session, second: Session) -> None:
    """`RecordAlreadyExists` is only useful if the caller can act on it.

    Delivery is at-least-once, so the answer to a duplicate is normally to look
    up the job already queued and acknowledge it. PostgreSQL aborts a whole
    transaction on a failed statement, so without a savepoint around the insert
    the caller would be told the record exists and then be unable to read it.
    """

    key = "train:snapshot-9:recipe-3"
    SqlAlchemyExecutionJobRepository(first).add(factories.job(idempotency_key=key))
    first.commit()

    jobs = SqlAlchemyExecutionJobRepository(second)
    with pytest.raises(RecordAlreadyExists):
        jobs.add(factories.job(idempotency_key=key))

    assert jobs.find_by_idempotency_key(key) is not None


def test_work_already_done_survives_a_duplicate_insert(first: Session, second: Session) -> None:
    """The savepoint undoes the failed insert, not the use case's transaction."""

    key = "train:snapshot-9:recipe-3"
    SqlAlchemyExecutionJobRepository(first).add(factories.job(idempotency_key=key))
    first.commit()

    artifacts = SqlAlchemyArtifactRepository(second)
    earlier = factories.artifact()
    artifacts.add(earlier)

    with pytest.raises(RecordAlreadyExists):
        SqlAlchemyExecutionJobRepository(second).add(factories.job(idempotency_key=key))
    second.commit()

    assert SqlAlchemyArtifactRepository(first).get(earlier.id) == earlier


def test_a_verification_made_before_the_bytes_went_missing_is_refused(
    first: Session, second: Session
) -> None:
    """The cycle a target-only check cannot see.

    ``missing -> available`` is a legal repair, so an artifact verified while it
    was ``pending`` would pass a check that only asks whether the row may become
    ``available`` -- even after the bytes were observed absent. The verification
    predates that observation, so accepting it marks absent bytes readable. The
    expected state is what makes the difference: the caller read ``pending`` and
    the row says ``missing``.
    """

    artifacts = SqlAlchemyArtifactRepository(first)
    artifact = factories.artifact()
    artifacts.add(artifact)
    first.commit()
    pending = artifacts.get(artifact.id)
    verified = pending.mark_available()

    elsewhere = SqlAlchemyArtifactRepository(second)
    available = elsewhere.get(artifact.id).mark_available()
    elsewhere.update(available, expected_state=ArtifactState.PENDING)
    elsewhere.update(available.mark_missing(), expected_state=ArtifactState.AVAILABLE)
    second.commit()

    with pytest.raises(RecordChangedElsewhere):
        artifacts.update(verified, expected_state=pending.state)

    first.rollback()
    assert stored_artifact(first, artifact).state == ArtifactState.MISSING.value


def test_a_second_agent_cannot_claim_a_job_that_was_already_leased(
    first: Session, second: Session
) -> None:
    """The lease race the expected state does catch.

    Two agents read the same ``queued`` job and both decide to lease it. The
    first claim lands; the second arrives with ``expected_state=queued`` while
    the row says ``leased``, so it is refused rather than overwriting a lease
    another agent holds.

    What this does *not* cover is a job that has gone all the way back to
    ``queued`` -- see the next test. The difference is whether the value the
    caller read is still the value in the row.
    """

    jobs = SqlAlchemyExecutionJobRepository(first)
    job = factories.job()
    jobs.add(job)
    first.commit()
    queued = jobs.get(job.id)
    claim = queued.lease()

    elsewhere = SqlAlchemyExecutionJobRepository(second)
    elsewhere.update(elsewhere.get(job.id).lease(), expected_state=ExecutionJobState.QUEUED)
    second.commit()

    with pytest.raises(RecordChangedElsewhere):
        jobs.update(claim, expected_state=queued.state)


def test_a_completed_cycle_back_to_the_same_state_is_not_caught(
    first: Session, second: Session
) -> None:
    """The limit of an expected state, pinned so it is not mistaken for safety.

    ``queued -> leased -> running -> queued`` returns to the value the caller
    read, so ``expected_state`` matches and the stale claim lands. An expected
    state can only say "the value I read is still there", which is exactly what
    a completed cycle makes true again.

    Every state reachable from itself has this hole: ``available`` and
    ``missing`` for artifacts, ``queued``, ``leased`` and ``running`` for jobs,
    plus the ``draft -> draft`` item edit. All of them need a revision rather
    than a state, which the ports do not carry -- see ADR-0005. This test
    records the boundary; it will need deleting when that arrives.
    """

    jobs = SqlAlchemyExecutionJobRepository(first)
    job = factories.job()
    jobs.add(job)
    first.commit()
    queued = jobs.get(job.id)
    claim = queued.lease()

    elsewhere = SqlAlchemyExecutionJobRepository(second)
    leased = elsewhere.get(job.id).lease()
    elsewhere.update(leased, expected_state=ExecutionJobState.QUEUED)
    running = leased.start()
    elsewhere.update(running, expected_state=ExecutionJobState.LEASED)
    elsewhere.update(running.release(), expected_state=ExecutionJobState.RUNNING)
    second.commit()

    jobs.update(claim, expected_state=queued.state)
    first.commit()

    assert jobs.get(job.id).state is ExecutionJobState.LEASED
