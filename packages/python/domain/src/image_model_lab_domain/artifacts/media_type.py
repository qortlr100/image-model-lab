"""Artifact media type value object.

An artifact records what its bytes are, so a reader does not have to guess
from the key. The value is a bare ``<type>/<subtype>`` following the RFC 6838
restricted-name grammar, normalised to lowercase.

Parameters such as ``; charset=utf-8`` are rejected: they describe how one
reader interprets a stream, not what the stored object is, and allowing them
would make two spellings of the same artifact type compare unequal. Wildcards
are rejected for the same reason -- ``image/*`` is a request preference, never
the type of a concrete file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from image_model_lab_domain.artifacts.errors import MediaTypeError

MAX_NAME_LENGTH: Final = 127
"""Maximum length of the type and of the subtype, per RFC 6838."""

_NAME: Final = rf"[a-z0-9][a-z0-9!#$&^_.+-]{{0,{MAX_NAME_LENGTH - 1}}}"
_MEDIA_TYPE: Final = re.compile(rf"({_NAME})/({_NAME})")


@dataclass(frozen=True, slots=True)
class MediaType:
    """A concrete ``<type>/<subtype>`` such as ``image/png``."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.lower()
        if ";" in normalized:
            raise MediaTypeError(
                f"{self.value!r} carries parameters; an artifact stores a bare <type>/<subtype>"
            )
        if "*" in normalized:
            raise MediaTypeError(
                f"{self.value!r} is a wildcard; an artifact has one concrete media type"
            )
        if _MEDIA_TYPE.fullmatch(normalized) is None:
            raise MediaTypeError(f"{self.value!r} is not a valid <type>/<subtype> media type")
        object.__setattr__(self, "value", normalized)

    @property
    def type(self) -> str:
        """The top-level type, such as ``image``."""

        return self.value.split("/", 1)[0]

    @property
    def subtype(self) -> str:
        """The subtype, such as ``png``."""

        return self.value.split("/", 1)[1]

    def __str__(self) -> str:
        return self.value


__all__ = ["MAX_NAME_LENGTH", "MediaType"]
