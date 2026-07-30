"""Where the database URL comes from, and the engine built from it.

A service is told its database by environment, never by a value passed through
a request, so the URL is read in one place and every service and the migration
runner read it the same way.

Three rules are enforced here rather than left to whatever fails first.

The dialect has to be PostgreSQL. The schema is written for it -- checked
state lists, ``timestamptz``, a real ``uuid`` type -- and a migration that
"succeeds" against SQLite proves nothing about the database the system runs
on, so a test pointed at one should stop rather than pass.

The driver has to be the installed one. A bare ``postgresql://`` URL is not
driver-agnostic to SQLAlchemy: it resolves to ``psycopg2``, which this package
does not install, so it would pass every check here and then fail on an import
inside engine creation. Such a URL is completed rather than refused, since
leaving the driver out is the ordinary thing to write; a URL that names a
different driver by hand is refused, because that is a choice this package
cannot honour.

Nothing echoes the URL. A connection URL carries a password, and the first
thing anyone does with a startup error is paste it somewhere.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from image_model_lab_persistence.errors import DatabaseUrlError

DATABASE_URL_VARIABLE: Final = "IMAGE_MODEL_LAB_DATABASE_URL"
"""Environment variable every service and the migration runner read."""

REQUIRED_BACKEND: Final = "postgresql"
"""The only database backend this schema is written for."""

DRIVER: Final = "psycopg"
"""The PostgreSQL driver this package depends on, and the only one installed.

A bare ``postgresql://`` URL does not mean "whatever driver is available" to
SQLAlchemy -- it resolves to ``psycopg2``, which is not here. So a URL without a
driver is completed with this one rather than accepted and left to fail later
inside :func:`create_database_engine` as an import error.
"""

REQUIRED_DRIVERNAME: Final = f"{REQUIRED_BACKEND}+{DRIVER}"
"""The fully qualified scheme every URL is normalised to."""


def require_database_url(environ: Mapping[str, str] | None = None) -> str:
    """Return the configured database URL, with its driver made explicit.

    A URL that names no driver is completed with :data:`DRIVER` rather than
    passed through. SQLAlchemy would otherwise resolve ``postgresql://`` to
    ``psycopg2`` and fail on the import, several steps after the check that was
    supposed to catch a bad configuration.

    Raises:
        DatabaseUrlError: if the variable is unset or empty, if the value is not
            a URL, if it names a backend other than PostgreSQL, or if it asks
            for a PostgreSQL driver other than the installed one. Neither the
            value nor the exception that rejected it is quoted back, since both
            can contain the password.
    """

    source = os.environ if environ is None else environ
    url_text = source.get(DATABASE_URL_VARIABLE, "").strip()
    if not url_text:
        raise DatabaseUrlError(
            f"{DATABASE_URL_VARIABLE} is not set; a service is told its database by "
            "environment and does not fall back to a default one"
        )

    try:
        url = make_url(url_text)
    except ArgumentError:
        raise DatabaseUrlError(
            f"{DATABASE_URL_VARIABLE} is not a database URL; expected "
            f"'{REQUIRED_DRIVERNAME}://<user>@<host>/<database>'"
        ) from None

    if url.get_backend_name() != REQUIRED_BACKEND:
        raise DatabaseUrlError(
            f"{DATABASE_URL_VARIABLE} names the {url.get_backend_name()!r} backend; this "
            f"schema is written for {REQUIRED_BACKEND} and its constraints, timestamps and "
            "identifier types do not carry over"
        )

    # `drivername`, not `get_driver_name()`: the latter reports the dialect's
    # default for a bare URL, so it cannot tell "unspecified" from "psycopg2
    # asked for by name". The first is completed; the second is a deliberate
    # choice this package cannot honour.
    if url.drivername == REQUIRED_BACKEND:
        return url.set(drivername=REQUIRED_DRIVERNAME).render_as_string(hide_password=False)
    if url.drivername != REQUIRED_DRIVERNAME:
        raise DatabaseUrlError(
            f"{DATABASE_URL_VARIABLE} asks for the {url.get_driver_name()!r} driver; this "
            f"package depends on {DRIVER!r} and installs no other, so the connection would "
            f"fail on the import. Use '{REQUIRED_DRIVERNAME}://' or leave the driver out."
        )
    return url_text


def create_database_engine(url: str, *, echo: bool = False) -> Engine:
    """Build an engine for ``url``.

    ``pool_pre_ping`` is on because the control plane holds connections idle
    between jobs and a NAS-side restart or a connection killed by the server
    should cost one retry rather than one failed request.
    """

    return create_engine(url, echo=echo, pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build the session factory the repositories are constructed from.

    ``expire_on_commit`` is off. Repositories return domain values that are
    already detached from the session, so expiring rows after a commit would
    only buy a reload nothing reads.
    """

    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


__all__ = [
    "DATABASE_URL_VARIABLE",
    "DRIVER",
    "REQUIRED_BACKEND",
    "REQUIRED_DRIVERNAME",
    "create_database_engine",
    "create_session_factory",
    "require_database_url",
]
