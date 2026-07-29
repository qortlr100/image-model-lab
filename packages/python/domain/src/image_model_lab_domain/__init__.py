"""Framework-independent domain package for the image model lab."""

from typing import Final

from image_model_lab_domain.artifacts import (
    ARTIFACT_TRANSITIONS,
    Artifact,
    ArtifactError,
    ArtifactNamespace,
    ArtifactReference,
    ArtifactReferenceError,
    ArtifactState,
    ArtifactUri,
    ArtifactUriError,
    DigestError,
    MediaType,
    MediaTypeError,
    Sha256Digest,
)
from image_model_lab_domain.datasets import (
    DATASET_SNAPSHOT_TRANSITIONS,
    DatasetSnapshot,
    DatasetSnapshotError,
    DatasetSnapshotState,
    SnapshotItem,
    SnapshotItemError,
)
from image_model_lab_domain.errors import DomainError
from image_model_lab_domain.execution import (
    EXECUTION_JOB_TRANSITIONS,
    RUN_ATTEMPT_TRANSITIONS,
    ExecutionJob,
    ExecutionJobError,
    ExecutionJobKind,
    ExecutionJobState,
    RunAttempt,
    RunAttemptError,
    RunAttemptState,
)

PACKAGE_NAME: Final[str] = "image-model-lab-domain"

__all__ = [
    "ARTIFACT_TRANSITIONS",
    "DATASET_SNAPSHOT_TRANSITIONS",
    "EXECUTION_JOB_TRANSITIONS",
    "PACKAGE_NAME",
    "RUN_ATTEMPT_TRANSITIONS",
    "Artifact",
    "ArtifactError",
    "ArtifactNamespace",
    "ArtifactReference",
    "ArtifactReferenceError",
    "ArtifactState",
    "ArtifactUri",
    "ArtifactUriError",
    "DatasetSnapshot",
    "DatasetSnapshotError",
    "DatasetSnapshotState",
    "DigestError",
    "DomainError",
    "ExecutionJob",
    "ExecutionJobError",
    "ExecutionJobKind",
    "ExecutionJobState",
    "MediaType",
    "MediaTypeError",
    "RunAttempt",
    "RunAttemptError",
    "RunAttemptState",
    "Sha256Digest",
    "SnapshotItem",
    "SnapshotItemError",
]
