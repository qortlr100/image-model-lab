"""Where an artifact's bytes came from.

An artifact that nobody can trace is not evidence. A training input has to
name the import it came from, a checkpoint the attempt that wrote it, and a
thumbnail the artifact it was derived from -- otherwise a finished run cannot
be explained after the fact, and provenance cannot be reconstructed later
because the knowledge only exists at the moment of writing.

The three origins an artifact can have are different in kind, so each carries
a different reference:

* ``ingested`` -- the bytes came from outside the system, so there is no
  in-system identifier to point at, only a label describing the source;
* ``derived`` -- produced from another artifact, named by that artifact's id;
* ``run_output`` -- written by one execution, named by that run attempt's id.

A machine path anywhere in a label is refused, however it is introduced,
because ``copied from /mnt/nas/inbox/a.png`` and ``source=/mnt/...`` leak the
same mount root that a bare path would. Where a file happened to sit on one
machine is not what the source was, and a mount path must not reach the
domain or the database. A remote URL is still a usable label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from image_model_lab_domain.artifacts.errors import ArtifactProvenanceError
from image_model_lab_domain.lifecycle import require_state
from image_model_lab_domain.validation import require_id, require_instant, require_text

MAX_SOURCE_LABEL_LENGTH: Final = 500
"""Maximum length of an ingest source label, in characters."""

_MACHINE_PATH: Final = re.compile(
    r"""
      (?<![A-Za-z0-9:/])/          # a POSIX absolute path, wherever it starts
    | (?<=:)/(?!/)                 # one introduced by a colon, unlike a scheme's '://'
    | \\                           # any backslash: a Windows separator or UNC prefix
    | (?<![A-Za-z])[A-Za-z]:[\\/]  # a Windows drive, but not a URL scheme's ':/'
    | file://                      # a local path wearing a URL
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""A machine path anywhere in a label, however it is introduced.

``copied from /mnt/nas/inbox/a.png``, ``source=/mnt/...``,
``(/srv/import/a.png)`` and ``source:/mnt/...`` all leak the same mount root
that a bare path would, so a leading slash is judged by what precedes it: a
path starts where the preceding character is not part of one, and a colon
introduces a path unless it is a scheme's ``://``.

That leaves a remote URL alone. Its slashes follow a scheme's ``//``, another
slash, or a hostname character, so ``https://example.org/gallery/42`` and a
date like ``2026/07`` still describe real external sources.
"""


class ProvenanceKind(StrEnum):
    """How an artifact's bytes came to exist."""

    INGESTED = "ingested"
    DERIVED = "derived"
    RUN_OUTPUT = "run_output"


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """The origin recorded with an artifact when its bytes were written.

    ``source_id`` names the artifact or run attempt the bytes came from, and
    ``source_label`` describes an external origin that has no identifier here.
    Exactly one of them fits any given kind, so a record can never claim both
    an in-system parent and an outside source.
    """

    kind: ProvenanceKind
    recorded_at: datetime
    source_id: UUID | None = None
    source_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            require_state(
                self.kind,
                states=ProvenanceKind,
                subject="artifact provenance kind",
                error=ArtifactProvenanceError,
            ),
        )
        object.__setattr__(
            self,
            "recorded_at",
            require_instant(
                self.recorded_at,
                field="artifact provenance recorded_at",
                error=ArtifactProvenanceError,
            ),
        )
        self._validate_source()

    def _validate_source(self) -> None:
        if self.kind is ProvenanceKind.INGESTED:
            if self.source_label is None:
                raise ArtifactProvenanceError(
                    "ingested artifact provenance needs a source label; bytes from outside "
                    "the system have no identifier here to name them by"
                )
            if self.source_id is not None:
                raise ArtifactProvenanceError(
                    "ingested artifact provenance must not have a source id; the bytes came "
                    "from outside the system"
                )
            self._validate_label(self.source_label)
            return

        if self.source_id is None:
            raise ArtifactProvenanceError(
                f"{self.kind.value} artifact provenance needs the source id of the "
                "artifact or run attempt the bytes came from"
            )
        require_id(
            self.source_id, field="artifact provenance source id", error=ArtifactProvenanceError
        )
        if self.source_label is not None:
            raise ArtifactProvenanceError(
                f"{self.kind.value} artifact provenance must not have a source label; its "
                "origin is inside the system and is named by the source id"
            )

    def _validate_label(self, label: str) -> None:
        require_text(
            label,
            field="artifact provenance source label",
            error=ArtifactProvenanceError,
            max_length=MAX_SOURCE_LABEL_LENGTH,
        )
        if _MACHINE_PATH.search(label):
            raise ArtifactProvenanceError(
                f"artifact provenance source label {label!r} contains a machine path; "
                "record what the source was, not where one machine kept it"
            )


__all__ = ["MAX_SOURCE_LABEL_LENGTH", "ArtifactProvenance", "ProvenanceKind"]
