"""The baseline migration runs both ways on an empty database.

Two claims are checked here, and they are different claims.

Upgrading proves the schema can be created. Downgrading proves it can be
taken back out -- which is the half that rots, because nobody exercises it
until a deployment has already gone wrong. A migration whose downgrade was
never run is not a downgrade path; it is an untested guess about one.

The comparison against the mapping is the third claim: that a database built
by the migrations is the database the code expects to read. Without it, the
mapping and the migrations drift apart silently and only meet on a deployment.
"""

from __future__ import annotations

from image_model_lab_persistence.schema import downgrade, pending_changes, upgrade
from image_model_lab_persistence.tables import METADATA
from sqlalchemy import Engine, create_engine, inspect

EXPECTED_TABLES = frozenset(METADATA.tables)
"""Every table the mapping describes, which is what an upgrade must create."""

VERSION_TABLE = "alembic_version"
"""Alembic's own bookkeeping. It outlives a downgrade to base, holding no row."""


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_creates_every_mapped_table_on_an_empty_database(empty_database: str) -> None:
    engine = create_engine(empty_database)
    try:
        assert not table_names(engine), "the fixture database was not empty to begin with"

        with engine.begin() as connection:
            upgrade(connection)

        assert table_names(engine) >= EXPECTED_TABLES
    finally:
        engine.dispose()


def test_downgrade_returns_an_upgraded_database_to_empty(empty_database: str) -> None:
    engine = create_engine(empty_database)
    try:
        with engine.begin() as connection:
            upgrade(connection)
        with engine.begin() as connection:
            downgrade(connection)

        remaining = table_names(engine)
        assert remaining <= {VERSION_TABLE}, (
            f"downgrade left {sorted(remaining - {VERSION_TABLE})} behind; a downgrade path that "
            "only half runs is worse than none, because it fails partway through a rollback"
        )
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_leaves_the_same_schema(empty_database: str) -> None:
    """A downgrade that dropped the wrong thing shows up on the way back up."""

    engine = create_engine(empty_database)
    try:
        with engine.begin() as connection:
            upgrade(connection)
        first = table_names(engine)
        with engine.begin() as connection:
            downgrade(connection)
        with engine.begin() as connection:
            upgrade(connection)

        assert table_names(engine) == first
    finally:
        engine.dispose()


def test_a_migrated_database_matches_the_mapping(migrated_engine: Engine) -> None:
    """No mapping change is missing a migration."""

    with migrated_engine.connect() as connection:
        differences = pending_changes(connection)

    assert not differences, (
        "the mapping and the migrations disagree: "
        f"{differences}. A mapping change needs a migration, or the migration needs correcting."
    )
