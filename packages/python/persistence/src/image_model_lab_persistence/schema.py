"""Running the migrations from code, and asking whether they are current.

The command line is the ordinary way in::

    just migrate upgrade head
    just migrate downgrade base

This module is the same thing for a caller that already holds a connection,
which today means the tests: they build a disposable database and bring it up
without going through the environment. It runs the revisions in
``migrations/versions`` like the command line does, so there is one description
of the schema and no second path that creates tables from the mapping directly.

A service bringing its own schema up at startup would use this too, but none
does yet -- no service image installs this package.

:func:`pending_changes` is the check worth running after a mapping change.
``METADATA`` describes what the code reads; the migrations describe what a
database actually gets. Comparing them catches the mapping edit that was never
given a migration -- which otherwise fails much later, on a deployment, as a
missing column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection

from image_model_lab_persistence.tables import METADATA

ALEMBIC_CONFIG_PATH: Final[Path] = Path(__file__).parent / "alembic.ini"
"""The packaged Alembic configuration, next to the migrations it points at."""

HEAD: Final = "head"
"""The newest revision."""

BASE: Final = "base"
"""Before the first revision, which for this schema is an empty database."""


def alembic_config(connection: Connection | None = None) -> Config:
    """Build the Alembic configuration, optionally bound to ``connection``.

    With a connection, the migrations run inside the caller's transaction and
    the environment's database URL is never read, so a test cannot reach a
    database other than the one it created.
    """

    config = Config(str(ALEMBIC_CONFIG_PATH))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade(connection: Connection, revision: str = HEAD) -> None:
    """Bring ``connection``'s database up to ``revision``."""

    command.upgrade(alembic_config(connection), revision)


def downgrade(connection: Connection, revision: str = BASE) -> None:
    """Take ``connection``'s database back down to ``revision``."""

    command.downgrade(alembic_config(connection), revision)


def pending_changes(connection: Connection) -> list[Any]:
    """Differences between the mapping and the database ``connection`` is on.

    An empty list means a database built by the migrations is the one the
    mapping describes. Anything in it is a mapping change that has not been
    given a migration yet.
    """

    context = MigrationContext.configure(connection)
    return list(compare_metadata(context, METADATA))


__all__ = [
    "ALEMBIC_CONFIG_PATH",
    "BASE",
    "HEAD",
    "alembic_config",
    "downgrade",
    "pending_changes",
    "upgrade",
]
