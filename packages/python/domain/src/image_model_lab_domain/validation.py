"""Shared field checks used by domain entities.

Each check takes the error type to raise, so a rejected field reports the
entity that refused it instead of a generic type complaint. Values are
returned normalised where there is a canonical form, which keeps two spellings
of the same fact from comparing unequal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from image_model_lab_domain.errors import DomainError


def require_instance(
    value: object, *, expected: type[object], field: str, error: type[DomainError]
) -> None:
    """Check that ``value`` is exactly an instance of ``expected``.

    An annotated caller is already stopped by the type checker, so this is for
    the dynamically typed ones -- deserialization, a repository row, a test --
    that reach a constructor without one.

    Raises:
        error: if ``value`` is of any other type.
    """

    if type(value) is not expected:
        raise error(f"{field} must be {expected.__name__}, got {type(value).__name__}")


def require_id(value: object, *, field: str, error: type[DomainError]) -> UUID:
    """Return ``value`` as an entity identifier.

    Identifiers are opaque UUIDs rather than strings so a name, a path or a
    digest can never stand in for a stable identity.

    Raises:
        error: if ``value`` is not a :class:`~uuid.UUID`.
    """

    if not isinstance(value, UUID):
        raise error(f"{field} must be a uuid.UUID, got {type(value).__name__}")
    return value


def require_instant(value: object, *, field: str, error: type[DomainError]) -> datetime:
    """Return ``value`` as a UTC instant.

    A naive datetime is rejected because two of them cannot be ordered: the
    control plane, the agent and the database each have their own idea of
    local time, and a run timeline is only meaningful as instants. An aware
    datetime in another zone is converted, so one instant has one stored form.

    Raises:
        error: if ``value`` is not a timezone-aware :class:`~datetime.datetime`.
    """

    if not isinstance(value, datetime):
        raise error(f"{field} must be a datetime, got {type(value).__name__}")
    if value.utcoffset() is None:
        raise error(f"{field} must be timezone-aware; a naive datetime is not an instant")
    return value.astimezone(UTC)


def require_int(value: object, *, field: str, error: type[DomainError], minimum: int) -> int:
    """Return ``value`` as an integer of at least ``minimum``.

    ``bool`` is refused explicitly: it is a subclass of ``int`` and ``True``
    would otherwise be stored as the count ``1``.

    Raises:
        error: if ``value`` is not an integer, or is below ``minimum``.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise error(f"{field} must be an int, got {type(value).__name__}")
    if value < minimum:
        raise error(f"{field} must be at least {minimum}, got {value}")
    return value


def require_bool(value: object, *, field: str, error: type[DomainError]) -> bool:
    """Return ``value`` as a boolean.

    Raises:
        error: if ``value`` is not a ``bool``. A truthy string or ``None`` is
            a caller mistake, not a decision worth recording.
    """

    if not isinstance(value, bool):
        raise error(f"{field} must be a bool, got {type(value).__name__}")
    return value


def require_text(value: object, *, field: str, error: type[DomainError], max_length: int) -> str:
    """Return ``value`` as non-empty text with no surrounding whitespace.

    Padding is rejected rather than trimmed: a key that only differs by a
    trailing space is a different key to a database index, and silently
    trimming it would hide where it came from.

    Raises:
        error: if ``value`` is not a string, is empty, is padded with
            whitespace, or is longer than ``max_length``.
    """

    if not isinstance(value, str):
        raise error(f"{field} must be a string, got {type(value).__name__}")
    if not value:
        raise error(f"{field} must not be empty")
    if value != value.strip():
        raise error(f"{field} must not start or end with whitespace, got {value!r}")
    if len(value) > max_length:
        raise error(f"{field} is {len(value)} characters, over the {max_length} character limit")
    return value


__all__ = [
    "require_bool",
    "require_id",
    "require_instance",
    "require_instant",
    "require_int",
    "require_text",
]
