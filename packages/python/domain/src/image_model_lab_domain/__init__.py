"""Framework-independent domain package for the image model lab."""

from typing import Final

from image_model_lab_domain.artifacts import (
    ArtifactNamespace,
    ArtifactReference,
    ArtifactReferenceError,
    ArtifactUri,
    ArtifactUriError,
    DigestError,
    MediaType,
    MediaTypeError,
    Sha256Digest,
)
from image_model_lab_domain.errors import DomainError

PACKAGE_NAME: Final[str] = "image-model-lab-domain"

__all__ = [
    "PACKAGE_NAME",
    "ArtifactNamespace",
    "ArtifactReference",
    "ArtifactReferenceError",
    "ArtifactUri",
    "ArtifactUriError",
    "DigestError",
    "DomainError",
    "MediaType",
    "MediaTypeError",
    "Sha256Digest",
]
