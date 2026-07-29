"""The execution job entity and its queue lifecycle.

An execution job is one schedulable command that an agent on the execution
plane leases and runs. The control plane never runs it, and the agent never
reaches the database, so the job's state is the whole of what the two sides
agree on.

The lifecycle assumes at-least-once delivery in both directions:

* a lease can be lost -- the agent dies, the network drops, the lease expires
  -- so ``leased`` and ``running`` both return to ``queued`` and the job is
  offered again under a new :class:`~image_model_lab_domain.execution.attempt.RunAttempt`;
* the completion report can arrive twice, which is why a repeated transition
  raises rather than passing silently. Deduplicating a retried report is the
  caller's decision, made from the job's current state and its idempotency
  key, not something the entity can guess.

Cancelling depends on who holds the job. A queued job has no agent to
cooperate with, so it is cancelled outright. Once an agent holds it,
cancellation is cooperative and therefore two-step: ``cancel_requested``
records the intent, and the job reaches ``cancelled`` when nothing is running
for it any more. A job that finishes before the request is noticed still
reports ``succeeded`` or ``failed``, because the work did happen and its
outputs exist -- and that is exactly why a queued job never passes through
``cancel_requested``. An outcome must not be reportable for work that was
never handed to anyone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from image_model_lab_domain.execution.errors import ExecutionJobError
from image_model_lab_domain.lifecycle import require_state, require_transition
from image_model_lab_domain.validation import require_id, require_int, require_text

MAX_IDEMPOTENCY_KEY_LENGTH: Final = 200
"""Maximum length of a job's idempotency key, in characters."""


class ExecutionJobKind(StrEnum):
    """The kind of command a job carries.

    An agent claims only the kinds it has a working adapter for, so adding a
    kind changes the execution protocol and not only this enum.
    """

    CAPTION = "caption"
    TRAINING = "training"


class ExecutionJobState(StrEnum):
    """Where a job is in the queue and lease protocol."""

    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


EXECUTION_JOB_TRANSITIONS: Final[Mapping[ExecutionJobState, frozenset[ExecutionJobState]]] = (
    MappingProxyType(
        {
            ExecutionJobState.QUEUED: frozenset(
                {ExecutionJobState.LEASED, ExecutionJobState.CANCELLED}
            ),
            ExecutionJobState.LEASED: frozenset(
                {
                    ExecutionJobState.RUNNING,
                    ExecutionJobState.QUEUED,
                    ExecutionJobState.CANCEL_REQUESTED,
                }
            ),
            ExecutionJobState.RUNNING: frozenset(
                {
                    ExecutionJobState.SUCCEEDED,
                    ExecutionJobState.FAILED,
                    ExecutionJobState.QUEUED,
                    ExecutionJobState.CANCEL_REQUESTED,
                }
            ),
            ExecutionJobState.CANCEL_REQUESTED: frozenset(
                {
                    ExecutionJobState.CANCELLED,
                    ExecutionJobState.SUCCEEDED,
                    ExecutionJobState.FAILED,
                }
            ),
            ExecutionJobState.SUCCEEDED: frozenset(),
            ExecutionJobState.FAILED: frozenset(),
            ExecutionJobState.CANCELLED: frozenset(),
        }
    )
)
"""Allowed execution job state transitions, keyed by the current state.

The mapping is read-only: a lifecycle that a caller can widen at runtime is
not an invariant.
"""

_TERMINAL: Final = frozenset(
    state for state, targets in EXECUTION_JOB_TRANSITIONS.items() if not targets
)


@dataclass(frozen=True, slots=True)
class ExecutionJob:
    """A schedulable command, and where it is in the lease protocol.

    Transitions return a new job rather than mutating this one, so a caller
    that still holds the old value keeps reading the state it checked.
    """

    id: UUID
    kind: ExecutionJobKind
    idempotency_key: str
    priority: int = 0
    state: ExecutionJobState = ExecutionJobState.QUEUED

    def __post_init__(self) -> None:
        require_id(self.id, field="execution job id", error=ExecutionJobError)
        object.__setattr__(
            self,
            "kind",
            require_state(
                self.kind,
                states=ExecutionJobKind,
                subject="execution job kind",
                error=ExecutionJobError,
            ),
        )
        require_text(
            self.idempotency_key,
            field="execution job idempotency key",
            error=ExecutionJobError,
            max_length=MAX_IDEMPOTENCY_KEY_LENGTH,
        )
        require_int(
            self.priority, field="execution job priority", error=ExecutionJobError, minimum=0
        )
        object.__setattr__(
            self,
            "state",
            require_state(
                self.state,
                states=ExecutionJobState,
                subject="execution job state",
                error=ExecutionJobError,
            ),
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the job has reached an outcome and will not run again."""

        return self.state in _TERMINAL

    @property
    def is_claimable(self) -> bool:
        """Whether an agent may lease the job right now."""

        return self.state is ExecutionJobState.QUEUED

    def _become(self, target: ExecutionJobState) -> ExecutionJob:
        require_transition(
            subject="an execution job",
            current=self.state,
            target=target,
            allowed=EXECUTION_JOB_TRANSITIONS,
            error=ExecutionJobError,
        )
        return replace(self, state=target)

    def lease(self) -> ExecutionJob:
        """Hand the job to an agent that matched its requirements.

        Raises:
            ExecutionJobError: if the job is not queued.
        """

        return self._become(ExecutionJobState.LEASED)

    def start(self) -> ExecutionJob:
        """Record that the leasing agent began executing the job.

        Raises:
            ExecutionJobError: if the job is not leased.
        """

        return self._become(ExecutionJobState.RUNNING)

    def release(self) -> ExecutionJob:
        """Return a job to the queue after its lease was lost or expired.

        The work already done is not erased: it stays on the attempt that was
        running, and the next lease opens a new one.

        Raises:
            ExecutionJobError: if the job is not leased or running.
        """

        return self._become(ExecutionJobState.QUEUED)

    def cancel(self) -> ExecutionJob:
        """Cancel the job, immediately or cooperatively as its state allows.

        A queued job is cancelled outright because no agent holds it. Once one
        does, this records the request and the agent stops at its next
        cooperative point.

        Raises:
            ExecutionJobError: if cancellation was already requested, or the
                job has already reached an outcome.
        """

        if self.state is ExecutionJobState.QUEUED:
            return self.mark_cancelled()
        return self.request_cancellation()

    def request_cancellation(self) -> ExecutionJob:
        """Record that the job should stop at the next cooperative point.

        Raises:
            ExecutionJobError: if no agent holds the job, if cancellation was
                already requested, or if the job has already reached an
                outcome.
        """

        return self._become(ExecutionJobState.CANCEL_REQUESTED)

    def mark_cancelled(self) -> ExecutionJob:
        """Cancel a queued job, or complete a requested cancellation.

        Raises:
            ExecutionJobError: if an agent holds the job and cancellation was
                not requested first.
        """

        return self._become(ExecutionJobState.CANCELLED)

    def mark_succeeded(self) -> ExecutionJob:
        """Record that the job's command completed and produced its outputs.

        Raises:
            ExecutionJobError: if the job was not running or being cancelled.
        """

        return self._become(ExecutionJobState.SUCCEEDED)

    def mark_failed(self) -> ExecutionJob:
        """Record that the job's command ran and did not succeed.

        Raises:
            ExecutionJobError: if the job was not running or being cancelled.
        """

        return self._become(ExecutionJobState.FAILED)


__all__ = [
    "EXECUTION_JOB_TRANSITIONS",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "ExecutionJob",
    "ExecutionJobKind",
    "ExecutionJobState",
]
