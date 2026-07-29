"""The artifact entity and its storage lifecycle.

An artifact is one immutable object on NAS. Its address, digest, size and
media type never change -- that is what :class:`ArtifactReference` fixes -- so
the only thing that moves is what the control plane currently knows about the
bytes behind that reference.

Publishing is not one transaction. A writer streams to a temporary key,
verifies size and digest, renames to the final key, and only then can a row
claim the bytes are there. The state records that knowledge:

* ``pending`` -- the row exists, the bytes are not confirmed at the final key;
* ``available`` -- the stored bytes were verified against the digest;
* ``missing`` -- bytes that were available are no longer at the key;
* ``quarantined`` -- the stored bytes contradict the reference, or are for any
  other reason not to be trusted or served.

``quarantined`` is final. The digest is what identifies an artifact, so bytes
that disagree with it can never become this artifact again; a good copy is
published as a new artifact and the quarantined row stays as the evidence a
garbage collection policy decides on. ``missing`` is not final: a repair job
that finds the bytes again and re-verifies the digest returns the artifact to
``available``.

Every artifact also records where its bytes came from. Provenance is captured
when the artifact is created, because the writer is the only one who knows it
and no later pass can reconstruct it.

It is a history rather than one record. Importing bytes that are already
stored writes no second copy, so the second import has nowhere else to be
recorded, and two sources of the same bytes can carry different licence
terms. The history only ever grows: a record already written is never
rewritten or dropped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from image_model_lab_domain.artifacts.errors import ArtifactError
from image_model_lab_domain.artifacts.provenance import ArtifactProvenance
from image_model_lab_domain.artifacts.reference import ArtifactReference
from image_model_lab_domain.lifecycle import require_state, require_transition
from image_model_lab_domain.validation import require_id, require_instance


class ArtifactState(StrEnum):
    """What the control plane knows about an artifact's stored bytes."""

    PENDING = "pending"
    AVAILABLE = "available"
    MISSING = "missing"
    QUARANTINED = "quarantined"


ARTIFACT_TRANSITIONS: Final[Mapping[ArtifactState, frozenset[ArtifactState]]] = MappingProxyType(
    {
        ArtifactState.PENDING: frozenset({ArtifactState.AVAILABLE, ArtifactState.QUARANTINED}),
        ArtifactState.AVAILABLE: frozenset({ArtifactState.MISSING, ArtifactState.QUARANTINED}),
        ArtifactState.MISSING: frozenset({ArtifactState.AVAILABLE, ArtifactState.QUARANTINED}),
        ArtifactState.QUARANTINED: frozenset(),
    }
)
"""Allowed artifact state transitions, keyed by the current state.

The mapping is read-only: a lifecycle that a caller can widen at runtime is
not an invariant.
"""


@dataclass(frozen=True, slots=True)
class Artifact:
    """One immutable stored object, and what is known about its bytes.

    Transitions return a new artifact rather than mutating this one, so a
    caller that still holds the old value keeps reading the state it checked.
    The reference is carried through unchanged, and so is every provenance
    record already written: what the bytes are is settled when the artifact is
    created, and a state change is not a place to revise where they came from.
    """

    id: UUID
    reference: ArtifactReference
    provenance: tuple[ArtifactProvenance, ...]
    state: ArtifactState = ArtifactState.PENDING

    def __post_init__(self) -> None:
        require_id(self.id, field="artifact id", error=ArtifactError)
        require_instance(
            self.reference,
            expected=ArtifactReference,
            field="artifact reference",
            error=ArtifactError,
        )
        object.__setattr__(self, "provenance", _validated_provenance(self.provenance))
        object.__setattr__(
            self,
            "state",
            require_state(
                self.state, states=ArtifactState, subject="artifact state", error=ArtifactError
            ),
        )

    @property
    def is_readable(self) -> bool:
        """Whether the bytes may be served or used as a run input."""

        return self.state is ArtifactState.AVAILABLE

    @property
    def origin(self) -> ArtifactProvenance:
        """The record of the write that first put these bytes on NAS."""

        return self.provenance[0]

    def record_provenance(self, record: ArtifactProvenance) -> Artifact:
        """Append another origin for the same bytes.

        Importing bytes that are already stored does not write a second copy;
        it adds where this copy also came from. Existing records are never
        rewritten, so an artifact accumulates its sources and a licence audit
        can see all of them.

        Raises:
            ArtifactError: if ``record`` is not an
                :class:`ArtifactProvenance`, or is already recorded.
        """

        return replace(self, provenance=(*self.provenance, record))

    def _become(self, target: ArtifactState) -> Artifact:
        require_transition(
            subject="an artifact",
            current=self.state,
            target=target,
            allowed=ARTIFACT_TRANSITIONS,
            error=ArtifactError,
        )
        return replace(self, state=target)

    def mark_available(self) -> Artifact:
        """Record that the stored bytes were verified against the digest.

        This is both the end of a publish and the end of a repair, because the
        check that justifies it is the same one in either case.

        Raises:
            ArtifactError: if the artifact is quarantined or already available.
        """

        return self._become(ArtifactState.AVAILABLE)

    def mark_missing(self) -> Artifact:
        """Record that bytes that were available are no longer at the key.

        Raises:
            ArtifactError: if the artifact was never available.
        """

        return self._become(ArtifactState.MISSING)

    def quarantine(self) -> Artifact:
        """Withdraw the artifact from use without deleting anything.

        Raises:
            ArtifactError: if the artifact is already quarantined.
        """

        return self._become(ArtifactState.QUARANTINED)


def _validated_provenance(
    records: Iterable[ArtifactProvenance],
) -> tuple[ArtifactProvenance, ...]:
    """Copy ``records`` into a tuple, rejecting an empty or repeated history.

    The copy matters: a caller that kept a list could otherwise rewrite an
    artifact's history through its own reference.
    """

    try:
        ordered = tuple(records)
    except TypeError:
        raise ArtifactError(
            "artifact provenance must be a sequence of provenance records, got "
            f"{type(records).__name__}"
        ) from None
    if not ordered:
        raise ArtifactError(
            "an artifact must have at least one provenance record; bytes nobody can trace "
            "cannot explain a training input or a run output"
        )
    seen: list[ArtifactProvenance] = []
    for record in ordered:
        require_instance(
            record,
            expected=ArtifactProvenance,
            field="artifact provenance record",
            error=ArtifactError,
        )
        if record in seen:
            raise ArtifactError(f"artifact provenance record {record} is already recorded")
        seen.append(record)
    return ordered


__all__ = ["ARTIFACT_TRANSITIONS", "Artifact", "ArtifactState"]
