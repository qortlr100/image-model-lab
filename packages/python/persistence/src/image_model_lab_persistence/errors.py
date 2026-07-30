"""Errors specific to the stored form of the domain.

The repository ports name what a use case can act on, and those errors come
from :mod:`image_model_lab_application.errors`. Only the failures that are
about storage itself are defined here.
"""

from __future__ import annotations

from image_model_lab_application import RepositoryError


class DatabaseUrlError(RepositoryError):
    """The configured database URL is missing or is not one this schema runs on."""


class StoredRowInvalid(RepositoryError):
    """A stored row contradicts a rule its table was supposed to enforce.

    Raised on the way out rather than passed along. A row like this survives a
    restore from an older schema, a hand-edited fix or a constraint that was
    dropped, and quietly loading it would put a value the domain refuses into
    the middle of a use case.
    """


__all__ = ["DatabaseUrlError", "StoredRowInvalid"]
