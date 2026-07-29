"""Errors raised by the execution entities."""

from __future__ import annotations

from image_model_lab_domain.errors import DomainError


class ExecutionJobError(DomainError):
    """An execution job is invalid, or its state transition is not allowed."""


class RunAttemptError(DomainError):
    """A run attempt is invalid, or its state transition is not allowed."""


__all__ = ["ExecutionJobError", "RunAttemptError"]
