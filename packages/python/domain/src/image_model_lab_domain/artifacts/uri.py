"""Logical artifact URI value object.

Artifacts live on NAS, but a machine mount path must never reach the domain or
the database. A deployment maps every namespace to a real mount root, so the
only address the domain knows is ``nas://<namespace>/<key>``.

The grammar is deliberately narrower than RFC 3986:

* the scheme is exactly ``nas://``, lowercase, with no host, port,
  userinfo, query or fragment;
* the namespace is one of :class:`ArtifactNamespace`;
* the key is one or more ``/``-separated segments matching
  ``[a-z0-9][a-z0-9._-]*``.

Everything else is rejected, which is what keeps a machine path out:

* ``.`` and ``..`` segments, empty segments and a leading ``/`` are path
  traversal or an absolute path;
* a backslash is a Windows separator or a UNC prefix;
* percent-encoding could smuggle ``%2e%2e`` past this check and only become
  traversal inside the storage adapter that decodes it;
* uppercase is rejected because a case-insensitive backend (SMB, macOS) would
  map two distinct URIs onto one file, and keys are generated identifiers such
  as a SHA-256 hex or a UUID, never a user-supplied filename.

A trailing ``/`` is rejected too. ``nas://datasets/<id>/snapshots/<id>/`` names
a prefix in the layout documentation; an artifact is a single object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from image_model_lab_domain.artifacts.errors import ArtifactUriError

SCHEME: Final = "nas"
"""The only scheme a logical artifact URI may use."""

MAX_KEY_LENGTH: Final = 1024
"""Maximum length of the whole key, in characters."""

MAX_SEGMENT_LENGTH: Final = 255
"""Maximum length of one key segment, matching the usual POSIX ``NAME_MAX``."""

_PREFIX: Final = f"{SCHEME}://"
_SEGMENT: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
_RELATIVE_SEGMENTS: Final = frozenset({".", ".."})


class ArtifactNamespace(StrEnum):
    """Top-level logical location of an artifact.

    A namespace is resolved to a mount root by deployment configuration, so
    adding one is a deployment change and not only a code change.
    """

    ASSETS = "assets"
    DATASETS = "datasets"
    MODELS = "models"
    RUNS = "runs"
    WORKFLOWS = "workflows"


def _namespace_choices() -> str:
    return ", ".join(namespace.value for namespace in ArtifactNamespace)


def _coerce_namespace(value: object) -> ArtifactNamespace:
    """Return ``value`` as a namespace, accepting its plain string spelling.

    ``ArtifactNamespace`` is a ``StrEnum``, so a bare ``"assets"`` compares
    equal to the member and would slip through a construction unnoticed, only
    to fail later where the member API is used. Normalising here means direct
    construction either yields a usable URI or fails immediately.
    """

    try:
        return ArtifactNamespace(value)
    except ValueError:
        raise ArtifactUriError(
            f"{value!r} is not a known artifact namespace; expected one of {_namespace_choices()}"
        ) from None


def _validate_key(key: str) -> None:
    if not key:
        raise ArtifactUriError("an artifact key must not be empty")
    if len(key) > MAX_KEY_LENGTH:
        raise ArtifactUriError(
            f"artifact key is {len(key)} characters, over the {MAX_KEY_LENGTH} character limit"
        )
    if key.startswith("/"):
        raise ArtifactUriError(
            f"artifact key {key!r} starts with '/'; a logical key is never an absolute path"
        )
    if key.endswith("/"):
        raise ArtifactUriError(
            f"artifact key {key!r} ends with '/'; that names a prefix, not a single artifact"
        )
    if "\\" in key:
        raise ArtifactUriError(
            f"artifact key {key!r} contains a backslash; a machine path is not a logical key"
        )
    if "%" in key:
        raise ArtifactUriError(
            f"artifact key {key!r} is percent-encoded; a decoded key could escape its namespace"
        )

    for segment in key.split("/"):
        if not segment:
            raise ArtifactUriError(f"artifact key {key!r} has an empty path segment")
        if segment in _RELATIVE_SEGMENTS:
            raise ArtifactUriError(
                f"artifact key {key!r} contains the relative segment {segment!r}; "
                "path traversal is not addressable"
            )
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise ArtifactUriError(
                f"artifact key segment {segment!r} is over the {MAX_SEGMENT_LENGTH} character limit"
            )
        if not _SEGMENT.fullmatch(segment):
            raise ArtifactUriError(
                f"artifact key segment {segment!r} must match "
                f"'{_SEGMENT.pattern}'; keys are lowercase generated identifiers"
            )


@dataclass(frozen=True, slots=True)
class ArtifactUri:
    """A deployment-independent address of one immutable artifact.

    Construct it from its parts, or parse a stored string with
    :meth:`parse`. ``str(uri)`` formats the canonical form back.
    """

    namespace: ArtifactNamespace
    key: str

    def __post_init__(self) -> None:
        # `type(...) is not` rather than isinstance: a StrEnum member and its
        # plain string spelling are equal, so only an exact type check spots
        # the string a dynamically typed caller passed in.
        if type(self.namespace) is not ArtifactNamespace:
            object.__setattr__(self, "namespace", _coerce_namespace(self.namespace))
        _validate_key(self.key)

    @classmethod
    def parse(cls, value: str) -> ArtifactUri:
        """Parse ``nas://<namespace>/<key>``.

        Raises:
            ArtifactUriError: if ``value`` is not a well-formed logical URI.
        """

        if not value.startswith(_PREFIX):
            raise ArtifactUriError(
                f"{value!r} is not a logical artifact URI; expected it to start with {_PREFIX!r}"
            )

        namespace_text, separator, key = value[len(_PREFIX) :].partition("/")
        if not separator:
            raise ArtifactUriError(f"{value!r} has no key; expected '{_PREFIX}<namespace>/<key>'")

        return cls(namespace=_coerce_namespace(namespace_text), key=key)

    def __str__(self) -> str:
        return f"{_PREFIX}{self.namespace.value}/{self.key}"


__all__ = [
    "MAX_KEY_LENGTH",
    "MAX_SEGMENT_LENGTH",
    "SCHEME",
    "ArtifactNamespace",
    "ArtifactUri",
]
