"""Fixtures that put a real, disposable PostgreSQL in front of every test.

These tests are not run against SQLite. The schema's whole job is to say what
PostgreSQL will refuse -- checked state lists, ``timestamptz``, ``IS DISTINCT
FROM``, ``SELECT ... FOR UPDATE`` -- and a suite that passes on another engine
would be testing the mapping code while claiming to test the schema.

So a run needs a server, named by ``IMAGE_MODEL_LAB_TEST_DATABASE_URL``. There
is none in an ordinary ``just test``, which stays runnable with no GPU, no NAS
and no network, and the tests skip with the reason. CI runs them in a job with
a PostgreSQL service, and ``ops/dev/compose.yaml`` starts the same thing
locally.

Each database is created for the run and dropped afterwards, so nothing
depends on what a previous run left behind. Inside a run, each test gets a
connection whose transaction is rolled back at the end -- fast, and it means
one test's rows are never another's fixture.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from image_model_lab_persistence import DATABASE_URL_VARIABLE, require_database_url
from image_model_lab_persistence.schema import upgrade
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

TEST_DATABASE_URL_VARIABLE = "IMAGE_MODEL_LAB_TEST_DATABASE_URL"
"""Server these tests may create and drop databases on.

Deliberately not the variable a service reads. A suite that drops databases
must not be one environment variable away from doing it to a real one.
"""

REQUIRE_DATABASE_VARIABLE = "IMAGE_MODEL_LAB_REQUIRE_DATABASE"
"""Set where skipping would be a failure rather than a reasonable default.

The CI job that exists to run these tests sets it. Otherwise a service
container that never came up would turn that job into a green run of nothing,
which is the one outcome a database job must not be able to produce.
"""

SKIP_REASON = (
    f"{TEST_DATABASE_URL_VARIABLE} is not set; these tests need a PostgreSQL server they may "
    "create and drop databases on. See ops/dev/compose.yaml."
)


@pytest.fixture(scope="session")
def server_url() -> str:
    """The configured server URL, or skip the whole suite."""

    configured = os.environ.get(TEST_DATABASE_URL_VARIABLE, "").strip()
    if not configured:
        if os.environ.get(REQUIRE_DATABASE_VARIABLE, "").strip():
            pytest.fail(f"{REQUIRE_DATABASE_VARIABLE} is set but {SKIP_REASON}")
        pytest.skip(SKIP_REASON)
    return require_database_url({DATABASE_URL_VARIABLE: configured})


@contextmanager
def disposable_database(server_url: str) -> Generator[str]:
    """Create a uniquely named database, yield its URL, and drop it.

    ``CREATE DATABASE`` cannot run inside a transaction, hence the autocommit
    connection. The drop uses ``WITH (FORCE)`` so a connection this suite
    failed to close does not leave a database behind for the next run to trip
    over.
    """

    name = f"imllab_test_{uuid4().hex}"
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        # render_as_string, not str: str(URL) masks the password, and a URL
        # that cannot authenticate is a confusing way to fail.
        yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    finally:
        try:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            admin.dispose()


@pytest.fixture
def empty_database(server_url: str) -> Iterator[str]:
    """A database with no schema at all, for one test.

    The migration tests need this: "upgrade and downgrade succeed on an empty
    database" is only answered by a database nothing has touched.
    """

    with disposable_database(server_url) as url:
        yield url


@pytest.fixture(scope="session")
def migrated_engine(server_url: str) -> Iterator[Engine]:
    """One database per session, brought up to head by the migrations.

    Through the migrations rather than ``metadata.create_all``: the repository
    tests should run against the schema a deployment actually gets, so a
    migration that disagrees with the mapping fails here rather than on a
    deployment.
    """

    with disposable_database(server_url) as url:
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                upgrade(connection)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    """A session on a transaction that is rolled back when the test ends.

    The repositories flush and never commit, so the rollback undoes the whole
    test. Anything a repository writes is still visible to the reads in the
    same test, which is the behaviour a use case gets inside its transaction.
    """

    with migrated_engine.connect() as raw:
        transaction = raw.begin()
        try:
            with Session(bind=raw, expire_on_commit=False) as opened:
                yield opened
        finally:
            # A test that provoked an integrity error already rolled this
            # transaction back through the session, so the check is not
            # defensive: rolling back twice is what raises here.
            if transaction.is_active:
                transaction.rollback()
