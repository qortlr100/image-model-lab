"""Errors a repository raises, stated in terms a use case can act on.

A use case has to tell apart the failures it can answer for -- this identity
is already taken, this record is gone, this record can no longer be written --
from the ones it cannot, such as a lost connection or a deadlock. Only the
first kind is named here. Everything else surfaces as whatever the driver
raised, because a use case that cannot fix it should not be catching it.

None of these are :class:`~image_model_lab_domain.errors.DomainError`. A
domain error means a value or a transition was rejected by a rule; these mean
the rule was satisfied and the store still could not carry the write out.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """A use case could not be carried out."""


class RepositoryError(ApplicationError):
    """A repository refused a read or a write."""


class RecordNotFound(RepositoryError):
    """No stored record has that identity.

    Raised for the record being addressed and for a record it points at, since
    an attempt whose job is missing is as unwritable as a missing attempt.
    """


class RecordAlreadyExists(RepositoryError):
    """A stored record already claims that identity.

    The identity may be the primary one or a uniqueness rule that stands in
    for it, such as a job's idempotency key or an artifact's logical URI.
    """


class RecordIsFinal(RepositoryError):
    """The stored record has reached a state it never leaves.

    A completed run attempt and a sealed dataset snapshot are the evidence a
    finished run is explained by, so neither is rewritten. The correction is a
    new attempt or a new snapshot, which is a different record entirely.
    """


class RecordHistoryRewritten(RepositoryError):
    """An append-only history was replaced instead of extended.

    An artifact's provenance only ever grows. A write that shortens it, or
    that changes a record already written, is discarding the evidence a
    licence audit reads, so it is refused rather than merged.
    """


__all__ = [
    "ApplicationError",
    "RecordAlreadyExists",
    "RecordHistoryRewritten",
    "RecordIsFinal",
    "RecordNotFound",
    "RepositoryError",
]
