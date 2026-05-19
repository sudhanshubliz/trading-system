from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_runs_symbol", "feature_runs", ["symbol"])
    op.create_index("ix_feature_runs_generated_at", "feature_runs", ["generated_at"])
    op.create_table(
        "alpha_source_readings",
        sa.Column("reading_id", sa.String(length=64), primary_key=True),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("symbol_or_market", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("strategy_family", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alpha_source_readings_symbol_or_market", "alpha_source_readings", ["symbol_or_market"])
    op.create_index("ix_alpha_source_readings_source_name", "alpha_source_readings", ["source_name"])
    op.create_table(
        "fused_opportunities",
        sa.Column("opportunity_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol_or_market", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("fused_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("strategy_family", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fused_opportunities_symbol_or_market", "fused_opportunities", ["symbol_or_market"])
    op.create_index("ix_fused_opportunities_generated_at", "fused_opportunities", ["generated_at"])
    op.create_table(
        "regime_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("regime", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_regime_snapshots_symbol", "regime_snapshots", ["symbol"])
    op.create_index("ix_regime_snapshots_generated_at", "regime_snapshots", ["generated_at"])
    op.create_table(
        "wallet_profiles",
        sa.Column("wallet_id", sa.String(length=128), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "wallet_observations",
        sa.Column("observation_id", sa.String(length=64), primary_key=True),
        sa.Column("wallet_id", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "wallet_signals",
        sa.Column("signal_id", sa.String(length=64), primary_key=True),
        sa.Column("wallet_id", sa.String(length=128), nullable=False),
        sa.Column("symbol_or_market", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "arbitrage_opportunities",
        sa.Column("opportunity_id", sa.String(length=64), primary_key=True),
        sa.Column("market", sa.String(length=64), nullable=False),
        sa.Column("symbol_or_market", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "event_observations",
        sa.Column("observation_id", sa.String(length=64), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "event_signals",
        sa.Column("signal_id", sa.String(length=64), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("symbol_or_market", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "strategy_allocations",
        sa.Column("allocation_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("capital_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "promotion_reviews",
        sa.Column("review_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "execution_quality_records",
        sa.Column("record_id", sa.String(length=64), primary_key=True),
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "provider_health_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "risk_lock_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("lock_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.String(length=8), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "research_experiments",
        sa.Column("experiment_id", sa.String(length=64), primary_key=True),
        sa.Column("experiment_name", sa.String(length=128), nullable=False),
        sa.Column("strategy_family", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "experiment_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "experiment_artifacts",
        sa.Column("artifact_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("uri", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "operator_notes",
        sa.Column("note_id", sa.String(length=64), primary_key=True),
        sa.Column("note_type", sa.String(length=64), nullable=False),
        sa.Column("related_entity_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "incident_records",
        sa.Column("incident_id", sa.String(length=64), primary_key=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table_name in [
        "incident_records",
        "operator_notes",
        "experiment_artifacts",
        "experiment_runs",
        "research_experiments",
        "risk_lock_events",
        "provider_health_events",
        "execution_quality_records",
        "promotion_reviews",
        "strategy_allocations",
        "event_signals",
        "event_observations",
        "arbitrage_opportunities",
        "wallet_signals",
        "wallet_observations",
        "wallet_profiles",
        "regime_snapshots",
        "fused_opportunities",
        "alpha_source_readings",
        "feature_runs",
    ]:
        op.drop_table(table_name)
