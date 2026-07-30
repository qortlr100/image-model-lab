"""Storing an artifact, its state and the history of where its bytes came from."""

from __future__ import annotations

from uuid import uuid4

import factories
import pytest
from image_model_lab_application import (
    RecordAlreadyExists,
    RecordChangedElsewhere,
    RecordHistoryRewritten,
    RecordIsFinal,
    RecordNotFound,
)
from image_model_lab_domain import ArtifactState
from image_model_lab_persistence import SqlAlchemyArtifactRepository
from sqlalchemy.orm import Session


def repository(session: Session) -> SqlAlchemyArtifactRepository:
    return SqlAlchemyArtifactRepository(session)


def test_an_artifact_survives_a_round_trip_unchanged(session: Session) -> None:
    artifacts = repository(session)
    stored = factories.artifact()

    artifacts.add(stored)
    session.expunge_all()

    assert artifacts.get(stored.id) == stored


def test_provenance_keeps_its_order(session: Session) -> None:
    """The first record is the write that put the bytes on NAS."""

    artifacts = repository(session)
    origin = factories.ingested("inbox import, roll 4")
    second = factories.ingested("re-import from the 2024 archive")
    stored = factories.artifact(provenance=(origin, second))

    artifacts.add(stored)
    session.expunge_all()

    assert artifacts.get(stored.id).provenance == (origin, second)


def test_reading_an_artifact_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        repository(session).get(uuid4())


def test_two_artifacts_cannot_claim_one_logical_uri(session: Session) -> None:
    """An address names one object, or a reader cannot tell what it addressed."""

    artifacts = repository(session)
    address = factories.reference(key="original/c9/c9002e99")
    artifacts.add(factories.artifact(reference_=address))

    with pytest.raises(RecordAlreadyExists):
        artifacts.add(factories.artifact(reference_=address))


def test_two_artifacts_may_share_a_digest(session: Session) -> None:
    """A quarantined artifact keeps its row, and the good copy is a new one."""

    artifacts = repository(session)
    quarantined = factories.artifact(
        reference_=factories.reference(seed="abcd1234"), state=ArtifactState.QUARANTINED
    )
    artifacts.add(quarantined)

    republished = factories.artifact(reference_=factories.reference(seed="abcd1234"))
    artifacts.add(republished)

    assert artifacts.get(republished.id).reference.digest == quarantined.reference.digest


def test_a_state_change_is_stored(session: Session) -> None:
    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)

    artifacts.update(stored.mark_available(), expected_state=stored.state)
    session.expunge_all()

    assert artifacts.get(stored.id).state is ArtifactState.AVAILABLE


def test_a_state_change_does_not_disturb_the_provenance(session: Session) -> None:
    artifacts = repository(session)
    stored = factories.artifact(provenance=(factories.ingested(),))
    artifacts.add(stored)

    artifacts.update(stored.quarantine(), expected_state=stored.state)
    session.expunge_all()

    assert artifacts.get(stored.id).provenance == stored.provenance


def test_a_further_import_is_appended(session: Session) -> None:
    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)

    reimported = stored.record_provenance(factories.ingested("re-import from the 2024 archive"))
    artifacts.update(reimported, expected_state=stored.state)
    session.expunge_all()

    assert artifacts.get(stored.id).provenance == reimported.provenance


def test_provenance_cannot_be_shortened(session: Session) -> None:
    artifacts = repository(session)
    origin = factories.ingested("inbox import, roll 4")
    stored = factories.artifact(provenance=(origin, factories.ingested("second import")))
    artifacts.add(stored)

    with pytest.raises(RecordHistoryRewritten):
        artifacts.update(
            factories.artifact(artifact_id=stored.id, provenance=(origin,)),
            expected_state=stored.state,
        )


def test_a_recorded_origin_cannot_be_replaced(session: Session) -> None:
    """A licence audit reads these records; a rewrite would erase one."""

    artifacts = repository(session)
    stored = factories.artifact(provenance=(factories.ingested("inbox import, roll 4"),))
    artifacts.add(stored)

    rewritten = factories.artifact(
        artifact_id=stored.id,
        reference_=stored.reference,
        provenance=(factories.ingested("a different source entirely"),),
    )

    with pytest.raises(RecordHistoryRewritten):
        artifacts.update(rewritten, expected_state=stored.state)


def test_an_update_does_not_re_address_the_stored_artifact(session: Session) -> None:
    """The reference is what identifies an artifact, so an update never carries one."""

    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)

    artifacts.update(
        factories.artifact(
            artifact_id=stored.id,
            reference_=factories.reference(key="original/somewhere/else"),
            provenance=stored.provenance,
        ),
        expected_state=stored.state,
    )
    session.expunge_all()

    assert artifacts.get(stored.id).reference == stored.reference


def test_a_quarantined_artifact_takes_no_new_provenance(session: Session) -> None:
    """The stale value a concurrent quarantine leaves a second writer holding.

    Two transactions read the same available artifact; one quarantines it and
    commits, the other still holds the value it read and appends an import to
    it. Waiting on the row lock is not enough on its own -- the second writer
    then sees the quarantined row, and without this check would attach the
    import to bytes whose digest was declared untrustworthy, claiming that
    import produced them.
    """

    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)
    artifacts.update(stored.quarantine(), expected_state=stored.state)

    with pytest.raises(RecordIsFinal):
        artifacts.update(
            stored.record_provenance(factories.ingested("a later import")),
            expected_state=stored.state,
        )


def test_a_quarantined_artifact_is_not_returned_to_an_earlier_state(session: Session) -> None:
    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)
    available = stored.mark_available()
    artifacts.update(available, expected_state=stored.state)
    artifacts.update(available.quarantine(), expected_state=available.state)

    with pytest.raises(RecordIsFinal):
        artifacts.update(available, expected_state=stored.state)


def test_a_stale_state_is_refused_rather_than_written(session: Session) -> None:
    """``missing`` does not become ``pending``, so the write is a lost update."""

    artifacts = repository(session)
    stored = factories.artifact()
    artifacts.add(stored)
    available = stored.mark_available()
    artifacts.update(available, expected_state=stored.state)
    artifacts.update(available.mark_missing(), expected_state=available.state)

    with pytest.raises(RecordChangedElsewhere):
        artifacts.update(stored, expected_state=stored.state)


def test_updating_an_artifact_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        repository(session).update(factories.artifact(), expected_state=ArtifactState.PENDING)
