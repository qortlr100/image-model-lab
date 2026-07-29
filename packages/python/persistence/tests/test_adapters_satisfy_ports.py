"""Every adapter has the shape its port declares.

The ports are :class:`~typing.Protocol` classes, so an adapter satisfies one by
having the methods rather than by inheriting from it. That is what keeps the
dependency pointing inward -- and it also means nothing checks the match at
import time, so a renamed method would only surface wherever the port is
finally used.

Assigning each adapter to a variable annotated with its port makes the type
checker do the checking, and the runtime assertions below fail the same way in
a plain test run.

No database is involved: this is about the interface, not about what the
adapters do with a session.
"""

from __future__ import annotations

from image_model_lab_application import (
    ArtifactRepository,
    DatasetSnapshotRepository,
    ExecutionJobRepository,
    RunAttemptRepository,
)
from image_model_lab_persistence import (
    SqlAlchemyArtifactRepository,
    SqlAlchemyDatasetSnapshotRepository,
    SqlAlchemyExecutionJobRepository,
    SqlAlchemyRunAttemptRepository,
)
from sqlalchemy.orm import Session

PORTS = (
    (ArtifactRepository, SqlAlchemyArtifactRepository),
    (ExecutionJobRepository, SqlAlchemyExecutionJobRepository),
    (RunAttemptRepository, SqlAlchemyRunAttemptRepository),
    (DatasetSnapshotRepository, SqlAlchemyDatasetSnapshotRepository),
)


def test_each_adapter_is_accepted_where_its_port_is_expected() -> None:
    """Checked by the type checker; the call keeps it from being dead code."""

    session = Session()
    artifacts: ArtifactRepository = SqlAlchemyArtifactRepository(session)
    jobs: ExecutionJobRepository = SqlAlchemyExecutionJobRepository(session)
    attempts: RunAttemptRepository = SqlAlchemyRunAttemptRepository(session)
    snapshots: DatasetSnapshotRepository = SqlAlchemyDatasetSnapshotRepository(session)

    assert [artifacts, jobs, attempts, snapshots]


def test_no_port_method_is_missing_from_its_adapter() -> None:
    for port, adapter in PORTS:
        declared = {
            name
            for name in vars(port)
            if not name.startswith("_") and callable(getattr(port, name, None))
        }
        missing = sorted(name for name in declared if not hasattr(adapter, name))

        assert not missing, f"{adapter.__name__} is missing {missing} from {port.__name__}"
