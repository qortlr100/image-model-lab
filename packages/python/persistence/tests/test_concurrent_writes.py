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
from image_model_lab_application import RecordAlreadyExists, RecordIsFinal
from image_model_lab_domain import Artifact, ArtifactState
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
    artifacts.update(available)
    first.commit()
    # Load it, so the first session is holding it in its identity map.
    assert artifacts.get(artifact.id).state is ArtifactState.AVAILABLE

    SqlAlchemyArtifactRepository(second).update(available.quarantine())
    second.commit()

    with pytest.raises(RecordIsFinal):
        artifacts.update(available.record_provenance(factories.ingested("a later import")))


def test_a_quarantine_committed_elsewhere_leaves_the_provenance_alone(
    first: Session, second: Session
) -> None:
    """The refusal has to happen before the append, not after it."""

    artifacts = SqlAlchemyArtifactRepository(first)
    artifact = factories.artifact()
    artifacts.add(artifact)
    first.commit()
    assert artifacts.get(artifact.id).state is ArtifactState.PENDING

    SqlAlchemyArtifactRepository(second).update(artifact.quarantine())
    second.commit()

    with pytest.raises(RecordIsFinal):
        artifacts.update(artifact.record_provenance(factories.ingested("a later import")))
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
