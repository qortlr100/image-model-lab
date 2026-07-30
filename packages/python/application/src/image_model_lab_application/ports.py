"""Repository ports: what a use case may ask of a store, and nothing more.

Each port is one aggregate's whole boundary. A caller reads an aggregate, asks
the domain entity for the next value, and writes that value back; the store
never sees a half-applied change, and a rule the entity refused never reaches
a table.

They are :class:`~typing.Protocol` classes so the dependency only ever points
inward. An adapter satisfies a port by having the methods, not by importing
it, which is what keeps the persistence package downstream of this one.

Writes do not commit. A repository writes through the session or connection it
was given and the composition root decides the transaction boundary, because
one use case's work is usually several aggregates and committing halfway
through would publish a state no rule was checked against.

Every write can raise :class:`~image_model_lab_application.errors.RecordChangedElsewhere`.
The entity was asked for the next value given the state the caller had read,
so if the record moved in between, that answer is about a state it has already
left. The write is refused instead of applied, and the caller reads again and
decides against the state the record is in.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from image_model_lab_domain import Artifact, DatasetSnapshot, ExecutionJob, RunAttempt


class ArtifactRepository(Protocol):
    """Stored artifacts and the history of where their bytes came from."""

    def add(self, artifact: Artifact) -> None:
        """Store a new artifact together with its provenance.

        Raises:
            RecordAlreadyExists: if the id or the logical URI is taken. A
                logical URI is an address, so two artifacts at one address
                would leave a reader no way to tell which bytes it addressed.
        """
        ...

    def get(self, artifact_id: UUID) -> Artifact:
        """Read an artifact and its full provenance history.

        Raises:
            RecordNotFound: if no artifact has that id.
        """
        ...

    def update(self, artifact: Artifact) -> None:
        """Store an artifact's new state and any provenance it has gained.

        The reference is not rewritten: an artifact's address, digest, size
        and media type are what identify it, so a write that changed them
        would be describing a different artifact.

        Raises:
            RecordNotFound: if no artifact has that id.
            RecordIsFinal: if the stored artifact is quarantined. Its bytes
                contradict the digest that identifies them, so it takes no new
                origin and never returns to a usable state; a good copy is
                published as a new artifact.
            RecordChangedElsewhere: if the stored state does not become the
                state being written.
            RecordHistoryRewritten: if the provenance shrank, or a record
                already stored is not the one being written back.
        """
        ...


class ExecutionJobRepository(Protocol):
    """Schedulable commands and where each is in the lease protocol."""

    def add(self, job: ExecutionJob) -> None:
        """Store a newly queued job.

        Raises:
            RecordAlreadyExists: if the id or the idempotency key is taken.
        """
        ...

    def get(self, job_id: UUID) -> ExecutionJob:
        """Read a job.

        Raises:
            RecordNotFound: if no job has that id.
        """
        ...

    def update(self, job: ExecutionJob) -> None:
        """Store a job's new state.

        Raises:
            RecordNotFound: if no job has that id.
            RecordIsFinal: if the stored job already reached an outcome.
            RecordChangedElsewhere: if the stored state does not become the
                state being written. Two agents can report different outcomes
                for one job, so without this the outcome would be whichever
                report was written last.
        """
        ...

    def find_by_idempotency_key(self, idempotency_key: str) -> ExecutionJob | None:
        """Read the job with that idempotency key, or ``None``.

        Delivery is at-least-once, so a request to queue work can arrive
        twice. This is how a use case tells a duplicate request from a new
        one before it creates a second job for the same command.
        """
        ...


class RunAttemptRepository(Protocol):
    """What each execution of a job actually did."""

    def add(self, attempt: RunAttempt) -> None:
        """Open a new attempt on an existing job.

        Raises:
            RecordAlreadyExists: if the id is taken, or the job already has an
                attempt with that number.
            RecordNotFound: if the attempt names a job that does not exist.
        """
        ...

    def get(self, attempt_id: UUID) -> RunAttempt:
        """Read an attempt.

        Raises:
            RecordNotFound: if no attempt has that id.
        """
        ...

    def complete(self, attempt: RunAttempt) -> None:
        """Record how a running attempt ended.

        An attempt moves once. There is no method that rewrites a completed
        one, because its timeline and outputs are the evidence for a finished
        run and a retry is the next attempt instead.

        Raises:
            RecordNotFound: if no attempt has that id.
            RecordIsFinal: if the stored attempt has already ended.
            RecordChangedElsewhere: if the attempt being written has not ended.
        """
        ...

    def list_for_job(self, job_id: UUID) -> tuple[RunAttempt, ...]:
        """Read a job's attempts in the order they were numbered.

        Returns an empty tuple for a job that has not been leased, and for a
        job that does not exist -- a caller asking what ran is answered by the
        attempts, and there are none either way.
        """
        ...


class DatasetSnapshotRepository(Protocol):
    """Candidate and sealed training inputs."""

    def add(self, snapshot: DatasetSnapshot) -> None:
        """Store a snapshot and its items.

        Raises:
            RecordAlreadyExists: if the id is taken.
        """
        ...

    def get(self, snapshot_id: UUID) -> DatasetSnapshot:
        """Read a snapshot and its items in order.

        Raises:
            RecordNotFound: if no snapshot has that id.
        """
        ...

    def update(self, snapshot: DatasetSnapshot) -> None:
        """Store a snapshot's new state, and its items while it is a draft.

        Raises:
            RecordNotFound: if no snapshot has that id.
            RecordIsFinal: if the stored snapshot is sealed or rejected.
            RecordChangedElsewhere: if the stored state does not become the
                state being written -- notably a stale draft written over a
                snapshot that has begun validating, which would reopen the item
                list validation froze.
        """
        ...


__all__ = [
    "ArtifactRepository",
    "DatasetSnapshotRepository",
    "ExecutionJobRepository",
    "RunAttemptRepository",
]
