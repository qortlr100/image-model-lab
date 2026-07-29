"""Errors raised by artifact value objects."""

from __future__ import annotations

from image_model_lab_domain.errors import DomainError


class ArtifactUriError(DomainError):
    """A value cannot be a logical artifact URI."""


class DigestError(DomainError):
    """A value cannot be a SHA-256 content digest."""


class MediaTypeError(DomainError):
    """A value cannot be an artifact media type."""


class ArtifactReferenceError(DomainError):
    """An artifact reference is incomplete, inconsistent or unreadable."""


__all__ = [
    "ArtifactReferenceError",
    "ArtifactUriError",
    "DigestError",
    "MediaTypeError",
]
