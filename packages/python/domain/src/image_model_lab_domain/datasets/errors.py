"""Errors raised by the dataset entities."""

from __future__ import annotations

from image_model_lab_domain.errors import DomainError


class SnapshotItemError(DomainError):
    """A snapshot item cannot describe a training input."""


class DatasetSnapshotError(DomainError):
    """A dataset snapshot is invalid, or the change to it is not allowed."""


__all__ = ["DatasetSnapshotError", "SnapshotItemError"]
