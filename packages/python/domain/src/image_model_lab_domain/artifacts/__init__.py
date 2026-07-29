"""Value objects that address and describe immutable stored artifacts."""

from image_model_lab_domain.artifacts.digest import ALGORITHM, DIGEST_LENGTH, Sha256Digest
from image_model_lab_domain.artifacts.errors import (
    ArtifactReferenceError,
    ArtifactUriError,
    DigestError,
    MediaTypeError,
)
from image_model_lab_domain.artifacts.media_type import MediaType
from image_model_lab_domain.artifacts.reference import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    ArtifactReference,
)
from image_model_lab_domain.artifacts.uri import (
    MAX_KEY_LENGTH,
    MAX_SEGMENT_LENGTH,
    SCHEME,
    ArtifactNamespace,
    ArtifactUri,
)

__all__ = [
    "ALGORITHM",
    "DIGEST_LENGTH",
    "MAX_KEY_LENGTH",
    "MAX_SEGMENT_LENGTH",
    "SCHEMA_VERSION",
    "SCHEME",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ArtifactNamespace",
    "ArtifactReference",
    "ArtifactReferenceError",
    "ArtifactUri",
    "ArtifactUriError",
    "DigestError",
    "MediaType",
    "MediaTypeError",
    "Sha256Digest",
]
