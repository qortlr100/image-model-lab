"""Serializable reference to one immutable stored artifact.

Every stored artifact carries a logical URI, a SHA-256 digest, a byte size and
a media type. This value object is the durable form of those four facts, and
its JSON shape is versioned by ``schema_version`` because it is embedded in
manifests that outlive the code that wrote them.

``contracts/schemas/artifact-reference-v1.schema.json`` is the published
schema for :data:`SCHEMA_VERSION` and
``contracts/examples/artifact-reference-v1.example.json`` is the fixture both
sides are tested against.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from image_model_lab_domain.artifacts.digest import Sha256Digest
from image_model_lab_domain.artifacts.errors import ArtifactReferenceError
from image_model_lab_domain.artifacts.media_type import MediaType
from image_model_lab_domain.artifacts.uri import ArtifactUri

SCHEMA_VERSION: Final = 1
"""Version of the serialized artifact reference this code writes."""

SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({SCHEMA_VERSION})
"""Versions :meth:`ArtifactReference.from_json_dict` accepts.

A migration adds the preceding version here before the writer moves on, so a
reader always accepts the current version and at least one older one while
stored manifests are being rewritten.
"""

_FIELDS: Final = ("schema_version", "logical_uri", "sha256", "size_bytes", "media_type")


def _require_field(payload: Mapping[str, object], field: str) -> object:
    if field not in payload:
        raise ArtifactReferenceError(f"serialized artifact reference is missing {field!r}")
    return payload[field]


def _require_str(payload: Mapping[str, object], field: str) -> str:
    value = _require_field(payload, field)
    if not isinstance(value, str):
        raise ArtifactReferenceError(
            f"serialized artifact reference field {field!r} must be a string, "
            f"got {type(value).__name__}"
        )
    return value


def _require_int(payload: Mapping[str, object], field: str) -> int:
    value = _require_field(payload, field)
    # bool is a subclass of int, and `True == 1`, so an unchecked bool would
    # pass both the isinstance test and a version equality test.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactReferenceError(
            f"serialized artifact reference field {field!r} must be an integer, "
            f"got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """The four facts every stored artifact must have."""

    uri: ArtifactUri
    digest: Sha256Digest
    size_bytes: int
    media_type: MediaType

    def __post_init__(self) -> None:
        if isinstance(self.size_bytes, bool):
            raise ArtifactReferenceError("artifact size_bytes must be an integer, got bool")
        if self.size_bytes < 0:
            raise ArtifactReferenceError(
                f"artifact size_bytes must not be negative, got {self.size_bytes}"
            )

    def to_json_dict(self) -> dict[str, object]:
        """Serialize to the versioned JSON object shape."""

        return {
            "schema_version": SCHEMA_VERSION,
            "logical_uri": str(self.uri),
            "sha256": self.digest.hex,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type.value,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, object]) -> ArtifactReference:
        """Rebuild a reference from the versioned JSON object shape.

        Unknown fields are rejected rather than ignored: in a durable manifest
        a stray key is a mistyped field or a newer writer, and silently
        dropping either loses information.

        Raises:
            ArtifactReferenceError: if the payload is malformed or its version
                is not supported.
            DomainError: if a field is present but not a valid value object.
        """

        unknown = sorted(set(payload) - set(_FIELDS))
        if unknown:
            raise ArtifactReferenceError(
                f"serialized artifact reference has unknown field(s): {', '.join(unknown)}"
            )

        version = _require_int(payload, "schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            supported = ", ".join(str(known) for known in sorted(SUPPORTED_SCHEMA_VERSIONS))
            raise ArtifactReferenceError(
                f"artifact reference schema version {version} is not supported; "
                f"this reader accepts {supported}"
            )

        return cls(
            uri=ArtifactUri.parse(_require_str(payload, "logical_uri")),
            digest=Sha256Digest(_require_str(payload, "sha256")),
            size_bytes=_require_int(payload, "size_bytes"),
            media_type=MediaType(_require_str(payload, "media_type")),
        )


__all__ = ["SCHEMA_VERSION", "SUPPORTED_SCHEMA_VERSIONS", "ArtifactReference"]
