"""Valid domain values for the repository tests to store.

Every builder produces something the domain already accepts, so a failing test
is about persistence and not about a rejected constructor. Identifiers are
fresh per call, which is what lets tests share a database without sharing
rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from image_model_lab_domain import (
    Artifact,
    ArtifactNamespace,
    ArtifactProvenance,
    ArtifactReference,
    ArtifactState,
    ArtifactUri,
    DatasetSnapshot,
    ExecutionJob,
    ExecutionJobKind,
    ExecutionJobState,
    MediaType,
    ProvenanceKind,
    RunAttempt,
    Sha256Digest,
    SnapshotItem,
)

STARTED_AT = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 7, 29, 10, 30, tzinfo=UTC)


def digest(seed: str = "c9002e99") -> Sha256Digest:
    """A syntactically valid digest whose first characters are ``seed``."""

    return Sha256Digest(f"{seed}{'0' * (64 - len(seed))}")


def reference(*, key: str | None = None, seed: str = "c9002e99") -> ArtifactReference:
    return ArtifactReference(
        uri=ArtifactUri(
            namespace=ArtifactNamespace.ASSETS,
            key=key if key is not None else f"original/{uuid4().hex}",
        ),
        digest=digest(seed),
        size_bytes=20480,
        media_type=MediaType("image/png"),
    )


def ingested(label: str = "inbox import, scanned negatives batch 12") -> ArtifactProvenance:
    return ArtifactProvenance(
        kind=ProvenanceKind.INGESTED, recorded_at=STARTED_AT, source_label=label
    )


def derived_from(source_id: UUID) -> ArtifactProvenance:
    return ArtifactProvenance(
        kind=ProvenanceKind.DERIVED, recorded_at=ENDED_AT, source_id=source_id
    )


def artifact(
    *,
    artifact_id: UUID | None = None,
    reference_: ArtifactReference | None = None,
    provenance: tuple[ArtifactProvenance, ...] | None = None,
    state: ArtifactState = ArtifactState.PENDING,
) -> Artifact:
    return Artifact(
        id=uuid4() if artifact_id is None else artifact_id,
        reference=reference() if reference_ is None else reference_,
        provenance=(ingested(),) if provenance is None else provenance,
        state=state,
    )


def job(
    *,
    job_id: UUID | None = None,
    kind: ExecutionJobKind = ExecutionJobKind.TRAINING,
    idempotency_key: str | None = None,
    priority: int = 5,
    state: ExecutionJobState = ExecutionJobState.QUEUED,
) -> ExecutionJob:
    return ExecutionJob(
        id=uuid4() if job_id is None else job_id,
        kind=kind,
        idempotency_key=f"train-{uuid4().hex}" if idempotency_key is None else idempotency_key,
        priority=priority,
        state=state,
    )


def attempt(
    job_id: UUID, *, attempt_id: UUID | None = None, number: int = 1, agent_id: UUID | None = None
) -> RunAttempt:
    return RunAttempt(
        id=uuid4() if attempt_id is None else attempt_id,
        job_id=job_id,
        agent_id=uuid4() if agent_id is None else agent_id,
        number=number,
        started_at=STARTED_AT,
    )


def item(*, repeats: int = 1) -> SnapshotItem:
    return SnapshotItem(
        asset_revision_id=uuid4(),
        caption_revision_id=uuid4(),
        caption_approved=True,
        repeats=repeats,
    )


def snapshot(*, items: tuple[SnapshotItem, ...] = ()) -> DatasetSnapshot:
    return DatasetSnapshot(id=uuid4(), dataset_id=uuid4(), items=items)
