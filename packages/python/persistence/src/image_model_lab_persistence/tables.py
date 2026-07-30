"""Relational mapping for the domain entities that have a lifecycle.

The domain entities are frozen dataclasses that import no framework, so they
are not mapped onto directly. Each has a row class here and an explicit
translation in :mod:`image_model_lab_persistence.mapping`. The extra step buys
the property the architecture rests on: the domain rules can be read and
tested without a database, and the schema can change shape -- a value object
spread across columns, a child list in its own table -- without the entities
being reshaped to suit it.

Three conventions run through the tables.

*Widths and state lists come from the domain.* A column is as wide as the
value object it stores, and a state column's ``CHECK`` lists exactly the
members of the corresponding ``StrEnum``. Restating either by hand is how the
two drift; deriving them means a change in the domain shows up as a schema
change, which is a migration and a test failure rather than a surprise in
production. :mod:`image_model_lab_persistence.tests` checks the deployed
constraints against the live enums for that reason.

*States are text with a ``CHECK``, not a PostgreSQL ``ENUM``.* An enum type
would put the same list in a second place that only DDL can change, and adding
a member to it is awkward inside a transactional migration. Text with a
checked list stores exactly the values the domain writes and is rewritten by
an ordinary ``ALTER TABLE``.

*An artifact reference is embedded, not referenced.* A manifest is described
by the four facts that travel together -- URI, digest, size, media type -- and
the entity holds that value object rather than an artifact id. Storing them as
four columns keeps a run manifest readable even if the artifact row is not
there yet, which is the ordinary case while a publish is still ``pending``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from image_model_lab_domain import (
    ArtifactNamespace,
    ArtifactState,
    DatasetSnapshotState,
    ExecutionJobKind,
    ExecutionJobState,
    ProvenanceKind,
    RunAttemptState,
)
from image_model_lab_domain.artifacts import (
    DIGEST_LENGTH,
    MAX_KEY_LENGTH,
    MAX_SOURCE_LABEL_LENGTH,
    SCHEME,
)
from image_model_lab_domain.artifacts.media_type import MAX_NAME_LENGTH as MAX_MEDIA_TYPE_NAME
from image_model_lab_domain.execution import MAX_IDEMPOTENCY_KEY_LENGTH
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic names for every constraint and index.

Alembic drops a constraint by name, so an unnamed one leaves a downgrade with
nothing to address and a migration that only runs forwards.
"""

MAX_LOGICAL_URI_LENGTH: Final = (
    len(f"{SCHEME}://")
    + max(len(namespace.value) for namespace in ArtifactNamespace)
    + len("/")
    + MAX_KEY_LENGTH
)
"""Longest ``nas://<namespace>/<key>`` the URI value object can produce."""

MAX_MEDIA_TYPE_LENGTH: Final = MAX_MEDIA_TYPE_NAME + len("/") + MAX_MEDIA_TYPE_NAME
"""Longest bare ``<type>/<subtype>``, both names at the RFC 6838 limit."""

MAX_STATE_LENGTH: Final = 32
"""Room for a state or kind value. The longest in the domain is far shorter."""


def _quoted_values(states: type[StrEnum]) -> str:
    """Every member of ``states`` as a sorted SQL string list.

    Sorted so the rendered DDL depends on the set of states and not on the
    order they happen to be declared in, which keeps a reordered enum from
    looking like a schema change.
    """

    return ", ".join(f"'{state.value}'" for state in sorted(states))


def _state_check(column: str, states: type[StrEnum], *, name: str) -> CheckConstraint:
    """Constrain ``column`` to exactly the members of ``states``."""

    return CheckConstraint(f"{column} IN ({_quoted_values(states)})", name=name)


class Base(DeclarativeBase):
    """Declarative base carrying the metadata every migration works against."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


METADATA: Final = Base.metadata
"""The schema Alembic compares a database against."""


class ArtifactReferenceColumns:
    """The four facts that address one stored artifact, as nullable columns.

    Mixed into the rows that carry a manifest. All four are null together or
    present together; the owning table adds the ``CHECK`` that says so, since
    the rule it pairs with -- which states must have a manifest -- is the
    owner's.
    """

    manifest_logical_uri: Mapped[str | None] = mapped_column(String(MAX_LOGICAL_URI_LENGTH))
    manifest_sha256: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    manifest_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    manifest_media_type: Mapped[str | None] = mapped_column(String(MAX_MEDIA_TYPE_LENGTH))


_MANIFEST_COLUMNS: Final = (
    "manifest_logical_uri",
    "manifest_sha256",
    "manifest_size_bytes",
    "manifest_media_type",
)

_MANIFEST_PRESENT: Final = " AND ".join(f"{column} IS NOT NULL" for column in _MANIFEST_COLUMNS)
_MANIFEST_ABSENT: Final = " AND ".join(f"{column} IS NULL" for column in _MANIFEST_COLUMNS)


def _manifest_whole_or_absent() -> CheckConstraint:
    """Three of the four facts do not address anything.

    A new constraint each call: a ``CheckConstraint`` binds to the one table it
    is attached to, so the two tables carrying a manifest each need their own.
    """

    return CheckConstraint(
        f"({_MANIFEST_PRESENT}) OR ({_MANIFEST_ABSENT})", name="manifest_whole_or_absent"
    )


class ArtifactRow(Base):
    """One immutable stored object, and what is known about its bytes."""

    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # The address is unique; the digest is only indexed. A quarantined
    # artifact keeps its row and its digest as the evidence a garbage
    # collection policy reads, and the good copy of those same bytes is
    # published as a new artifact -- so two rows may share a digest, and two
    # rows claiming one address would leave a reader unable to say which bytes
    # it addressed.
    logical_uri: Mapped[str] = mapped_column(String(MAX_LOGICAL_URI_LENGTH), unique=True)
    sha256: Mapped[str] = mapped_column(String(DIGEST_LENGTH), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(MAX_MEDIA_TYPE_LENGTH))
    state: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))

    provenance: Mapped[list[ArtifactProvenanceRow]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="ArtifactProvenanceRow.position",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes_not_negative"),
        _state_check("state", ArtifactState, name="state_is_known"),
    )


class ArtifactProvenanceRow(Base):
    """One recorded origin of an artifact's bytes.

    Ordered by ``position`` and only ever appended to. The first row is the
    write that put the bytes on NAS; later rows are further imports of bytes
    that were already stored, which write no second copy and so have nowhere
    else to be recorded.
    """

    __tablename__ = "artifact_provenance"

    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_label: Mapped[str | None] = mapped_column(String(MAX_SOURCE_LABEL_LENGTH))

    artifact: Mapped[ArtifactRow] = relationship(back_populates="provenance")

    __table_args__ = (
        CheckConstraint("position >= 0", name="position_not_negative"),
        _state_check("kind", ProvenanceKind, name="kind_is_known"),
        CheckConstraint(
            f"CASE WHEN kind = '{ProvenanceKind.INGESTED.value}'"
            " THEN source_label IS NOT NULL AND source_id IS NULL"
            " ELSE source_id IS NOT NULL AND source_label IS NULL END",
            name="source_matches_kind",
        ),
        CheckConstraint("source_id IS DISTINCT FROM artifact_id", name="source_is_not_self"),
    )
    """Bytes from outside the system are named by a label, bytes from inside by
    an id, and an artifact that cites itself has recorded a cycle rather than
    an origin."""


class ExecutionJobRow(Base):
    """A schedulable command, and where it is in the lease protocol."""

    __tablename__ = "execution_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))
    # Unique, so a request delivered twice cannot queue the same command
    # twice, whatever the caller believed about the first delivery.
    idempotency_key: Mapped[str] = mapped_column(String(MAX_IDEMPOTENCY_KEY_LENGTH), unique=True)
    priority: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))

    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_not_negative"),
        _state_check("kind", ExecutionJobKind, name="kind_is_known"),
        _state_check("state", ExecutionJobState, name="state_is_known"),
    )


class RunAttemptRow(ArtifactReferenceColumns, Base):
    """One actual execution of a job by one agent."""

    __tablename__ = "run_attempts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("execution_jobs.id"), index=True)
    agent_id: Mapped[UUID] = mapped_column(Uuid)
    number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))

    __table_args__ = (
        _state_check("state", RunAttemptState, name="state_is_known"),
        CheckConstraint("number >= 1", name="number_starts_at_one"),
        CheckConstraint(
            f"(state = '{RunAttemptState.RUNNING.value}') = (ended_at IS NULL)",
            name="ended_at_matches_state",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ended_at_not_before_started_at"
        ),
        _manifest_whole_or_absent(),
        CheckConstraint(
            f"state <> '{RunAttemptState.SUCCEEDED.value}' OR ({_MANIFEST_PRESENT})",
            name="succeeded_has_manifest",
        ),
        CheckConstraint(
            f"state NOT IN ('{RunAttemptState.RUNNING.value}',"
            f" '{RunAttemptState.ABANDONED.value}') OR ({_MANIFEST_ABSENT})",
            name="unfinalized_has_no_manifest",
        ),
        # Numbering is per job, so a retry cannot reuse a number and quietly
        # take the place of the attempt that already carries that evidence.
        UniqueConstraint("job_id", "number"),
    )
    """A run nobody can reproduce did not succeed, and an attempt nobody was
    left to finalize cannot claim outputs, so the manifest rules are checked
    here as well as in the entity."""


class DatasetSnapshotRow(ArtifactReferenceColumns, Base):
    """A candidate or sealed training input for one dataset."""

    __tablename__ = "dataset_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    state: Mapped[str] = mapped_column(String(MAX_STATE_LENGTH))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[SnapshotItemRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="SnapshotItemRow.position",
        lazy="selectin",
    )

    __table_args__ = (
        _state_check("state", DatasetSnapshotState, name="state_is_known"),
        _manifest_whole_or_absent(),
        CheckConstraint(
            f"(state = '{DatasetSnapshotState.SEALED.value}') = ({_MANIFEST_PRESENT})",
            name="manifest_matches_state",
        ),
        CheckConstraint(
            f"(state = '{DatasetSnapshotState.SEALED.value}') = (sealed_at IS NOT NULL)",
            name="sealed_at_matches_state",
        ),
    )
    """Sealing is what produces the manifest and the instant, so a snapshot has
    both or neither."""


class SnapshotItemRow(Base):
    """One asset revision and the approved caption revision paired with it."""

    __tablename__ = "snapshot_items"

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_revision_id: Mapped[UUID] = mapped_column(Uuid)
    caption_revision_id: Mapped[UUID] = mapped_column(Uuid)
    caption_approved: Mapped[bool] = mapped_column(Boolean)
    repeats: Mapped[int] = mapped_column(Integer)

    snapshot: Mapped[DatasetSnapshotRow] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("position >= 0", name="position_not_negative"),
        CheckConstraint("repeats >= 1", name="repeats_at_least_one"),
        CheckConstraint("caption_approved", name="caption_is_approved"),
        # One asset revision, one item. Weighting an image is what repeats are
        # for; listing it twice would make the manifest ambiguous instead.
        UniqueConstraint("snapshot_id", "asset_revision_id"),
    )
    """``caption_approved`` is stored and checked rather than inferred.

    A snapshot is sealed from approved revisions only, and it has to stay
    explainable after the caption revision it names is superseded: the row
    says the approval existed when the item was added, which is the fact the
    seal rests on."""


__all__ = [
    "METADATA",
    "ArtifactProvenanceRow",
    "ArtifactRow",
    "Base",
    "DatasetSnapshotRow",
    "ExecutionJobRow",
    "RunAttemptRow",
    "SnapshotItemRow",
]
