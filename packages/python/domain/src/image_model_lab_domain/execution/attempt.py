"""The run attempt entity and its execution lifecycle.

A job can be offered more than once -- a lease expires, an agent dies, an
engine crashes -- so the job records what should happen and an attempt records
what actually happened once. Every retry adds an attempt; no attempt is ever
rewritten, because its timeline and outputs are the evidence for a completed
run.

An attempt therefore starts in ``running`` and moves once, to exactly one of:

* ``succeeded`` -- the engine finished and the outputs were collected, so the
  attempt carries the run manifest that describes them;
* ``failed`` -- the engine ran and did not succeed;
* ``cancelled`` -- the engine stopped because cancellation was requested;
* ``abandoned`` -- nothing reported an outcome. The lease expired or the agent
  disappeared mid-run, so the control plane closes the attempt without
  claiming to know how the engine ended.

``failed`` and ``cancelled`` may still carry a manifest: a stopped run can
leave real partial outputs, and those belong to the attempt that produced
them. An abandoned attempt cannot, because nobody was left to finalize one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from image_model_lab_domain.artifacts.reference import ArtifactReference
from image_model_lab_domain.execution.errors import RunAttemptError
from image_model_lab_domain.lifecycle import require_state, require_transition
from image_model_lab_domain.validation import (
    require_id,
    require_instance,
    require_instant,
    require_int,
)


class RunAttemptState(StrEnum):
    """Whether an attempt is still running, and how it ended."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


RUN_ATTEMPT_TRANSITIONS: Final[Mapping[RunAttemptState, frozenset[RunAttemptState]]] = (
    MappingProxyType(
        {
            RunAttemptState.RUNNING: frozenset(
                {
                    RunAttemptState.SUCCEEDED,
                    RunAttemptState.FAILED,
                    RunAttemptState.CANCELLED,
                    RunAttemptState.ABANDONED,
                }
            ),
            RunAttemptState.SUCCEEDED: frozenset(),
            RunAttemptState.FAILED: frozenset(),
            RunAttemptState.CANCELLED: frozenset(),
            RunAttemptState.ABANDONED: frozenset(),
        }
    )
)
"""Allowed run attempt state transitions, keyed by the current state.

The mapping is read-only: a lifecycle that a caller can widen at runtime is
not an invariant.
"""

_TERMINAL: Final = frozenset(
    state for state, targets in RUN_ATTEMPT_TRANSITIONS.items() if not targets
)


@dataclass(frozen=True, slots=True)
class RunAttempt:
    """One actual execution of a job by one agent.

    Completing an attempt returns a new attempt rather than mutating this one.
    A completed attempt is never reopened: a later try is a new attempt with
    the next number.
    """

    id: UUID
    job_id: UUID
    agent_id: UUID
    number: int
    started_at: datetime
    state: RunAttemptState = RunAttemptState.RUNNING
    ended_at: datetime | None = None
    manifest: ArtifactReference | None = None

    def __post_init__(self) -> None:
        require_id(self.id, field="run attempt id", error=RunAttemptError)
        require_id(self.job_id, field="run attempt job id", error=RunAttemptError)
        require_id(self.agent_id, field="run attempt agent id", error=RunAttemptError)
        require_int(self.number, field="run attempt number", error=RunAttemptError, minimum=1)
        object.__setattr__(
            self,
            "started_at",
            require_instant(self.started_at, field="run attempt started_at", error=RunAttemptError),
        )
        object.__setattr__(
            self,
            "state",
            require_state(
                self.state,
                states=RunAttemptState,
                subject="run attempt state",
                error=RunAttemptError,
            ),
        )
        self._validate_ending()
        self._validate_manifest()

    def _validate_ending(self) -> None:
        if self.state is RunAttemptState.RUNNING:
            if self.ended_at is not None:
                raise RunAttemptError("a running run attempt must not have an ended_at")
            return
        if self.ended_at is None:
            raise RunAttemptError(
                f"a {self.state.value} run attempt must have an ended_at; "
                "an outcome without an end leaves the timeline unreadable"
            )
        ended_at = require_instant(
            self.ended_at, field="run attempt ended_at", error=RunAttemptError
        )
        if ended_at < self.started_at:
            raise RunAttemptError(
                f"run attempt ended_at {ended_at.isoformat()} is before started_at "
                f"{self.started_at.isoformat()}"
            )
        object.__setattr__(self, "ended_at", ended_at)

    def _validate_manifest(self) -> None:
        if self.manifest is not None:
            require_instance(
                self.manifest,
                expected=ArtifactReference,
                field="run attempt manifest",
                error=RunAttemptError,
            )
        if self.state is RunAttemptState.SUCCEEDED and self.manifest is None:
            raise RunAttemptError(
                "a succeeded run attempt must have a manifest; a run nobody can reproduce "
                "did not succeed"
            )
        if self.state is RunAttemptState.RUNNING and self.manifest is not None:
            raise RunAttemptError(
                "a running run attempt must not have a manifest; it is written when the "
                "outputs are collected"
            )
        if self.state is RunAttemptState.ABANDONED and self.manifest is not None:
            raise RunAttemptError(
                "an abandoned run attempt must not have a manifest; nothing was left to "
                "finalize one"
            )

    @property
    def is_complete(self) -> bool:
        """Whether the attempt has ended and can no longer change."""

        return self.state in _TERMINAL

    @property
    def outcome(self) -> RunAttemptState | None:
        """How the attempt ended, or ``None`` while it is still running."""

        return self.state if self.is_complete else None

    def _end(
        self,
        target: RunAttemptState,
        ended_at: datetime,
        manifest: ArtifactReference | None,
    ) -> RunAttempt:
        require_transition(
            subject="a run attempt",
            current=self.state,
            target=target,
            allowed=RUN_ATTEMPT_TRANSITIONS,
            error=RunAttemptError,
        )
        return replace(self, state=target, ended_at=ended_at, manifest=manifest)

    def succeed(self, *, ended_at: datetime, manifest: ArtifactReference) -> RunAttempt:
        """Close the attempt with its collected outputs.

        Raises:
            RunAttemptError: if the attempt already ended, or ``ended_at`` is
                not an instant at or after the start.
        """

        return self._end(RunAttemptState.SUCCEEDED, ended_at, manifest)

    def fail(self, *, ended_at: datetime, manifest: ArtifactReference | None = None) -> RunAttempt:
        """Close the attempt after the engine ran and did not succeed.

        Raises:
            RunAttemptError: if the attempt already ended, or ``ended_at`` is
                not an instant at or after the start.
        """

        return self._end(RunAttemptState.FAILED, ended_at, manifest)

    def cancel(
        self, *, ended_at: datetime, manifest: ArtifactReference | None = None
    ) -> RunAttempt:
        """Close the attempt after a cooperative stop.

        Raises:
            RunAttemptError: if the attempt already ended, or ``ended_at`` is
                not an instant at or after the start.
        """

        return self._end(RunAttemptState.CANCELLED, ended_at, manifest)

    def abandon(self, *, ended_at: datetime) -> RunAttempt:
        """Close the attempt after its lease was lost and nothing reported back.

        Raises:
            RunAttemptError: if the attempt already ended, or ``ended_at`` is
                not an instant at or after the start.
        """

        return self._end(RunAttemptState.ABANDONED, ended_at, None)


__all__ = ["RUN_ATTEMPT_TRANSITIONS", "RunAttempt", "RunAttemptState"]
