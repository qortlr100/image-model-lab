from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from image_model_lab_domain import (
    DATASET_SNAPSHOT_TRANSITIONS,
    ArtifactNamespace,
    ArtifactReference,
    ArtifactUri,
    DatasetSnapshot,
    DatasetSnapshotError,
    DatasetSnapshotState,
    MediaType,
    Sha256Digest,
    SnapshotItem,
    SnapshotItemError,
)

SEALED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

MANIFEST = ArtifactReference(
    uri=ArtifactUri(namespace=ArtifactNamespace.DATASETS, key="7c1d/snapshots/9b2a/manifest.json"),
    digest=Sha256Digest("aa7d3ff8e0b1c2d3e4f5061728394a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5"),
    size_bytes=8192,
    media_type=MediaType("application/json"),
)

_CHANGES: dict[str, tuple[DatasetSnapshotState, Callable[[DatasetSnapshot], DatasetSnapshot]]] = {
    "begin_validation": (
        DatasetSnapshotState.VALIDATING,
        lambda snapshot: snapshot.begin_validation(),
    ),
    "seal": (
        DatasetSnapshotState.SEALED,
        lambda snapshot: snapshot.seal(manifest=MANIFEST, sealed_at=SEALED_AT),
    ),
    "reject": (DatasetSnapshotState.REJECTED, lambda snapshot: snapshot.reject()),
}

LEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in DatasetSnapshotState
    if target in DATASET_SNAPSHOT_TRANSITIONS[state]
]
ILLEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in DatasetSnapshotState
    if target not in DATASET_SNAPSHOT_TRANSITIONS[state]
]


def item(*, repeats: int = 1) -> SnapshotItem:
    return SnapshotItem(
        asset_revision_id=uuid4(),
        caption_revision_id=uuid4(),
        caption_approved=True,
        repeats=repeats,
    )


def snapshot_in(state: DatasetSnapshotState, *, items: int = 2) -> DatasetSnapshot:
    sealed = state is DatasetSnapshotState.SEALED
    return DatasetSnapshot(
        id=uuid4(),
        dataset_id=uuid4(),
        items=tuple(item() for _ in range(items)),
        state=state,
        manifest=MANIFEST if sealed else None,
        sealed_at=SEALED_AT if sealed else None,
    )


def test_a_new_snapshot_is_an_empty_draft() -> None:
    snapshot = DatasetSnapshot(id=uuid4(), dataset_id=uuid4())

    assert snapshot.state is DatasetSnapshotState.DRAFT
    assert snapshot.items == ()
    assert not snapshot.is_sealed


def test_the_transition_table_covers_every_state() -> None:
    assert set(DATASET_SNAPSHOT_TRANSITIONS) == set(DatasetSnapshotState)


def test_the_transition_table_cannot_be_widened_at_runtime() -> None:
    """A lifecycle a caller can edit in place is not an invariant."""

    with pytest.raises(TypeError):
        DATASET_SNAPSHOT_TRANSITIONS[DatasetSnapshotState.SEALED] = frozenset(  # type: ignore[index]
            {DatasetSnapshotState.DRAFT}
        )


def test_every_allowed_transition_has_a_method() -> None:
    """No entry in the table is unreachable through the snapshot's API."""

    declared = {
        (state, target)
        for state, targets in DATASET_SNAPSHOT_TRANSITIONS.items()
        for target in targets
    }
    covered = {(state, _CHANGES[name][0]) for state, name in LEGAL}

    assert covered == declared


@pytest.mark.parametrize(("state", "name"), LEGAL)
def test_allowed_transition_keeps_the_items(state: DatasetSnapshotState, name: str) -> None:
    snapshot = snapshot_in(state)
    target, change = _CHANGES[name]

    moved = change(snapshot)

    assert moved.state is target
    assert moved.items == snapshot.items
    assert moved.id == snapshot.id
    assert snapshot.state is state


@pytest.mark.parametrize(("state", "name"), ILLEGAL)
def test_rejects_every_transition_outside_the_table(state: DatasetSnapshotState, name: str) -> None:
    snapshot = snapshot_in(state)
    _, change = _CHANGES[name]

    with pytest.raises(DatasetSnapshotError):
        change(snapshot)


def test_a_draft_is_validated_then_sealed_with_the_manifest_that_names_it() -> None:
    draft = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).add_item(item())

    sealed = draft.begin_validation().seal(manifest=MANIFEST, sealed_at=SEALED_AT)

    assert sealed.is_sealed
    assert sealed.manifest == MANIFEST
    assert sealed.sealed_at == SEALED_AT


def test_sealing_never_reverses() -> None:
    """A mistake in a sealed snapshot is corrected by building a new snapshot."""

    sealed = snapshot_in(DatasetSnapshotState.SEALED)

    assert DATASET_SNAPSHOT_TRANSITIONS[DatasetSnapshotState.SEALED] == frozenset()
    with pytest.raises(DatasetSnapshotError):
        sealed.begin_validation()
    with pytest.raises(DatasetSnapshotError):
        sealed.reject()


def test_a_sealed_snapshot_refuses_to_add_remove_or_reorder_items() -> None:
    sealed = snapshot_in(DatasetSnapshotState.SEALED)
    first, second = sealed.items

    with pytest.raises(DatasetSnapshotError):
        sealed.add_item(item())
    with pytest.raises(DatasetSnapshotError):
        sealed.remove_item(first.asset_revision_id)
    with pytest.raises(DatasetSnapshotError):
        sealed.reorder([second.asset_revision_id, first.asset_revision_id])

    assert sealed.items == (first, second)


def test_a_snapshot_being_validated_refuses_item_changes() -> None:
    """The list that was checked is the list that gets sealed."""

    validating = snapshot_in(DatasetSnapshotState.VALIDATING)

    with pytest.raises(DatasetSnapshotError):
        validating.add_item(item())


def test_a_draft_adds_removes_and_reorders_items() -> None:
    first, second = item(), item()
    draft = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).add_item(first).add_item(second)

    assert draft.items == (first, second)
    assert draft.reorder([second.asset_revision_id, first.asset_revision_id]).items == (
        second,
        first,
    )
    assert draft.remove_item(first.asset_revision_id).items == (second,)


def test_a_change_leaves_the_snapshot_it_was_made_from_alone() -> None:
    draft = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).add_item(item())

    draft.add_item(item())

    assert len(draft.items) == 1


def test_rejects_removing_or_reordering_items_the_snapshot_does_not_have() -> None:
    draft = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).add_item(item())

    with pytest.raises(DatasetSnapshotError):
        draft.remove_item(uuid4())
    with pytest.raises(DatasetSnapshotError):
        draft.reorder([uuid4()])
    with pytest.raises(DatasetSnapshotError):
        draft.reorder([])


def test_rejects_the_same_asset_revision_twice() -> None:
    only = item()
    draft = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).add_item(only)

    with pytest.raises(DatasetSnapshotError):
        draft.add_item(only)


def test_an_empty_snapshot_cannot_be_sealed() -> None:
    empty = DatasetSnapshot(id=uuid4(), dataset_id=uuid4()).begin_validation()

    with pytest.raises(DatasetSnapshotError):
        empty.seal(manifest=MANIFEST, sealed_at=SEALED_AT)


@pytest.mark.parametrize(
    "state",
    [DatasetSnapshotState.DRAFT, DatasetSnapshotState.VALIDATING, DatasetSnapshotState.REJECTED],
)
def test_only_a_sealed_snapshot_has_a_manifest_and_a_sealed_at(
    state: DatasetSnapshotState,
) -> None:
    with pytest.raises(DatasetSnapshotError):
        DatasetSnapshot(id=uuid4(), dataset_id=uuid4(), state=state, manifest=MANIFEST)
    with pytest.raises(DatasetSnapshotError):
        DatasetSnapshot(id=uuid4(), dataset_id=uuid4(), state=state, sealed_at=SEALED_AT)


def test_a_sealed_snapshot_without_a_manifest_or_a_sealed_at_cannot_exist() -> None:
    with pytest.raises(DatasetSnapshotError):
        DatasetSnapshot(
            id=uuid4(),
            dataset_id=uuid4(),
            items=(item(),),
            state=DatasetSnapshotState.SEALED,
            sealed_at=SEALED_AT,
        )
    with pytest.raises(DatasetSnapshotError):
        DatasetSnapshot(
            id=uuid4(),
            dataset_id=uuid4(),
            items=(item(),),
            state=DatasetSnapshotState.SEALED,
            manifest=MANIFEST,
        )


def test_a_caller_cannot_reach_into_a_sealed_snapshots_items() -> None:
    """The snapshot copies what it was given, so an outside list cannot reorder it."""

    given = [item(), item()]
    snapshot = DatasetSnapshot(
        id=uuid4(),
        dataset_id=uuid4(),
        items=given,  # type: ignore[arg-type]
        state=DatasetSnapshotState.SEALED,
        manifest=MANIFEST,
        sealed_at=SEALED_AT,
    )
    before = snapshot.items

    given.reverse()

    assert snapshot.items == before


def test_is_immutable() -> None:
    snapshot = snapshot_in(DatasetSnapshotState.DRAFT)

    with pytest.raises(AttributeError):
        snapshot.state = DatasetSnapshotState.SEALED  # type: ignore[misc]


@pytest.mark.parametrize("items", [("not-an-item",), (None,)])
def test_rejects_items_that_are_not_snapshot_items(items: tuple[object, ...]) -> None:
    with pytest.raises(DatasetSnapshotError):
        DatasetSnapshot(id=uuid4(), dataset_id=uuid4(), items=items)  # type: ignore[arg-type]


def test_an_unapproved_caption_needs_a_stated_override_reason() -> None:
    with pytest.raises(SnapshotItemError):
        SnapshotItem(asset_revision_id=uuid4(), caption_revision_id=uuid4(), caption_approved=False)

    override = SnapshotItem(
        asset_revision_id=uuid4(),
        caption_revision_id=uuid4(),
        caption_approved=False,
        caption_override_reason="reviewer accepted the raw WD tags for this pose",
    )

    assert override.caption_override_reason is not None


def test_an_approved_caption_overrides_nothing() -> None:
    with pytest.raises(SnapshotItemError):
        SnapshotItem(
            asset_revision_id=uuid4(),
            caption_revision_id=uuid4(),
            caption_approved=True,
            caption_override_reason="there is nothing being overridden",
        )


@pytest.mark.parametrize("repeats", [0, -1, True, 1.5, "2"])
def test_rejects_repeats_that_cannot_weight_an_item(repeats: object) -> None:
    with pytest.raises(SnapshotItemError):
        SnapshotItem(
            asset_revision_id=uuid4(),
            caption_revision_id=uuid4(),
            caption_approved=True,
            repeats=repeats,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("approved", ["yes", 1, None])
def test_rejects_an_approval_that_is_not_a_decision(approved: object) -> None:
    with pytest.raises(SnapshotItemError):
        SnapshotItem(
            asset_revision_id=uuid4(),
            caption_revision_id=uuid4(),
            caption_approved=approved,  # type: ignore[arg-type]
        )
