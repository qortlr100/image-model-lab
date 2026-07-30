"""SQLAlchemy adapters for the repository ports.

Each adapter is constructed with a :class:`~sqlalchemy.orm.Session` and writes
through it without committing. The composition root owns the transaction,
because one use case usually touches more than one aggregate and a commit in
the middle of it would publish a state no rule was checked against.

Writes flush, though. A flush is what turns a duplicate key or a broken
``CHECK`` into an error the caller can still do something about, instead of
one that surfaces at commit time with no context left about which write caused
it. Inserts flush inside a savepoint, because "already exists" is only useful
if the caller still has a transaction to look the existing record up in.

Every write is guarded beyond what the constraints say, and the guard is
always the same question: does the *stored* state still allow the write the
caller decided on?

It has to be asked, because a caller reads an aggregate, asks the entity for
the next value, and writes that value back -- and the entity was asked about
the state the caller read. If something moved the record in between, that
answer is about a state the record has already left.

Two things have to be true for the guard to mean anything, and neither is
free. The row is read ``FOR UPDATE``, so a second writer queues rather than
racing. And that read repopulates the row, because a session that loaded the
record earlier holds it in its identity map, and a lock taken over a cached
object would have the guard checking the state the caller already knew instead
of the state in the database.

The transition tables are the domain's, not a copy. A state that becomes
final, or a move that stops being allowed, tightens these guards without
anyone having to remember they are here.

What this does *not* catch is a change that keeps the state where it was. Two
callers editing one draft snapshot both hold ``draft``, so the second is
allowed and replaces the first's items. Catching that needs an expected
revision travelling with the write, which the ports do not carry yet; see
ADR-0005.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from uuid import UUID

from image_model_lab_application import (
    RecordAlreadyExists,
    RecordChangedElsewhere,
    RecordHistoryRewritten,
    RecordIsFinal,
    RecordNotFound,
)
from image_model_lab_domain import (
    ARTIFACT_TRANSITIONS,
    DATASET_SNAPSHOT_TRANSITIONS,
    EXECUTION_JOB_TRANSITIONS,
    RUN_ATTEMPT_TRANSITIONS,
    Artifact,
    ArtifactState,
    DatasetSnapshot,
    DatasetSnapshotState,
    ExecutionJob,
    ExecutionJobState,
    RunAttempt,
    RunAttemptState,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from image_model_lab_persistence.errors import StoredRowInvalid
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


def _stored_state[StateT: StrEnum](value: str, *, states: type[StateT], subject: str) -> StateT:
    """Read a stored state column as the domain state it is meant to be.

    A ``CHECK`` keeps unknown values out, so reaching the failure means the
    constraint is gone or the row predates it. Reported as the broken row it
    is, rather than crashing on an enum lookup halfway through a write.
    """

    try:
        return states(value)
    except ValueError:
        raise StoredRowInvalid(
            f"stored {subject} state {value!r} is not a state the domain knows"
        ) from None


def _require_writable[StateT: StrEnum](
    *,
    subject: str,
    identity: UUID,
    stored: StateT,
    incoming: StateT,
    transitions: Mapping[StateT, frozenset[StateT]],
    final_note: str,
    allow_unchanged: bool,
) -> None:
    """Check the stored state still permits the state the caller decided on.

    ``allow_unchanged`` says whether a write that carries the same state is
    meaningful. For an artifact it is -- appending provenance changes nothing
    else -- and for a draft snapshot it is, because that is how its items are
    replaced. For a run attempt it is not: ``complete`` records how something
    ended, so a write that leaves it running is a caller mistake.

    Raises:
        RecordIsFinal: if the stored state never changes again. Retrying is
            pointless, which is worth telling apart.
        RecordChangedElsewhere: if the stored state moved somewhere the
            incoming state does not follow from. Reading again may well
            succeed, and the decision has to be made against the new state.
    """

    permitted = transitions[stored]
    if not permitted:
        raise RecordIsFinal(
            f"{subject} {identity} is {stored.value!r} and does not change again; {final_note}"
        )
    if incoming is stored:
        if allow_unchanged:
            return
        raise RecordChangedElsewhere(
            f"{subject} {identity} is still {stored.value!r}; this write records a move away "
            "from that state and carries none"
        )
    if incoming not in permitted:
        choices = ", ".join(sorted(state.value for state in permitted))
        raise RecordChangedElsewhere(
            f"{subject} {identity} is stored as {stored.value!r}, which does not become "
            f"{incoming.value!r}; it moved after it was read, and the allowed next states are "
            f"now {choices}. Read it again and decide against the state it is in."
        )


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


def _insert(session: Session, row: object, *, subject: str) -> None:
    """Insert ``row``, leaving the caller's transaction usable if it collides.

    The savepoint is the point of this. PostgreSQL aborts the whole transaction
    on a failed statement, and every statement after it fails until a rollback
    -- so raising ``RecordAlreadyExists`` from a bare flush would name a
    recoverable condition while leaving nothing to recover with. The caller
    could not then look the existing record up, which is exactly what it wanted
    the error for.

    Rolling back to the savepoint undoes only the failed insert. The
    transaction the composition root owns survives, along with whatever the use
    case had already written into it.
    """

    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as error:
        raise _translate(error, subject=subject) from error


class SqlAlchemyArtifactRepository:
    """Artifacts and the append-only history of where their bytes came from."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, artifact: Artifact) -> None:
        _insert(self._session, artifact_row(artifact), subject="artifact")

    def get(self, artifact_id: UUID) -> Artifact:
        return read_artifact(self._row(artifact_id))

    def update(self, artifact: Artifact) -> None:
        # The reference is not written back. Address, digest, size and media
        # type are what identify an artifact, and a transition returns the
        # same reference, so the only thing an update can carry is the state
        # and whatever provenance the artifact has gained.
        row = self._row(artifact.id, for_update=True)
        # Checked before the provenance is touched, and this is the check that
        # keeps a quarantined artifact from taking a new origin: its stored
        # bytes contradict their digest, so recording an import against them
        # would claim that import produced them.
        _require_writable(
            subject="artifact",
            identity=artifact.id,
            stored=_stored_state(row.state, states=ArtifactState, subject="artifact"),
            incoming=artifact.state,
            transitions=ARTIFACT_TRANSITIONS,
            final_note="a good copy of those bytes is published as a new artifact",
            allow_unchanged=True,
        )
        self._append_provenance(row, artifact)
        row.state = artifact.state.value
        self._session.flush()

    def _row(self, artifact_id: UUID, *, for_update: bool = False) -> ArtifactRow:
        row = self._session.get(
            ArtifactRow, artifact_id, with_for_update=for_update, populate_existing=for_update
        )
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
        _insert(self._session, execution_job_row(job), subject="execution job")

    def get(self, job_id: UUID) -> ExecutionJob:
        return read_execution_job(self._row(job_id))

    def update(self, job: ExecutionJob) -> None:
        # Kind and idempotency key are not rewritten: they say which command
        # this is, and a write that changed them would be describing a
        # different job under an existing id.
        row = self._row(job.id, for_update=True)
        # Two agents can report different outcomes for one job, and delivery is
        # at-least-once, so without this the final outcome would be whichever
        # report committed last. Which of the two a collision is -- a duplicate
        # or a real conflict -- is still the use case's call; it knows the
        # idempotency key, and it makes that call against a state it re-read.
        _require_writable(
            subject="execution job",
            identity=job.id,
            stored=_stored_state(row.state, states=ExecutionJobState, subject="execution job"),
            incoming=job.state,
            transitions=EXECUTION_JOB_TRANSITIONS,
            final_note="its outcome is reported once and a retry is a new job",
            allow_unchanged=True,
        )
        row.state = job.state.value
        row.priority = job.priority
        self._session.flush()

    def find_by_idempotency_key(self, idempotency_key: str) -> ExecutionJob | None:
        row = self._session.scalars(
            select(ExecutionJobRow).where(ExecutionJobRow.idempotency_key == idempotency_key)
        ).one_or_none()
        return None if row is None else read_execution_job(row)

    def _row(self, job_id: UUID, *, for_update: bool = False) -> ExecutionJobRow:
        row = self._session.get(
            ExecutionJobRow, job_id, with_for_update=for_update, populate_existing=for_update
        )
        if row is None:
            raise RecordNotFound(f"no execution job has the id {job_id}")
        return row


class SqlAlchemyRunAttemptRepository:
    """What each execution of a job actually did."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: RunAttempt) -> None:
        _insert(self._session, run_attempt_row(attempt), subject="run attempt")

    def get(self, attempt_id: UUID) -> RunAttempt:
        row = self._session.get(RunAttemptRow, attempt_id)
        if row is None:
            raise RecordNotFound(f"no run attempt has the id {attempt_id}")
        return read_run_attempt(row)

    def complete(self, attempt: RunAttempt) -> None:
        row = self._session.get(
            RunAttemptRow, attempt.id, with_for_update=True, populate_existing=True
        )
        if row is None:
            raise RecordNotFound(f"no run attempt has the id {attempt.id}")
        _require_writable(
            subject="run attempt",
            identity=attempt.id,
            stored=_stored_state(row.state, states=RunAttemptState, subject="run attempt"),
            incoming=attempt.state,
            transitions=RUN_ATTEMPT_TRANSITIONS,
            final_note="a completed attempt is the evidence for what ran, and a retry is the "
            "next attempt",
            allow_unchanged=False,
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
        _insert(self._session, dataset_snapshot_row(snapshot), subject="dataset snapshot")

    def get(self, snapshot_id: UUID) -> DatasetSnapshot:
        return read_dataset_snapshot(self._row(snapshot_id))

    def update(self, snapshot: DatasetSnapshot) -> None:
        row = self._row(snapshot.id, for_update=True)
        # This is also what keeps a validating snapshot from being put back to
        # draft by a stale write. Validation freezes the list that gets sealed,
        # so reopening it would let the items change after they were checked.
        _require_writable(
            subject="dataset snapshot",
            identity=snapshot.id,
            stored=_stored_state(
                row.state, states=DatasetSnapshotState, subject="dataset snapshot"
            ),
            incoming=snapshot.state,
            transitions=DATASET_SNAPSHOT_TRANSITIONS,
            final_note="a correction is a new snapshot, because runs already name this one's "
            "digest",
            allow_unchanged=True,
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
        row = self._session.get(
            DatasetSnapshotRow,
            snapshot_id,
            with_for_update=for_update,
            populate_existing=for_update,
        )
        if row is None:
            raise RecordNotFound(f"no dataset snapshot has the id {snapshot_id}")
        return row


__all__ = [
    "FOREIGN_KEY_VIOLATION",
    "UNIQUE_VIOLATION",
    "SqlAlchemyArtifactRepository",
    "SqlAlchemyDatasetSnapshotRepository",
    "SqlAlchemyExecutionJobRepository",
    "SqlAlchemyRunAttemptRepository",
]
