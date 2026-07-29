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

Provenance -- who wrote the bytes and from what source -- is part of this
entity in `docs/02-domain-model.md` but is not modelled yet. It arrives with
the ingest slice that first has something to record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from image_model_lab_domain.artifacts.errors import ArtifactError
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
    """

    id: UUID
    reference: ArtifactReference
    state: ArtifactState = ArtifactState.PENDING

    def __post_init__(self) -> None:
        require_id(self.id, field="artifact id", error=ArtifactError)
        require_instance(
            self.reference,
            expected=ArtifactReference,
            field="artifact reference",
            error=ArtifactError,
        )
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


__all__ = ["ARTIFACT_TRANSITIONS", "Artifact", "ArtifactState"]
