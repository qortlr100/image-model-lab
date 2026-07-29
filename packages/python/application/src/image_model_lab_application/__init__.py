"""Use cases and the ports they reach the outside world through.

This package holds no framework, no SQL and no filesystem access. It states
what a use case needs a store to do; the persistence package supplies it.
"""

from typing import Final

from image_model_lab_application.errors import (
    ApplicationError,
    RecordAlreadyExists,
    RecordHistoryRewritten,
    RecordIsFinal,
    RecordNotFound,
    RepositoryError,
)
from image_model_lab_application.ports import (
    ArtifactRepository,
    DatasetSnapshotRepository,
    ExecutionJobRepository,
    RunAttemptRepository,
)

PACKAGE_NAME: Final[str] = "image-model-lab-application"

__all__ = [
    "PACKAGE_NAME",
    "ApplicationError",
    "ArtifactRepository",
    "DatasetSnapshotRepository",
    "ExecutionJobRepository",
    "RecordAlreadyExists",
    "RecordHistoryRewritten",
    "RecordIsFinal",
    "RecordNotFound",
    "RepositoryError",
    "RunAttemptRepository",
]
