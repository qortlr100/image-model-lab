"""SHA-256 content digest value object.

Every stored artifact is identified by the digest of its bytes rather than by
its name or path, so the digest is the value that decides whether two
artifacts are the same object.

Both the bare hex form and the ``sha256:`` prefixed form parse, and case is
normalised, so one stored digest has exactly one in-memory representation and
equality never depends on how it was written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from image_model_lab_domain.artifacts.errors import DigestError

ALGORITHM: Final = "sha256"
"""The one content digest algorithm the domain uses for artifact identity."""

DIGEST_LENGTH: Final = 64
"""Number of hex characters in a SHA-256 digest."""

_ALGORITHM_PREFIX: Final = f"{ALGORITHM}:"
_HEX_DIGEST: Final = re.compile(rf"[0-9a-f]{{{DIGEST_LENGTH}}}")


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """A SHA-256 digest of an artifact's bytes, held as lowercase hex."""

    hex: str

    def __post_init__(self) -> None:
        normalized = self.hex.lower()
        if normalized.startswith(_ALGORITHM_PREFIX):
            normalized = normalized[len(_ALGORITHM_PREFIX) :]
        if not _HEX_DIGEST.fullmatch(normalized):
            raise DigestError(
                f"{self.hex!r} is not a {ALGORITHM} digest; expected "
                f"{DIGEST_LENGTH} hex characters, optionally prefixed with {_ALGORITHM_PREFIX!r}"
            )
        object.__setattr__(self, "hex", normalized)

    @property
    def prefixed(self) -> str:
        """The ``sha256:<hex>`` form, for contexts that name the algorithm."""

        return f"{_ALGORITHM_PREFIX}{self.hex}"

    def __str__(self) -> str:
        return self.hex


__all__ = ["ALGORITHM", "DIGEST_LENGTH", "Sha256Digest"]
