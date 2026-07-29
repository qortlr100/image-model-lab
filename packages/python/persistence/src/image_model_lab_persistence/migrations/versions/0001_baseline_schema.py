"""Baseline schema: artifacts, provenance, jobs, attempts and snapshots.

The first revision. It creates the tables for the four domain entities that
have a lifecycle, and the two ordered child tables that belong to them.

Every ``CHECK`` here restates a rule the domain already enforces. That is
deliberate rather than redundant: the entities are what a use case is stopped
by, and these are what a restore, a hand-edited fix or a future writer is
stopped by. Nothing is enforced *only* here, so reading the tables never
reveals a rule the domain does not have.

The downgrade drops everything in dependency order, which for a baseline means
returning to an empty database. It is exercised on every run of the
persistence integration tests, so the path back stays real rather than
theoretical.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("logical_uri", sa.String(length=1040), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "state IN ('available', 'missing', 'pending', 'quarantined')",
            name=op.f("ck_artifacts_state_is_known"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_artifacts_size_bytes_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("logical_uri", name=op.f("uq_artifacts_logical_uri")),
    )
    op.create_index(op.f("ix_artifacts_sha256"), "artifacts", ["sha256"], unique=False)

    op.create_table(
        "artifact_provenance",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_label", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "CASE WHEN kind = 'ingested'"
            " THEN source_label IS NOT NULL AND source_id IS NULL"
            " ELSE source_id IS NOT NULL AND source_label IS NULL END",
            name=op.f("ck_artifact_provenance_source_matches_kind"),
        ),
        sa.CheckConstraint(
            "kind IN ('derived', 'ingested', 'run_output')",
            name=op.f("ck_artifact_provenance_kind_is_known"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_artifact_provenance_position_not_negative")
        ),
        sa.CheckConstraint(
            "source_id IS DISTINCT FROM artifact_id",
            name=op.f("ck_artifact_provenance_source_is_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_artifact_provenance_artifact_id_artifacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artifact_id", "position", name=op.f("pk_artifact_provenance")),
    )

    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "kind IN ('caption', 'training')", name=op.f("ck_execution_jobs_kind_is_known")
        ),
        sa.CheckConstraint(
            "state IN ('cancel_requested', 'cancelled', 'failed', 'leased', 'queued',"
            " 'running', 'succeeded')",
            name=op.f("ck_execution_jobs_state_is_known"),
        ),
        sa.CheckConstraint("priority >= 0", name=op.f("ck_execution_jobs_priority_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_execution_jobs_idempotency_key")),
    )

    op.create_table(
        "run_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("manifest_logical_uri", sa.String(length=1040), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("manifest_media_type", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "(state = 'running') = (ended_at IS NULL)",
            name=op.f("ck_run_attempts_ended_at_matches_state"),
        ),
        sa.CheckConstraint(
            "state <> 'succeeded' OR (manifest_logical_uri IS NOT NULL"
            " AND manifest_sha256 IS NOT NULL AND manifest_size_bytes IS NOT NULL"
            " AND manifest_media_type IS NOT NULL)",
            name=op.f("ck_run_attempts_succeeded_has_manifest"),
        ),
        sa.CheckConstraint(
            "state IN ('abandoned', 'cancelled', 'failed', 'running', 'succeeded')",
            name=op.f("ck_run_attempts_state_is_known"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('running', 'abandoned') OR (manifest_logical_uri IS NULL"
            " AND manifest_sha256 IS NULL AND manifest_size_bytes IS NULL"
            " AND manifest_media_type IS NULL)",
            name=op.f("ck_run_attempts_unfinalized_has_no_manifest"),
        ),
        sa.CheckConstraint(
            "(manifest_logical_uri IS NOT NULL AND manifest_sha256 IS NOT NULL"
            " AND manifest_size_bytes IS NOT NULL AND manifest_media_type IS NOT NULL)"
            " OR (manifest_logical_uri IS NULL AND manifest_sha256 IS NULL"
            " AND manifest_size_bytes IS NULL AND manifest_media_type IS NULL)",
            name=op.f("ck_run_attempts_manifest_whole_or_absent"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name=op.f("ck_run_attempts_ended_at_not_before_started_at"),
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_run_attempts_number_starts_at_one")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["execution_jobs.id"], name=op.f("fk_run_attempts_job_id_execution_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_attempts")),
        sa.UniqueConstraint("job_id", "number", name=op.f("uq_run_attempts_job_id_number")),
    )
    op.create_index(op.f("ix_run_attempts_job_id"), "run_attempts", ["job_id"], unique=False)

    op.create_table(
        "dataset_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest_logical_uri", sa.String(length=1040), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("manifest_media_type", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "(state = 'sealed') = (manifest_logical_uri IS NOT NULL"
            " AND manifest_sha256 IS NOT NULL AND manifest_size_bytes IS NOT NULL"
            " AND manifest_media_type IS NOT NULL)",
            name=op.f("ck_dataset_snapshots_manifest_matches_state"),
        ),
        sa.CheckConstraint(
            "(state = 'sealed') = (sealed_at IS NOT NULL)",
            name=op.f("ck_dataset_snapshots_sealed_at_matches_state"),
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'rejected', 'sealed', 'validating')",
            name=op.f("ck_dataset_snapshots_state_is_known"),
        ),
        sa.CheckConstraint(
            "(manifest_logical_uri IS NOT NULL AND manifest_sha256 IS NOT NULL"
            " AND manifest_size_bytes IS NOT NULL AND manifest_media_type IS NOT NULL)"
            " OR (manifest_logical_uri IS NULL AND manifest_sha256 IS NULL"
            " AND manifest_size_bytes IS NULL AND manifest_media_type IS NULL)",
            name=op.f("ck_dataset_snapshots_manifest_whole_or_absent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_snapshots")),
    )
    op.create_index(
        op.f("ix_dataset_snapshots_dataset_id"), "dataset_snapshots", ["dataset_id"], unique=False
    )

    op.create_table(
        "snapshot_items",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("asset_revision_id", sa.Uuid(), nullable=False),
        sa.Column("caption_revision_id", sa.Uuid(), nullable=False),
        sa.Column("caption_approved", sa.Boolean(), nullable=False),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.CheckConstraint("caption_approved", name=op.f("ck_snapshot_items_caption_is_approved")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_snapshot_items_position_not_negative")),
        sa.CheckConstraint("repeats >= 1", name=op.f("ck_snapshot_items_repeats_at_least_one")),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["dataset_snapshots.id"],
            name=op.f("fk_snapshot_items_snapshot_id_dataset_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "position", name=op.f("pk_snapshot_items")),
        sa.UniqueConstraint(
            "snapshot_id",
            "asset_revision_id",
            name=op.f("uq_snapshot_items_snapshot_id_asset_revision_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("snapshot_items")
    op.drop_index(op.f("ix_dataset_snapshots_dataset_id"), table_name="dataset_snapshots")
    op.drop_table("dataset_snapshots")
    op.drop_index(op.f("ix_run_attempts_job_id"), table_name="run_attempts")
    op.drop_table("run_attempts")
    op.drop_table("execution_jobs")
    op.drop_table("artifact_provenance")
    op.drop_index(op.f("ix_artifacts_sha256"), table_name="artifacts")
    op.drop_table("artifacts")
