"""Base error type for domain rule violations."""

from __future__ import annotations


class DomainError(ValueError):
    """A domain invariant was violated.

    Domain errors subclass :class:`ValueError` so a caller that only wants to
    know that its input was rejected does not have to import the domain
    package, while a caller that cares about the specific rule still can.
    """


__all__ = ["DomainError"]
