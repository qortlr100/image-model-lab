"""SQLAlchemy adapters for the repository ports.

Each adapter is constructed with a :class:`~sqlalchemy.orm.Session` and writes
through it without committing. The composition root owns the transaction,
because one use case usually touches more than one aggregate and a commit in
the middle of it would publish a state no rule was checked against.

Writes flush, though. A flush is what turns a duplicate key or a broken
``CHECK`` into an error the caller can still do something about, instead of
one that surfaces at commit time with no context left about which write caused
it.

Three writes are guarded beyond what the constraints say, and all three guard
the same thing: a record that is finished must not be quietly replaced.
Completed run attempts and sealed snapshots are the evidence a finished run is
explained by, and an artifact's provenance is an append-only history. Each
guard reads the stored row ``FOR UPDATE`` first, so two agents reporting at
once queue behind each other rather than both seeing a writable row.
"""

from __future__ import annotations

from uuid import UUID

from image_model_lab_application import (
    RecordAlreadyExists,
    RecordHistoryRewritten,
    RecordIsFinal,
    RecordNotFound,
)
from image_model_lab_domain import (
    DATASET_SNAPSHOT_TRANSITIONS,
    Artifact,
    DatasetSnapshot,
    DatasetSnapshotState,
    ExecutionJob,
    RunAttempt,
    RunAttemptState,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from image_model_lab_persistence.mapping import (
    artifact_row,
    dataset_snapshot_row,
    execution_job_row,
    provenance_row,
    read_artifact,
    read_dataset_snapshot,
    read_execution_job,
    read_provenance,
    read_run_attempt,
    run_attempt_row,
    snapshot_item_rows,
    write_manifest,
)
from image_model_lab_persistence.tables import (
    ArtifactRow,
    DatasetSnapshotRow,
    ExecutionJobRow,
    RunAttemptRow,
)

UNIQUE_VIOLATION = "23505"
"""PostgreSQL SQLSTATE for a duplicate key."""

FOREIGN_KEY_VIOLATION = "23503"
"""PostgreSQL SQLSTATE for a reference to a row that is not there."""

FINAL_SNAPSHOT_STATES = frozenset(
    state.value for state, targets in DATASET_SNAPSHOT_TRANSITIONS.items() if not targets
)
"""Snapshot states that never change again, whatever an update carries.

Read off the lifecycle table rather than listed here, so a state that becomes
final in the domain becomes unwritable here without anyone remembering to.
"""


def _sqlstate(error: IntegrityError) -> str | None:
    """The SQLSTATE the driver reported, if it reported one.

    Read from the driver's exception rather than the message: the message is
    localised and reworded between server versions, and a repository that
    decides what happened by matching on English text is one upgrade away from
    reporting the wrong thing.
    """

    return getattr(error.orig, "sqlstate", None)


def _translate(error: IntegrityError, *, subject: str) -> Exception:
    """Turn a driver integrity error into one the caller's port declares."""

    sqlstate = _sqlstate(error)
    if sqlstate == UNIQUE_VIOLATION:
        return RecordAlreadyExists(f"a stored {subject} already claims that identity")
    if sqlstate == FOREIGN_KEY_VIOLATION:
        return RecordNotFound(f"the {subject} refers to a record that does not exist")
    # A broken CHECK means the domain let through something the schema
    # refuses, which is a rule disagreeing with itself rather than anything a
    # use case can retry. It travels on as the integrity error it is.
    return error


class SqlAlchemyArtifactRepository:
    """Artifacts and the append-only history of where their bytes came from."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, artifact: Artifact) -> None:
        self._session.add(artifact_row(artifact))
        try:
            self._session.flush()
        except IntegrityError as error:
            raise _translate(error, subject="artifact") from error

    def get(self, artifact_id: UUID) -> Artifact:
        return read_artifact(self._row(artifact_id))

    def update(self, artifact: Artifact) -> None:
        # The reference is not written back. Address, digest, size and media
        # type are what identify an artifact, and a transition returns the
        # same reference, so the only thing an update can carry is the state
        # and whatever provenance the artifact has gained.
        row = self._row(artifact.id, for_update=True)
        self._append_provenance(row, artifact)
        row.state = artifact.state.value
        self._session.flush()

    def _row(self, artifact_id: UUID, *, for_update: bool = False) -> ArtifactRow:
        row = self._session.get(ArtifactRow, artifact_id, with_for_update=for_update)
        if row is None:
            raise RecordNotFound(f"no artifact has the id {artifact_id}")
        return row

    @staticmethod
    def _append_provenance(row: ArtifactRow, artifact: Artifact) -> None:
        """Extend the stored history with the records the artifact has gained.

        The stored prefix is compared rather than trusted. An update carries a
        whole entity, so a caller that rebuilt one from somewhere else could
        otherwise replace an origin already written -- and a licence audit
        reads exactly those records.
        """

        stored = tuple(read_provenance(record) for record in row.provenance)
        if len(artifact.provenance) < len(stored):
            raise RecordHistoryRewritten(
                f"artifact {artifact.id} is stored with {len(stored)} provenance record(s) "
                f"and the update carries {len(artifact.provenance)}; the history only grows"
            )
        if artifact.provenance[: len(stored)] != stored:
            raise RecordHistoryRewritten(
                f"artifact {artifact.id} would have a provenance record rewritten; an origin "
                "already recorded is never revised, and a further import is appended"
            )
        for position in range(len(stored), len(artifact.provenance)):
            row.provenance.append(provenance_row(artifact.provenance[position], position=position))


class SqlAlchemyExecutionJobRepository:
    """Schedulable commands and where each is in the lease protocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: ExecutionJob) -> None:
        self._session.add(execution_job_row(job))
        try:
            self._session.flush()
        except IntegrityError as error:
            raise _translate(error, subject="execution job") from error

    def get(self, job_id: UUID) -> ExecutionJob:
        return read_execution_job(self._row(job_id))

    def update(self, job: ExecutionJob) -> None:
        # Kind and idempotency key are not rewritten: they say which command
        # this is, and a write that changed them would be describing a
        # different job under an existing id.
        row = self._row(job.id, for_update=True)
        row.state = job.state.value
        row.priority = job.priority
        self._session.flush()

    def find_by_idempotency_key(self, idempotency_key: str) -> ExecutionJob | None:
        row = self._session.scalars(
            select(ExecutionJobRow).where(ExecutionJobRow.idempotency_key == idempotency_key)
        ).one_or_none()
        return None if row is None else read_execution_job(row)

    def _row(self, job_id: UUID, *, for_update: bool = False) -> ExecutionJobRow:
        row = self._session.get(ExecutionJobRow, job_id, with_for_update=for_update)
        if row is None:
            raise RecordNotFound(f"no execution job has the id {job_id}")
        return row


class SqlAlchemyRunAttemptRepository:
    """What each execution of a job actually did."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: RunAttempt) -> None:
        self._session.add(run_attempt_row(attempt))
        try:
            self._session.flush()
        except IntegrityError as error:
            raise _translate(error, subject="run attempt") from error

    def get(self, attempt_id: UUID) -> RunAttempt:
        row = self._session.get(RunAttemptRow, attempt_id)
        if row is None:
            raise RecordNotFound(f"no run attempt has the id {attempt_id}")
        return read_run_attempt(row)

    def complete(self, attempt: RunAttempt) -> None:
        row = self._session.get(RunAttemptRow, attempt.id, with_for_update=True)
        if row is None:
            raise RecordNotFound(f"no run attempt has the id {attempt.id}")
        if row.state != RunAttemptState.RUNNING.value:
            raise RecordIsFinal(
                f"run attempt {attempt.id} already ended as {row.state!r}; a completed "
                "attempt is the evidence for what ran, and a retry is the next attempt"
            )
        row.state = attempt.state.value
        row.ended_at = attempt.ended_at
        write_manifest(row, attempt.manifest)
        self._session.flush()

    def list_for_job(self, job_id: UUID) -> tuple[RunAttempt, ...]:
        rows = self._session.scalars(
            select(RunAttemptRow)
            .where(RunAttemptRow.job_id == job_id)
            .order_by(RunAttemptRow.number)
        ).all()
        return tuple(read_run_attempt(row) for row in rows)


class SqlAlchemyDatasetSnapshotRepository:
    """Candidate and sealed training inputs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: DatasetSnapshot) -> None:
        self._session.add(dataset_snapshot_row(snapshot))
        try:
            self._session.flush()
        except IntegrityError as error:
            raise _translate(error, subject="dataset snapshot") from error

    def get(self, snapshot_id: UUID) -> DatasetSnapshot:
        return read_dataset_snapshot(self._row(snapshot_id))

    def update(self, snapshot: DatasetSnapshot) -> None:
        row = self._row(snapshot.id, for_update=True)
        if row.state in FINAL_SNAPSHOT_STATES:
            raise RecordIsFinal(
                f"dataset snapshot {snapshot.id} is {row.state!r} and does not change again; "
                "a correction is a new snapshot, because runs already name this one's digest"
            )
        if row.state == DatasetSnapshotState.DRAFT.value:
            # Items move only in draft, so this is the one write that may
            # replace them. From validating onwards the list being checked is
            # the list that gets sealed, and the entity refuses to change it.
            #
            # Cleared and flushed before the new rows are added: an item is
            # keyed by its position, so inserting the replacements in the same
            # flush as the deletions would collide on a key the old rows still
            # hold.
            row.items = []
            self._session.flush()
            row.items = snapshot_item_rows(snapshot.items)
        row.state = snapshot.state.value
        row.sealed_at = snapshot.sealed_at
        write_manifest(row, snapshot.manifest)
        self._session.flush()

    def _row(self, snapshot_id: UUID, *, for_update: bool = False) -> DatasetSnapshotRow:
        row = self._session.get(DatasetSnapshotRow, snapshot_id, with_for_update=for_update)
        if row is None:
            raise RecordNotFound(f"no dataset snapshot has the id {snapshot_id}")
        return row


__all__ = [
    "FINAL_SNAPSHOT_STATES",
    "FOREIGN_KEY_VIOLATION",
    "UNIQUE_VIOLATION",
    "SqlAlchemyArtifactRepository",
    "SqlAlchemyDatasetSnapshotRepository",
    "SqlAlchemyExecutionJobRepository",
    "SqlAlchemyRunAttemptRepository",
]
