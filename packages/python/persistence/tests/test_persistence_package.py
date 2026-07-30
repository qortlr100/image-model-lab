"""What the package ships, and where the mapping and the migrations live."""

from __future__ import annotations

from image_model_lab_persistence import METADATA, PACKAGE_NAME
from image_model_lab_persistence.schema import ALEMBIC_CONFIG_PATH

EXPECTED_TABLES = frozenset(
    {
        "artifacts",
        "artifact_provenance",
        "execution_jobs",
        "run_attempts",
        "dataset_snapshots",
        "snapshot_items",
    }
)


def test_package_name_is_stable() -> None:
    assert PACKAGE_NAME == "image-model-lab-persistence"


def test_the_mapping_covers_the_entities_that_have_a_lifecycle() -> None:
    assert set(METADATA.tables) == EXPECTED_TABLES


def test_the_migrations_ship_inside_the_package() -> None:
    """Whatever installs this package gets the migrations for its mapping.

    They are inside the package directory rather than beside it so the build
    includes them in the wheel. No deployment unit installs the package yet;
    this is about the packaging holding, not about a service using it.
    """

    assert ALEMBIC_CONFIG_PATH.is_file()
    versions = ALEMBIC_CONFIG_PATH.parent / "migrations" / "versions"
    assert sorted(path.name for path in versions.glob("*.py")) == ["0001_baseline_schema.py"]
