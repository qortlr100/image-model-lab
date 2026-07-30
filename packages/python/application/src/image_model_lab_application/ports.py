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

A refused write leaves the caller's transaction intact. That is what makes
these errors worth catching: on ``RecordAlreadyExists`` a use case can look up
the record that already holds the identity and acknowledge the duplicate, and
whatever it had written earlier in the same transaction is still there.

Every write therefore says which state it is coming from, as ``expected_state``:
the state the caller read before it asked the entity for the next value. A
target check alone is not enough, because a lifecycle can cycle back to a state
the stale target legitimately follows from -- an artifact verified while
``pending`` is written as ``available``, and ``missing -> available`` is a valid
repair, so without the source state a pre-``missing`` verification would mark
absent bytes readable. Pass the state you read, not the state you computed.

An expected state says only that the value the caller read is still the value in
the row, so a stale write survives wherever the row is back at that value --
whether it never moved (two callers editing one draft snapshot both read
``draft``) or moved and came all the way back (``queued -> leased -> running ->
queued``). Every state reachable from itself has that hole: ``available`` and
``missing`` for artifacts, ``queued``, ``leased`` and ``running`` for jobs.
Closing those needs a revision rather than a state, which these ports do not
carry; see ADR-0005.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from image_model_lab_domain import (
    Artifact,
    ArtifactState,
    DatasetSnapshot,
    DatasetSnapshotState,
    ExecutionJob,
    ExecutionJobState,
    RunAttempt,
    RunAttemptState,
)


class ArtifactRepository(Protocol):
    """Stored artifacts and the history of where their bytes came from."""

    def add(self, artifact: Artifact) -> None:
        """Store a new artifact together with its provenance.

        Raises:
            RecordAlreadyExists: if the id or the logical URI is taken. A
                logical URI is an address, so two artifacts at one address
                would leave a reader no way to tell which bytes it addressed.
                The caller's transaction survives the refusal.
        """
        ...

    def get(self, artifact_id: UUID) -> Artifact:
        """Read an artifact and its full provenance history.

        Raises:
            RecordNotFound: if no artifact has that id.
        """
        ...

    def update(self, artifact: Artifact, *, expected_state: ArtifactState) -> None:
        """Store an artifact's new state and any provenance it has gained.

        ``expected_state`` is the state the artifact was read in. It matters
        most here: ``missing -> available`` is a legal repair, so a verification
        made while the artifact was ``pending`` would otherwise be accepted
        after the bytes had been observed absent, marking them readable on
        evidence that predates the observation. A row that has cycled back to
        the value that was read is still not caught.

        The reference is not rewritten: an artifact's address, digest, size
        and media type are what identify it, so a write that changed them
        would be describing a different artifact.

        Raises:
            RecordNotFound: if no artifact has that id.
            RecordIsFinal: if the stored artifact is quarantined. Its bytes
                contradict the digest that identifies them, so it takes no new
                origin and never returns to a usable state; a good copy is
                published as a new artifact.
            RecordChangedElsewhere: if the stored state is not
                ``expected_state``, or does not become the state being written.
            RecordHistoryRewritten: if the provenance shrank, or a record
                already stored is not the one being written back.
        """
        ...


class ExecutionJobRepository(Protocol):
    """Schedulable commands and where each is in the lease protocol."""

    def add(self, job: ExecutionJob) -> None:
        """Store a newly queued job.

        Raises:
            RecordAlreadyExists: if the id or the idempotency key is taken. The
                caller's transaction survives the refusal, so the usual answer
                -- find the job already queued and acknowledge the duplicate --
                works without starting over.
        """
        ...

    def get(self, job_id: UUID) -> ExecutionJob:
        """Read a job.

        Raises:
            RecordNotFound: if no job has that id.
        """
        ...

    def update(self, job: ExecutionJob, *, expected_state: ExecutionJobState) -> None:
        """Store a job's new state.

        ``expected_state`` is the state the job was read in. It stops two
        agents that both read one ``queued`` job from both claiming it: the
        second arrives to find ``leased``.

        It does not make a claim handler safe on its own. A job that has gone
        ``queued -> leased -> running -> queued`` is back at the value the agent
        read, so a stale claim still lands -- that needs a revision, and
        ``test_a_completed_cycle_back_to_the_same_state_is_not_caught`` in the
        persistence package pins the boundary. Do not build claim logic that
        relies on protection this port does not give.

        Raises:
            RecordNotFound: if no job has that id.
            RecordIsFinal: if the stored job already reached an outcome.
            RecordChangedElsewhere: if the stored state is not
                ``expected_state``, or does not become the state being written.
                Two agents can report different outcomes for one job, so
                without this the outcome would be whichever report was written
                last.
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

    def complete(
        self, attempt: RunAttempt, *, expected_state: RunAttemptState = RunAttemptState.RUNNING
    ) -> None:
        """Record how a running attempt ended.

        An attempt moves once. There is no method that rewrites a completed
        one, because its timeline and outputs are the evidence for a finished
        run and a retry is the next attempt instead.

        ``expected_state`` defaults to ``running`` because that is the only
        state an attempt can be completed from -- this lifecycle has no cycles,
        so unlike the other ports there is nothing else a caller could have
        read. It is accepted for uniformity, so every write states its
        precondition the same way.

        Raises:
            RecordNotFound: if no attempt has that id.
            RecordIsFinal: if the stored attempt has already ended.
            RecordChangedElsewhere: if the stored state is not
                ``expected_state``, or the attempt being written has not ended.
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

    def update(self, snapshot: DatasetSnapshot, *, expected_state: DatasetSnapshotState) -> None:
        """Store a snapshot's new state, and its items while it is a draft.

        This lifecycle has no cycles, so ``expected_state`` adds one thing over
        the target check: it tells a caller whose transition someone else
        already performed, instead of accepting the write as a no-op.

        It does not make concurrent item edits safe. Two callers editing one
        draft both read ``draft``, so the expected state matches for each and
        the second still replaces the first's items -- that needs a revision,
        not a state. See ADR-0005.

        Raises:
            RecordNotFound: if no snapshot has that id.
            RecordIsFinal: if the stored snapshot is sealed or rejected.
            RecordChangedElsewhere: if the stored state is not
                ``expected_state``, or does not become the state being written
                -- notably a stale draft written over a snapshot that has begun
                validating, which would reopen the item list validation froze.
        """
        ...


__all__ = [
    "ArtifactRepository",
    "DatasetSnapshotRepository",
    "ExecutionJobRepository",
    "RunAttemptRepository",
]
