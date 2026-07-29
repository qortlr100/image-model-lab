"""Errors raised by artifact value objects and by the artifact entity.

The errors are flat. :class:`ArtifactError` names the entity that refused a
value; the others name the value object that could not be parsed. Neither is
the base of the other, so catching one never quietly catches the rest.
"""

from __future__ import annotations

from image_model_lab_domain.errors import DomainError


class ArtifactError(DomainError):
    """An artifact entity is invalid, or its state transition is not allowed."""


class ArtifactUriError(DomainError):
    """A value cannot be a logical artifact URI."""


class ArtifactProvenanceError(DomainError):
    """An artifact provenance record cannot explain where bytes came from."""


class DigestError(DomainError):
    """A value cannot be a SHA-256 content digest."""


class MediaTypeError(DomainError):
    """A value cannot be an artifact media type."""


class ArtifactReferenceError(DomainError):
    """An artifact reference is incomplete, inconsistent or unreadable."""


__all__ = [
    "ArtifactError",
    "ArtifactProvenanceError",
    "ArtifactReferenceError",
    "ArtifactUriError",
    "DigestError",
    "MediaTypeError",
]
