"""Reading the database URL, and what it refuses.

No database is involved. These are the checks that run before a connection is
attempted, and the reason they exist is that all three failures are quiet: an
unset variable that falls back to a default database, a URL naming an engine
the schema was never written for, and an error message carrying the password
into a log.
"""

from __future__ import annotations

import pytest
from image_model_lab_persistence import DATABASE_URL_VARIABLE, DatabaseUrlError
from image_model_lab_persistence.engine import require_database_url

PASSWORD = "s3cr3t-not-for-a-log"  # repo-policy: allow-secret
URL_WITH_PASSWORD = f"postgresql+psycopg://curator:{PASSWORD}@db.internal:5432/image_model_lab"


def test_a_postgres_url_is_returned_as_configured() -> None:
    assert require_database_url({DATABASE_URL_VARIABLE: URL_WITH_PASSWORD}) == URL_WITH_PASSWORD


def test_an_unset_variable_is_an_error_rather_than_a_default_database() -> None:
    with pytest.raises(DatabaseUrlError):
        require_database_url({})


def test_a_blank_variable_is_treated_as_unset() -> None:
    with pytest.raises(DatabaseUrlError):
        require_database_url({DATABASE_URL_VARIABLE: "   "})


def test_another_backend_is_refused() -> None:
    """A migration that succeeds against SQLite proves nothing about production."""

    with pytest.raises(DatabaseUrlError, match="sqlite"):
        require_database_url({DATABASE_URL_VARIABLE: "sqlite:///lab.db"})


def test_a_value_that_is_not_a_url_is_refused() -> None:
    with pytest.raises(DatabaseUrlError):
        require_database_url({DATABASE_URL_VARIABLE: "host=db.internal dbname=lab"})


@pytest.mark.parametrize(
    "configured",
    ["sqlite:///lab.db", "host=db.internal dbname=lab", f"mysql://curator:{PASSWORD}@db/lab"],
    ids=["other-backend", "not-a-url", "password-bearing"],
)
def test_a_rejection_never_quotes_the_configured_value(configured: str) -> None:
    """The first thing anyone does with a startup error is paste it somewhere."""

    with pytest.raises(DatabaseUrlError) as rejected:
        require_database_url({DATABASE_URL_VARIABLE: configured})

    assert PASSWORD not in str(rejected.value)
    assert configured not in str(rejected.value)
