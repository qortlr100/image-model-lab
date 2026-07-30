"""The deployed constraints say what the domain lifecycles say.

The state columns are text with a ``CHECK`` listing the states, and that list
is generated from the domain ``StrEnum``. Generating it keeps the mapping from
drifting, but it cannot keep the *database* from drifting: the constraint in a
running database is whatever the last migration wrote, so adding a state to
the domain changes the mapping and leaves the deployed table behind.

This reads the constraint back out of the live database and compares it with
the enum. A new domain state fails here until a migration rewrites the
constraint, which is the point -- the alternative is a state the domain
happily produces and PostgreSQL rejects at insert time.
"""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from image_model_lab_domain import (
    ArtifactState,
    DatasetSnapshotState,
    ExecutionJobKind,
    ExecutionJobState,
    ProvenanceKind,
    RunAttemptState,
)
from sqlalchemy import Engine, text

STATE_CONSTRAINTS: tuple[tuple[str, str, type[StrEnum]], ...] = (
    ("artifacts", "ck_artifacts_state_is_known", ArtifactState),
    ("artifact_provenance", "ck_artifact_provenance_kind_is_known", ProvenanceKind),
    ("execution_jobs", "ck_execution_jobs_kind_is_known", ExecutionJobKind),
    ("execution_jobs", "ck_execution_jobs_state_is_known", ExecutionJobState),
    ("run_attempts", "ck_run_attempts_state_is_known", RunAttemptState),
    ("dataset_snapshots", "ck_dataset_snapshots_state_is_known", DatasetSnapshotState),
)
"""Every column whose allowed values are a domain lifecycle."""

_QUOTED = re.compile(r"'([^']*)'")

CONSTRAINT_SOURCE = text(
    "SELECT pg_get_constraintdef(pg_constraint.oid)"
    " FROM pg_constraint"
    " JOIN pg_class ON pg_class.oid = pg_constraint.conrelid"
    " WHERE pg_class.relname = :table AND pg_constraint.conname = :constraint"
)


@pytest.mark.parametrize(
    ("table", "constraint", "states"),
    STATE_CONSTRAINTS,
    ids=[constraint for _, constraint, _ in STATE_CONSTRAINTS],
)
def test_a_state_constraint_lists_exactly_the_domain_states(
    migrated_engine: Engine, table: str, constraint: str, states: type[StrEnum]
) -> None:
    with migrated_engine.connect() as connection:
        definition = connection.execute(
            CONSTRAINT_SOURCE, {"table": table, "constraint": constraint}
        ).scalar_one_or_none()

    assert definition is not None, f"{table} has no constraint named {constraint}"

    listed = set(_QUOTED.findall(definition))
    expected = {state.value for state in states}
    assert listed == expected, (
        f"{constraint} allows {sorted(listed)} but {states.__name__} has {sorted(expected)}. "
        "A lifecycle change needs a migration that rewrites the constraint."
    )
