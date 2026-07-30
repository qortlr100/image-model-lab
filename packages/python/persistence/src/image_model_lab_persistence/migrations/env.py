"""Alembic environment for the image model lab schema.

The URL comes from the environment, the same way every service reads it, so a
migration is never run against a database written into a checked-in file. A
caller that already has a connection -- a test, or a service bringing its own
database up at startup -- passes it in ``config.attributes["connection"]``
instead, and the migration runs inside that caller's transaction.

``target_metadata`` is the mapping in :mod:`image_model_lab_persistence.tables`,
which is what lets an autogenerate comparison answer the question worth asking
after a mapping change: does a database built by the migrations still match the
code that reads it?
"""

from __future__ import annotations

from alembic import context
from image_model_lab_persistence.engine import create_database_engine, require_database_url
from image_model_lab_persistence.tables import METADATA
from sqlalchemy import Connection

target_metadata = METADATA


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without connecting to it."""

    context.configure(
        url=require_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_on(connection: Connection) -> None:
    """Run the migrations against an open connection."""

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations, reusing a caller's connection when one was supplied.

    Each revision runs inside a transaction, so PostgreSQL rolls a failed one
    back whole and the database is never left partway through a schema change.
    """

    supplied = context.config.attributes.get("connection")
    if isinstance(supplied, Connection):
        run_migrations_on(supplied)
        return

    engine = create_database_engine(require_database_url())
    try:
        with engine.connect() as connection:
            run_migrations_on(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
