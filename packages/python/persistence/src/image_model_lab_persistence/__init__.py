"""PostgreSQL mapping, repositories and migrations for the image model lab.

PostgreSQL is the metadata source of truth and NAS holds the bytes, so this
package stores logical artifact URIs, digests, sizes, media types, provenance
and lifecycle state -- never a machine mount path and never an artifact's
content.

It is the only place SQLAlchemy and Alembic appear outside a service
composition root. The domain package stays framework-free and the application
package states the ports; the adapters here are the downstream end of both.
"""

from typing import Final

from image_model_lab_persistence.engine import (
    DATABASE_URL_VARIABLE,
    create_database_engine,
    create_session_factory,
    require_database_url,
)
from image_model_lab_persistence.errors import DatabaseUrlError, StoredRowInvalid
from image_model_lab_persistence.repositories import (
    SqlAlchemyArtifactRepository,
    SqlAlchemyDatasetSnapshotRepository,
    SqlAlchemyExecutionJobRepository,
    SqlAlchemyRunAttemptRepository,
)
from image_model_lab_persistence.tables import METADATA

PACKAGE_NAME: Final[str] = "image-model-lab-persistence"

__all__ = [
    "DATABASE_URL_VARIABLE",
    "METADATA",
    "PACKAGE_NAME",
    "DatabaseUrlError",
    "SqlAlchemyArtifactRepository",
    "SqlAlchemyDatasetSnapshotRepository",
    "SqlAlchemyExecutionJobRepository",
    "SqlAlchemyRunAttemptRepository",
    "StoredRowInvalid",
    "create_database_engine",
    "create_session_factory",
    "require_database_url",
]
