"""Translation between rows and entities, without a database.

The round trips are covered by the repository tests. What is left here is the
one path a healthy database never reaches: a row that contradicts the ``CHECK``
its table carries. Such a row survives a restore from an older schema or a
hand-edited fix, and the point of reading through the entity constructors is
that it fails to load rather than arriving in the middle of a use case.
"""

from __future__ import annotations

import factories
import pytest
from image_model_lab_persistence import StoredRowInvalid
from image_model_lab_persistence.mapping import read_manifest, write_manifest
from image_model_lab_persistence.tables import RunAttemptRow

MANIFEST_COLUMNS = (
    "manifest_logical_uri",
    "manifest_sha256",
    "manifest_size_bytes",
    "manifest_media_type",
)


def test_a_manifest_survives_being_spread_across_columns() -> None:
    manifest = factories.reference(key="training/run-9/manifest.json")
    row = RunAttemptRow()

    write_manifest(row, manifest)

    assert read_manifest(row) == manifest


def test_no_manifest_reads_back_as_none() -> None:
    row = RunAttemptRow()

    write_manifest(row, None)

    assert read_manifest(row) is None


@pytest.mark.parametrize("cleared", MANIFEST_COLUMNS)
def test_a_partial_manifest_is_refused_rather_than_loaded(cleared: str) -> None:
    """Three of the four facts do not address anything."""

    row = RunAttemptRow()
    write_manifest(row, factories.reference(key="training/run-9/manifest.json"))
    setattr(row, cleared, None)

    with pytest.raises(StoredRowInvalid):
        read_manifest(row)
