"""Storing a training input while it is still a draft, and once it is sealed."""

from __future__ import annotations

from uuid import uuid4

import factories
import pytest
from image_model_lab_application import (
    RecordChangedElsewhere,
    RecordIsFinal,
    RecordNotFound,
)
from image_model_lab_domain import DatasetSnapshotState
from image_model_lab_persistence import SqlAlchemyDatasetSnapshotRepository
from sqlalchemy.orm import Session


def repository(session: Session) -> SqlAlchemyDatasetSnapshotRepository:
    return SqlAlchemyDatasetSnapshotRepository(session)


def test_a_snapshot_survives_a_round_trip_unchanged(session: Session) -> None:
    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(), factories.item(repeats=3)))

    snapshots.add(stored)
    session.expunge_all()

    assert snapshots.get(stored.id) == stored


def test_item_order_is_stored_rather_than_left_to_the_query(session: Session) -> None:
    """Order is part of the sealed input, so it has to come back the same."""

    snapshots = repository(session)
    items = tuple(factories.item() for _ in range(8))
    stored = factories.snapshot(items=items)

    snapshots.add(stored)
    session.expunge_all()

    assert snapshots.get(stored.id).items == items


def test_reading_a_snapshot_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        repository(session).get(uuid4())


def test_a_draft_may_have_its_items_replaced(session: Session) -> None:
    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(), factories.item()))
    snapshots.add(stored)

    kept = stored.items[1]
    reordered = stored.reorder([kept.asset_revision_id, stored.items[0].asset_revision_id])
    snapshots.update(reordered)
    session.expunge_all()

    assert snapshots.get(stored.id).items == reordered.items


def test_an_item_can_be_dropped_from_a_draft(session: Session) -> None:
    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(), factories.item()))
    snapshots.add(stored)

    trimmed = stored.remove_item(stored.items[0].asset_revision_id)
    snapshots.update(trimmed)
    session.expunge_all()

    assert snapshots.get(stored.id).items == trimmed.items


def test_sealing_stores_the_manifest_and_the_instant(session: Session) -> None:
    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(),))
    snapshots.add(stored)
    validating = stored.begin_validation()
    snapshots.update(validating)

    manifest = factories.reference(key=f"{stored.id}/manifest.json")
    snapshots.update(validating.seal(manifest=manifest, sealed_at=factories.ENDED_AT))
    session.expunge_all()

    read = snapshots.get(stored.id)
    assert read.state is DatasetSnapshotState.SEALED
    assert read.manifest == manifest
    assert read.sealed_at == factories.ENDED_AT


def test_a_sealed_snapshot_is_never_written_again(session: Session) -> None:
    """Runs already name this snapshot's digest; a correction is a new one."""

    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(),))
    snapshots.add(stored)
    validating = stored.begin_validation()
    snapshots.update(validating)
    sealed = validating.seal(
        manifest=factories.reference(key=f"{stored.id}/manifest.json"),
        sealed_at=factories.ENDED_AT,
    )
    snapshots.update(sealed)

    with pytest.raises(RecordIsFinal):
        snapshots.update(sealed)


def test_a_rejected_snapshot_is_never_written_again(session: Session) -> None:
    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(),))
    snapshots.add(stored)
    rejected = stored.reject()
    snapshots.update(rejected)

    with pytest.raises(RecordIsFinal):
        snapshots.update(rejected)


def test_validation_freezes_the_items_that_get_sealed(session: Session) -> None:
    """The list that was checked is the list that is sealed."""

    snapshots = repository(session)
    items = (factories.item(), factories.item())
    stored = factories.snapshot(items=items)
    snapshots.add(stored)
    validating = stored.begin_validation()
    snapshots.update(validating)

    snapshots.update(
        validating.seal(
            manifest=factories.reference(key=f"{stored.id}/manifest.json"),
            sealed_at=factories.ENDED_AT,
        )
    )
    session.expunge_all()

    assert snapshots.get(stored.id).items == items


def test_a_validating_snapshot_is_not_returned_to_draft(session: Session) -> None:
    """The stale draft a concurrent ``begin_validation`` leaves behind.

    One transaction starts validation and commits; another still holds the
    draft it read and writes that back. Waiting on the row lock is not enough
    on its own -- without checking the stored state, the snapshot would be
    reopened and a later draft update could change the item list validation had
    already frozen, sealing something that was never checked.
    """

    snapshots = repository(session)
    stored = factories.snapshot(items=(factories.item(),))
    snapshots.add(stored)
    snapshots.update(stored.begin_validation())

    with pytest.raises(RecordChangedElsewhere):
        snapshots.update(stored.add_item(factories.item()))


def test_updating_a_snapshot_that_was_never_stored_is_an_error(session: Session) -> None:
    with pytest.raises(RecordNotFound):
        repository(session).update(factories.snapshot())
