from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260408_0003"
down_revision = "20260408_0002"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _has_table("polymarket_markets"):
        op.create_table(
            "polymarket_markets",
            sa.Column("market_id", sa.String(length=128), primary_key=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("event_slug", sa.String(length=128), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_polymarket_markets_status", "polymarket_markets", ["status"])
    _create_index_if_missing("ix_polymarket_markets_category", "polymarket_markets", ["category"])
    _create_index_if_missing("ix_polymarket_markets_event_slug", "polymarket_markets", ["event_slug"])
    _create_index_if_missing("ix_polymarket_markets_updated_at", "polymarket_markets", ["updated_at"])

    if not _has_table("polymarket_market_snapshots"):
        op.create_table(
            "polymarket_market_snapshots",
            sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
            sa.Column("market_id", sa.String(length=128), nullable=False),
            sa.Column("yes_price", sa.Float(), nullable=True),
            sa.Column("no_price", sa.Float(), nullable=True),
            sa.Column("spread_bps", sa.Float(), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_polymarket_market_snapshots_market_id", "polymarket_market_snapshots", ["market_id"])
    _create_index_if_missing("ix_polymarket_market_snapshots_yes_price", "polymarket_market_snapshots", ["yes_price"])
    _create_index_if_missing("ix_polymarket_market_snapshots_no_price", "polymarket_market_snapshots", ["no_price"])
    _create_index_if_missing("ix_polymarket_market_snapshots_spread_bps", "polymarket_market_snapshots", ["spread_bps"])
    _create_index_if_missing("ix_polymarket_market_snapshots_captured_at", "polymarket_market_snapshots", ["captured_at"])

    if not _has_table("linked_market_validations"):
        op.create_table(
            "linked_market_validations",
            sa.Column("validation_id", sa.String(length=64), primary_key=True),
            sa.Column("rule_name", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_linked_market_validations_rule_name", "linked_market_validations", ["rule_name"])
    _create_index_if_missing("ix_linked_market_validations_status", "linked_market_validations", ["status"])
    _create_index_if_missing("ix_linked_market_validations_detected_at", "linked_market_validations", ["detected_at"])

    if not _has_table("strategy_promotion_status"):
        op.create_table(
            "strategy_promotion_status",
            sa.Column("strategy_name", sa.String(length=128), primary_key=True),
            sa.Column("current_stage", sa.String(length=64), nullable=False),
            sa.Column("eligible_for_promotion", sa.String(length=8), nullable=False),
            sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_strategy_promotion_status_current_stage", "strategy_promotion_status", ["current_stage"])
    _create_index_if_missing(
        "ix_strategy_promotion_status_eligible_for_promotion",
        "strategy_promotion_status",
        ["eligible_for_promotion"],
    )
    _create_index_if_missing("ix_strategy_promotion_status_last_review_at", "strategy_promotion_status", ["last_review_at"])
    _create_index_if_missing("ix_strategy_promotion_status_updated_at", "strategy_promotion_status", ["updated_at"])

    if not _has_table("provider_health_snapshots"):
        op.create_table(
            "provider_health_snapshots",
            sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
            sa.Column("provider_name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_provider_health_snapshots_provider_name", "provider_health_snapshots", ["provider_name"])
    _create_index_if_missing("ix_provider_health_snapshots_status", "provider_health_snapshots", ["status"])
    _create_index_if_missing("ix_provider_health_snapshots_observed_at", "provider_health_snapshots", ["observed_at"])

    if not _has_table("alert_history"):
        op.create_table(
            "alert_history",
            sa.Column("alert_id", sa.String(length=64), primary_key=True),
            sa.Column("channel", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_alert_history_channel", "alert_history", ["channel"])
    _create_index_if_missing("ix_alert_history_severity", "alert_history", ["severity"])
    _create_index_if_missing("ix_alert_history_created_at", "alert_history", ["created_at"])

    if not _has_table("portfolio_brain_snapshots"):
        op.create_table(
            "portfolio_brain_snapshots",
            sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
            sa.Column("execution_mode", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_portfolio_brain_snapshots_execution_mode", "portfolio_brain_snapshots", ["execution_mode"])
    _create_index_if_missing("ix_portfolio_brain_snapshots_status", "portfolio_brain_snapshots", ["status"])
    _create_index_if_missing("ix_portfolio_brain_snapshots_generated_at", "portfolio_brain_snapshots", ["generated_at"])

    if not _has_table("mirofish_simulation_runs"):
        op.create_table(
            "mirofish_simulation_runs",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("symbol_or_market", sa.String(length=128), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_mirofish_simulation_runs_status", "mirofish_simulation_runs", ["status"])
    _create_index_if_missing("ix_mirofish_simulation_runs_symbol_or_market", "mirofish_simulation_runs", ["symbol_or_market"])
    _create_index_if_missing("ix_mirofish_simulation_runs_generated_at", "mirofish_simulation_runs", ["generated_at"])


def downgrade() -> None:
    op.drop_table("mirofish_simulation_runs")
    op.drop_table("portfolio_brain_snapshots")
    op.drop_table("alert_history")
    op.drop_table("provider_health_snapshots")
    op.drop_table("strategy_promotion_status")
    op.drop_table("linked_market_validations")
    op.drop_table("polymarket_market_snapshots")
    op.drop_table("polymarket_markets")
