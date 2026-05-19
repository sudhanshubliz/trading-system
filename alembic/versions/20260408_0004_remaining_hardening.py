from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260408_0004"
down_revision = "20260408_0003"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _has_table("provider_ingest_runs"):
        op.create_table(
            "provider_ingest_runs",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column("provider_name", sa.String(length=64), nullable=False),
            sa.Column("dataset_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_provider_ingest_runs_provider_name", "provider_ingest_runs", ["provider_name"])
    _create_index_if_missing("ix_provider_ingest_runs_dataset_type", "provider_ingest_runs", ["dataset_type"])
    _create_index_if_missing("ix_provider_ingest_runs_status", "provider_ingest_runs", ["status"])
    _create_index_if_missing("ix_provider_ingest_runs_requested_at", "provider_ingest_runs", ["requested_at"])
    _create_index_if_missing("ix_provider_ingest_runs_completed_at", "provider_ingest_runs", ["completed_at"])

    if not _has_table("backfill_jobs"):
        op.create_table(
            "backfill_jobs",
            sa.Column("job_id", sa.String(length=64), primary_key=True),
            sa.Column("dataset_type", sa.String(length=64), nullable=False),
            sa.Column("provider_name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_backfill_jobs_dataset_type", "backfill_jobs", ["dataset_type"])
    _create_index_if_missing("ix_backfill_jobs_provider_name", "backfill_jobs", ["provider_name"])
    _create_index_if_missing("ix_backfill_jobs_status", "backfill_jobs", ["status"])
    _create_index_if_missing("ix_backfill_jobs_started_at", "backfill_jobs", ["started_at"])
    _create_index_if_missing("ix_backfill_jobs_finished_at", "backfill_jobs", ["finished_at"])

    if not _has_table("replay_fidelity_metadata"):
        op.create_table(
            "replay_fidelity_metadata",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column("fidelity_mode", sa.String(length=64), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_replay_fidelity_metadata_fidelity_mode", "replay_fidelity_metadata", ["fidelity_mode"])
    _create_index_if_missing("ix_replay_fidelity_metadata_generated_at", "replay_fidelity_metadata", ["generated_at"])

    with op.batch_alter_table("incident_records") as batch_op:
        if not _has_column("incident_records", "category"):
            batch_op.add_column(sa.Column("category", sa.String(length=64), nullable=True))
        if not _has_column("incident_records", "source"):
            batch_op.add_column(sa.Column("source", sa.String(length=64), nullable=True))
        if not _has_column("incident_records", "impacted_scope"):
            batch_op.add_column(sa.Column("impacted_scope", sa.String(length=64), nullable=True))
        if not _has_column("incident_records", "related_provider"):
            batch_op.add_column(sa.Column("related_provider", sa.String(length=64), nullable=True))
        if not _has_column("incident_records", "related_strategy"):
            batch_op.add_column(sa.Column("related_strategy", sa.String(length=128), nullable=True))
        if not _has_column("incident_records", "related_symbol_or_market"):
            batch_op.add_column(sa.Column("related_symbol_or_market", sa.String(length=128), nullable=True))
        if not _has_column("incident_records", "acknowledged_at"):
            batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column("incident_records", "resolved_at"):
            batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_index("incident_records", "ix_incident_records_category"):
            batch_op.create_index("ix_incident_records_category", ["category"])
        if not _has_index("incident_records", "ix_incident_records_source"):
            batch_op.create_index("ix_incident_records_source", ["source"])
        if not _has_index("incident_records", "ix_incident_records_impacted_scope"):
            batch_op.create_index("ix_incident_records_impacted_scope", ["impacted_scope"])
        if not _has_index("incident_records", "ix_incident_records_related_provider"):
            batch_op.create_index("ix_incident_records_related_provider", ["related_provider"])
        if not _has_index("incident_records", "ix_incident_records_related_strategy"):
            batch_op.create_index("ix_incident_records_related_strategy", ["related_strategy"])
        if not _has_index("incident_records", "ix_incident_records_related_symbol_or_market"):
            batch_op.create_index("ix_incident_records_related_symbol_or_market", ["related_symbol_or_market"])
        if not _has_index("incident_records", "ix_incident_records_acknowledged_at"):
            batch_op.create_index("ix_incident_records_acknowledged_at", ["acknowledged_at"])
        if not _has_index("incident_records", "ix_incident_records_resolved_at"):
            batch_op.create_index("ix_incident_records_resolved_at", ["resolved_at"])


def downgrade() -> None:
    with op.batch_alter_table("incident_records") as batch_op:
        batch_op.drop_index("ix_incident_records_resolved_at")
        batch_op.drop_index("ix_incident_records_acknowledged_at")
        batch_op.drop_index("ix_incident_records_related_symbol_or_market")
        batch_op.drop_index("ix_incident_records_related_strategy")
        batch_op.drop_index("ix_incident_records_related_provider")
        batch_op.drop_index("ix_incident_records_impacted_scope")
        batch_op.drop_index("ix_incident_records_source")
        batch_op.drop_index("ix_incident_records_category")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("related_symbol_or_market")
        batch_op.drop_column("related_strategy")
        batch_op.drop_column("related_provider")
        batch_op.drop_column("impacted_scope")
        batch_op.drop_column("source")
        batch_op.drop_column("category")

    op.drop_table("replay_fidelity_metadata")
    op.drop_table("backfill_jobs")
    op.drop_table("provider_ingest_runs")
