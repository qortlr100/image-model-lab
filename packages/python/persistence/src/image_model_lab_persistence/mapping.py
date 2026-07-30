"""Translation between domain entities and their rows.

The translation is written out rather than inferred. A generic mapper would
have to be told the same things -- that a state is stored as its value, that a
reference is four columns, that a child list is ordered by an explicit
position -- and would hide the one place a reader looks to see what a column
means.

Reading goes back through the entity constructors, so a row that violates an
invariant is refused on the way out with the same error a caller would have
got on the way in. That matters after a restore or a hand-edit: the store is
not a second source of truth for the rules, and a snapshot that lost its
manifest is a failure to load rather than a sealed snapshot with no manifest.
"""

from __future__ import annotations

from collections.abc import Sequence

from image_model_lab_domain import (
    Artifact,
    ArtifactProvenance,
    ArtifactReference,
    ArtifactState,
    ArtifactUri,
    DatasetSnapshot,
    DatasetSnapshotState,
    ExecutionJob,
    ExecutionJobKind,
    ExecutionJobState,
    MediaType,
    ProvenanceKind,
    RunAttempt,
    RunAttemptState,
    Sha256Digest,
    SnapshotItem,
)

from image_model_lab_persistence.errors import StoredRowInvalid
from image_model_lab_persistence.tables import (
    ArtifactProvenanceRow,
    ArtifactReferenceColumns,
    ArtifactRow,
    DatasetSnapshotRow,
    ExecutionJobRow,
    RunAttemptRow,
    SnapshotItemRow,
)


def write_manifest(row: ArtifactReferenceColumns, manifest: ArtifactReference | None) -> None:
    """Spread ``manifest`` across the row's four manifest columns, or clear them."""

    row.manifest_logical_uri = None if manifest is None else str(manifest.uri)
    row.manifest_sha256 = None if manifest is None else manifest.digest.hex
    row.manifest_size_bytes = None if manifest is None else manifest.size_bytes
    row.manifest_media_type = None if manifest is None else manifest.media_type.value


def read_manifest(row: ArtifactReferenceColumns) -> ArtifactReference | None:
    """Rebuild the reference from the row's four manifest columns.

    A row with some of them set is a schema the ``CHECK`` was supposed to
    prevent, so it is reported as the broken row it is rather than loaded as a
    reference with holes in it.
    """

    present = (
        row.manifest_logical_uri,
        row.manifest_sha256,
        row.manifest_size_bytes,
        row.manifest_media_type,
    )
    if all(value is None for value in present):
        return None
    if (
        row.manifest_logical_uri is None
        or row.manifest_sha256 is None
        or row.manifest_size_bytes is None
        or row.manifest_media_type is None
    ):
        raise StoredRowInvalid(
            "stored manifest is partial; a reference addresses an artifact with all four "
            "of its URI, digest, size and media type"
        )
    return ArtifactReference(
        uri=ArtifactUri.parse(row.manifest_logical_uri),
        digest=Sha256Digest(row.manifest_sha256),
        size_bytes=row.manifest_size_bytes,
        media_type=MediaType(row.manifest_media_type),
    )


def provenance_row(record: ArtifactProvenance, *, position: int) -> ArtifactProvenanceRow:
    """Build the row for one provenance record at ``position`` in the history."""

    return ArtifactProvenanceRow(
        position=position,
        kind=record.kind.value,
        recorded_at=record.recorded_at,
        source_id=record.source_id,
        source_label=record.source_label,
    )


def read_provenance(row: ArtifactProvenanceRow) -> ArtifactProvenance:
    """Rebuild one provenance record from its row."""

    return ArtifactProvenance(
        kind=ProvenanceKind(row.kind),
        recorded_at=row.recorded_at,
        source_id=row.source_id,
        source_label=row.source_label,
    )


def artifact_row(artifact: Artifact) -> ArtifactRow:
    """Build the row and the whole provenance history for a new artifact."""

    reference = artifact.reference
    return ArtifactRow(
        id=artifact.id,
        logical_uri=str(reference.uri),
        sha256=reference.digest.hex,
        size_bytes=reference.size_bytes,
        media_type=reference.media_type.value,
        state=artifact.state.value,
        provenance=[
            provenance_row(record, position=position)
            for position, record in enumerate(artifact.provenance)
        ],
    )


def read_artifact(row: ArtifactRow) -> Artifact:
    """Rebuild an artifact and its provenance history from its rows."""

    return Artifact(
        id=row.id,
        reference=ArtifactReference(
            uri=ArtifactUri.parse(row.logical_uri),
            digest=Sha256Digest(row.sha256),
            size_bytes=row.size_bytes,
            media_type=MediaType(row.media_type),
        ),
        provenance=tuple(read_provenance(record) for record in row.provenance),
        state=ArtifactState(row.state),
    )


def execution_job_row(job: ExecutionJob) -> ExecutionJobRow:
    """Build the row for a new execution job."""

    return ExecutionJobRow(
        id=job.id,
        kind=job.kind.value,
        idempotency_key=job.idempotency_key,
        priority=job.priority,
        state=job.state.value,
    )


def read_execution_job(row: ExecutionJobRow) -> ExecutionJob:
    """Rebuild an execution job from its row."""

    return ExecutionJob(
        id=row.id,
        kind=ExecutionJobKind(row.kind),
        idempotency_key=row.idempotency_key,
        priority=row.priority,
        state=ExecutionJobState(row.state),
    )


def run_attempt_row(attempt: RunAttempt) -> RunAttemptRow:
    """Build the row for a new run attempt."""

    row = RunAttemptRow(
        id=attempt.id,
        job_id=attempt.job_id,
        agent_id=attempt.agent_id,
        number=attempt.number,
        started_at=attempt.started_at,
        ended_at=attempt.ended_at,
        state=attempt.state.value,
    )
    write_manifest(row, attempt.manifest)
    return row


def read_run_attempt(row: RunAttemptRow) -> RunAttempt:
    """Rebuild a run attempt from its row."""

    return RunAttempt(
        id=row.id,
        job_id=row.job_id,
        agent_id=row.agent_id,
        number=row.number,
        started_at=row.started_at,
        state=RunAttemptState(row.state),
        ended_at=row.ended_at,
        manifest=read_manifest(row),
    )


def snapshot_item_row(item: SnapshotItem, *, position: int) -> SnapshotItemRow:
    """Build the row for one snapshot item at ``position`` in the ordered list."""

    return SnapshotItemRow(
        position=position,
        asset_revision_id=item.asset_revision_id,
        caption_revision_id=item.caption_revision_id,
        caption_approved=item.caption_approved,
        repeats=item.repeats,
    )


def read_snapshot_item(row: SnapshotItemRow) -> SnapshotItem:
    """Rebuild one snapshot item from its row."""

    return SnapshotItem(
        asset_revision_id=row.asset_revision_id,
        caption_revision_id=row.caption_revision_id,
        caption_approved=row.caption_approved,
        repeats=row.repeats,
    )


def snapshot_item_rows(items: Sequence[SnapshotItem]) -> list[SnapshotItemRow]:
    """Build the ordered item rows for a snapshot.

    Order is part of the sealed input, so it is stored as an explicit position
    rather than left to whatever order a query happens to return.
    """

    return [snapshot_item_row(item, position=position) for position, item in enumerate(items)]


def dataset_snapshot_row(snapshot: DatasetSnapshot) -> DatasetSnapshotRow:
    """Build the row and item rows for a new dataset snapshot."""

    row = DatasetSnapshotRow(
        id=snapshot.id,
        dataset_id=snapshot.dataset_id,
        state=snapshot.state.value,
        sealed_at=snapshot.sealed_at,
        items=snapshot_item_rows(snapshot.items),
    )
    write_manifest(row, snapshot.manifest)
    return row


def read_dataset_snapshot(row: DatasetSnapshotRow) -> DatasetSnapshot:
    """Rebuild a dataset snapshot and its ordered items from its rows."""

    return DatasetSnapshot(
        id=row.id,
        dataset_id=row.dataset_id,
        items=tuple(read_snapshot_item(item) for item in row.items),
        state=DatasetSnapshotState(row.state),
        manifest=read_manifest(row),
        sealed_at=row.sealed_at,
    )


__all__ = [
    "artifact_row",
    "dataset_snapshot_row",
    "execution_job_row",
    "provenance_row",
    "read_artifact",
    "read_dataset_snapshot",
    "read_execution_job",
    "read_manifest",
    "read_provenance",
    "read_run_attempt",
    "read_snapshot_item",
    "run_attempt_row",
    "snapshot_item_row",
    "snapshot_item_rows",
    "write_manifest",
]
