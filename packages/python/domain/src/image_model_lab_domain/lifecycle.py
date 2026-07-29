"""Shared state machine helpers for domain entities.

Every lifecycle in this package is one explicit table of allowed transitions,
and a state that maps to an empty set is final. Keeping the tables declarative
means an entity's rules can be read, and tested, without following the code
paths that happen to call them today.

A transition is rejected rather than ignored even when the target equals the
current state. The entity states what is true; deciding whether a repeated
command is a harmless duplicate or a real conflict needs the delivery context
that only a use case has.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from image_model_lab_domain.errors import DomainError


def require_state[StateT: StrEnum](
    value: object,
    *,
    states: type[StateT],
    subject: str,
    error: type[DomainError],
) -> StateT:
    """Return ``value`` as a member of ``states``.

    States are ``StrEnum`` members, so a plain ``"queued"`` compares equal to
    the member and would otherwise be stored unnoticed, only to fail later
    where the member API is used.

    Raises:
        error: if ``value`` does not name a state of ``states``.
    """

    try:
        return states(value)
    except ValueError:
        choices = ", ".join(state.value for state in states)
        raise error(f"{value!r} is not a valid {subject}; expected one of {choices}") from None


def require_transition[StateT: StrEnum](
    *,
    subject: str,
    current: StateT,
    target: StateT,
    allowed: Mapping[StateT, frozenset[StateT]],
    error: type[DomainError],
) -> None:
    """Check that ``subject`` may move from ``current`` to ``target``.

    ``subject`` is a noun phrase with its article, such as ``an artifact``, so
    the rejection reads as a sentence. ``allowed`` must have an entry for
    every state, so a missing key is a bug in the table rather than a silently
    final state.

    Raises:
        error: if the transition is not in ``allowed``.
    """

    permitted = allowed[current]
    if target in permitted:
        return
    if not permitted:
        raise error(f"{subject} in {current.value!r} is final; it cannot become {target.value!r}")
    choices = ", ".join(sorted(state.value for state in permitted))
    raise error(
        f"{subject} cannot move from {current.value!r} to {target.value!r}; "
        f"the allowed next states are {choices}"
    )


__all__ = ["require_state", "require_transition"]
