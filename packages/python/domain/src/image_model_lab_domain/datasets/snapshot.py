"""The dataset snapshot entity and its sealing lifecycle.

A snapshot is the exact training input a run consumed: which asset revisions,
with which caption revisions, in which order, repeated how often. A training
result is only explainable if that list cannot move afterwards, so a snapshot
is assembled once and then sealed:

``draft -> validating -> sealed``, or ``draft``/``validating -> rejected``.

Items may only change in ``draft``. Once validation starts, the list being
checked is the list that will be sealed -- adding an item afterwards would
seal something that was never validated. ``sealed`` and ``rejected`` are
final: a mistake in a sealed snapshot is corrected by building a new snapshot,
never by editing this one, because runs already reference its manifest digest.

Sealing requires the manifest artifact whose digest names this exact list.
Canonicalising the manifest and computing that digest is the sealing use
case's work; the entity's rule is that a sealed snapshot without one cannot
exist.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from image_model_lab_domain.artifacts.reference import ArtifactReference
from image_model_lab_domain.datasets.errors import DatasetSnapshotError, SnapshotItemError
from image_model_lab_domain.lifecycle import require_state, require_transition
from image_model_lab_domain.validation import (
    require_bool,
    require_id,
    require_instance,
    require_instant,
    require_int,
)


class DatasetSnapshotState(StrEnum):
    """Where a snapshot is between assembly and a sealed training input."""

    DRAFT = "draft"
    VALIDATING = "validating"
    SEALED = "sealed"
    REJECTED = "rejected"


DATASET_SNAPSHOT_TRANSITIONS: Final[
    Mapping[DatasetSnapshotState, frozenset[DatasetSnapshotState]]
] = MappingProxyType(
    {
        DatasetSnapshotState.DRAFT: frozenset(
            {DatasetSnapshotState.VALIDATING, DatasetSnapshotState.REJECTED}
        ),
        DatasetSnapshotState.VALIDATING: frozenset(
            {DatasetSnapshotState.SEALED, DatasetSnapshotState.REJECTED}
        ),
        DatasetSnapshotState.SEALED: frozenset(),
        DatasetSnapshotState.REJECTED: frozenset(),
    }
)
"""Allowed dataset snapshot state transitions, keyed by the current state.

The mapping is read-only: a lifecycle that a caller can widen at runtime is
not an invariant.
"""


@dataclass(frozen=True, slots=True)
class SnapshotItem:
    """One asset revision and the approved caption revision paired with it.

    ``caption_approved`` has to be stated and has to be true. A snapshot is
    sealed from approved revisions only, so an unapproved caption has no way
    into one -- there is no override, and a caption that needs an exception
    needs a review instead.

    It is recorded rather than merely checked because a sealed snapshot has to
    stay explainable after the caption revision it names is superseded: the
    item says the approval existed when the item was added, which is the fact
    the seal rests on.
    """

    asset_revision_id: UUID
    caption_revision_id: UUID
    caption_approved: bool
    repeats: int = 1

    def __post_init__(self) -> None:
        require_id(
            self.asset_revision_id, field="snapshot item asset revision id", error=SnapshotItemError
        )
        require_id(
            self.caption_revision_id,
            field="snapshot item caption revision id",
            error=SnapshotItemError,
        )
        require_bool(
            self.caption_approved,
            field="snapshot item caption_approved",
            error=SnapshotItemError,
        )
        require_int(self.repeats, field="snapshot item repeats", error=SnapshotItemError, minimum=1)
        if not self.caption_approved:
            raise SnapshotItemError(
                "a snapshot item's caption revision must be approved; a snapshot is sealed "
                "from approved revisions only, so an exception is a review that has not "
                "happened yet rather than an item to record"
            )


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """A candidate or sealed training input for one dataset.

    Every change returns a new snapshot rather than mutating this one, and a
    sealed snapshot refuses every change, so a reference held next to a run
    manifest keeps meaning what it meant when the run started.
    """

    id: UUID
    dataset_id: UUID
    items: tuple[SnapshotItem, ...] = ()
    state: DatasetSnapshotState = DatasetSnapshotState.DRAFT
    manifest: ArtifactReference | None = None
    sealed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_id(self.id, field="dataset snapshot id", error=DatasetSnapshotError)
        require_id(self.dataset_id, field="dataset snapshot dataset id", error=DatasetSnapshotError)
        object.__setattr__(self, "items", _validated_items(self.items))
        object.__setattr__(
            self,
            "state",
            require_state(
                self.state,
                states=DatasetSnapshotState,
                subject="dataset snapshot state",
                error=DatasetSnapshotError,
            ),
        )
        self._validate_sealing()

    def _validate_sealing(self) -> None:
        if self.state is not DatasetSnapshotState.SEALED:
            if self.manifest is not None:
                raise DatasetSnapshotError(
                    f"a {self.state.value} dataset snapshot must not have a manifest; "
                    "the manifest is what sealing produces"
                )
            if self.sealed_at is not None:
                raise DatasetSnapshotError(
                    f"a {self.state.value} dataset snapshot must not have a sealed_at"
                )
            return

        if not self.items:
            raise DatasetSnapshotError("a sealed dataset snapshot must have at least one item")
        if self.manifest is None:
            raise DatasetSnapshotError(
                "a sealed dataset snapshot must have the manifest whose digest names it"
            )
        require_instance(
            self.manifest,
            expected=ArtifactReference,
            field="dataset snapshot manifest",
            error=DatasetSnapshotError,
        )
        if self.sealed_at is None:
            raise DatasetSnapshotError("a sealed dataset snapshot must have a sealed_at")
        object.__setattr__(
            self,
            "sealed_at",
            require_instant(
                self.sealed_at, field="dataset snapshot sealed_at", error=DatasetSnapshotError
            ),
        )

    @property
    def is_sealed(self) -> bool:
        """Whether the snapshot is a fixed training input."""

        return self.state is DatasetSnapshotState.SEALED

    def _require_draft(self, change: str) -> None:
        if self.state is DatasetSnapshotState.DRAFT:
            return
        raise DatasetSnapshotError(
            f"a {self.state.value} dataset snapshot cannot {change}; only a draft snapshot "
            "changes its items, and a correction is a new snapshot"
        )

    def add_item(self, item: SnapshotItem) -> DatasetSnapshot:
        """Append an item to a draft snapshot.

        Raises:
            DatasetSnapshotError: if the snapshot is not a draft, if ``item``
                is not a :class:`SnapshotItem`, or if its asset revision is
                already in the snapshot.
        """

        self._require_draft("add an item")
        return replace(self, items=(*self.items, item))

    def remove_item(self, asset_revision_id: UUID) -> DatasetSnapshot:
        """Drop the item for ``asset_revision_id`` from a draft snapshot.

        Raises:
            DatasetSnapshotError: if the snapshot is not a draft, or no item
                names that asset revision.
        """

        self._require_draft("remove an item")
        kept = tuple(item for item in self.items if item.asset_revision_id != asset_revision_id)
        if len(kept) == len(self.items):
            raise DatasetSnapshotError(
                f"dataset snapshot has no item for asset revision {asset_revision_id}"
            )
        return replace(self, items=kept)

    def reorder(self, asset_revision_ids: Sequence[UUID]) -> DatasetSnapshot:
        """Put a draft snapshot's items in the given order.

        Order is part of the sealed input, so a reorder must name every item
        exactly once rather than move some and leave the rest implicit.

        Raises:
            DatasetSnapshotError: if the snapshot is not a draft, or the given
                identifiers are not exactly the snapshot's asset revisions.
        """

        self._require_draft("reorder its items")
        by_asset = {item.asset_revision_id: item for item in self.items}
        requested = list(asset_revision_ids)
        if len(requested) != len(by_asset) or set(requested) != set(by_asset):
            raise DatasetSnapshotError(
                f"a reorder must name each of the {len(by_asset)} asset revisions in the "
                f"dataset snapshot exactly once, got {len(requested)} identifier(s)"
            )
        return replace(self, items=tuple(by_asset[asset_id] for asset_id in requested))

    def _require_transition(self, target: DatasetSnapshotState) -> None:
        require_transition(
            subject="a dataset snapshot",
            current=self.state,
            target=target,
            allowed=DATASET_SNAPSHOT_TRANSITIONS,
            error=DatasetSnapshotError,
        )

    def begin_validation(self) -> DatasetSnapshot:
        """Freeze the item list and start checking it.

        Raises:
            DatasetSnapshotError: if the snapshot is not a draft.
        """

        self._require_transition(DatasetSnapshotState.VALIDATING)
        return replace(self, state=DatasetSnapshotState.VALIDATING)

    def seal(self, *, manifest: ArtifactReference, sealed_at: datetime) -> DatasetSnapshot:
        """Fix the snapshot as a training input, named by ``manifest``.

        Raises:
            DatasetSnapshotError: if the snapshot is not being validated, has
                no items, or ``sealed_at`` is not an instant.
        """

        self._require_transition(DatasetSnapshotState.SEALED)
        return replace(
            self, state=DatasetSnapshotState.SEALED, manifest=manifest, sealed_at=sealed_at
        )

    def reject(self) -> DatasetSnapshot:
        """Abandon the snapshot without sealing it.

        Raises:
            DatasetSnapshotError: if the snapshot is already sealed or
                rejected.
        """

        self._require_transition(DatasetSnapshotState.REJECTED)
        return replace(self, state=DatasetSnapshotState.REJECTED)


def _validated_items(items: Iterable[SnapshotItem]) -> tuple[SnapshotItem, ...]:
    """Copy ``items`` into a tuple, rejecting a repeated asset revision.

    The copy matters: a caller that kept a list would otherwise still be able
    to reorder a sealed snapshot's items through its own reference.
    """

    try:
        ordered = tuple(items)
    except TypeError:
        raise DatasetSnapshotError(
            f"dataset snapshot items must be a sequence, got {type(items).__name__}"
        ) from None
    seen: set[UUID] = set()
    for item in ordered:
        require_instance(
            item, expected=SnapshotItem, field="dataset snapshot item", error=DatasetSnapshotError
        )
        if item.asset_revision_id in seen:
            raise DatasetSnapshotError(
                f"asset revision {item.asset_revision_id} appears twice in the dataset "
                "snapshot; use repeats to weight one item"
            )
        seen.add(item.asset_revision_id)
    return ordered


__all__ = [
    "DATASET_SNAPSHOT_TRANSITIONS",
    "DatasetSnapshot",
    "DatasetSnapshotState",
    "SnapshotItem",
]
