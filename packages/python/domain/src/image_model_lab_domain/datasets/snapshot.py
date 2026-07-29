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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
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
    require_text,
)

MAX_OVERRIDE_REASON_LENGTH: Final = 500
"""Maximum length of a caption override reason, in characters."""


class DatasetSnapshotState(StrEnum):
    """Where a snapshot is between assembly and a sealed training input."""

    DRAFT = "draft"
    VALIDATING = "validating"
    SEALED = "sealed"
    REJECTED = "rejected"


DATASET_SNAPSHOT_TRANSITIONS: Final[dict[DatasetSnapshotState, frozenset[DatasetSnapshotState]]] = {
    DatasetSnapshotState.DRAFT: frozenset(
        {DatasetSnapshotState.VALIDATING, DatasetSnapshotState.REJECTED}
    ),
    DatasetSnapshotState.VALIDATING: frozenset(
        {DatasetSnapshotState.SEALED, DatasetSnapshotState.REJECTED}
    ),
    DatasetSnapshotState.SEALED: frozenset(),
    DatasetSnapshotState.REJECTED: frozenset(),
}
"""Allowed dataset snapshot state transitions, keyed by the current state."""


@dataclass(frozen=True, slots=True)
class SnapshotItem:
    """One asset revision and the caption revision paired with it.

    ``caption_approved`` is the approval as it stood when the item was added,
    recorded rather than looked up, because a sealed snapshot has to stay
    explainable after the caption revision it names is superseded.

    An unapproved caption needs ``caption_override_reason``: including one is
    a deliberate exception, and an exception with no stated reason is
    indistinguishable from a review that was skipped by accident.
    """

    asset_revision_id: UUID
    caption_revision_id: UUID
    caption_approved: bool
    repeats: int = 1
    caption_override_reason: str | None = None

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
        if self.caption_override_reason is not None:
            require_text(
                self.caption_override_reason,
                field="snapshot item caption override reason",
                error=SnapshotItemError,
                max_length=MAX_OVERRIDE_REASON_LENGTH,
            )
        if not self.caption_approved and self.caption_override_reason is None:
            raise SnapshotItemError(
                "a snapshot item whose caption is not approved needs a caption override "
                "reason; an unreviewed caption does not enter a training input silently"
            )
        if self.caption_approved and self.caption_override_reason is not None:
            raise SnapshotItemError(
                "a snapshot item with an approved caption must not carry an override "
                "reason; there is nothing being overridden"
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

    ordered = tuple(items)
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
    "MAX_OVERRIDE_REASON_LENGTH",
    "DatasetSnapshot",
    "DatasetSnapshotState",
    "SnapshotItem",
]
