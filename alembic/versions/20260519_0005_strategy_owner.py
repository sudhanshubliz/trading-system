from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260519_0005"
down_revision = "20260408_0004"
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
    if not _has_table("strategy_owner_candidates"):
        op.create_table(
            "strategy_owner_candidates",
            sa.Column("candidate_id", sa.String(length=64), primary_key=True),
            sa.Column("source_name", sa.String(length=64), nullable=False),
            sa.Column("strategy_family", sa.String(length=64), nullable=False),
            sa.Column("symbol_or_market", sa.String(length=128), nullable=False),
            sa.Column("direction", sa.String(length=16), nullable=False),
            sa.Column("overall_score", sa.Float(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("tradable", sa.String(length=8), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_strategy_owner_candidates_source_name", "strategy_owner_candidates", ["source_name"])
    _create_index_if_missing("ix_strategy_owner_candidates_strategy_family", "strategy_owner_candidates", ["strategy_family"])
    _create_index_if_missing("ix_strategy_owner_candidates_symbol_or_market", "strategy_owner_candidates", ["symbol_or_market"])
    _create_index_if_missing("ix_strategy_owner_candidates_direction", "strategy_owner_candidates", ["direction"])
    _create_index_if_missing("ix_strategy_owner_candidates_overall_score", "strategy_owner_candidates", ["overall_score"])
    _create_index_if_missing("ix_strategy_owner_candidates_confidence", "strategy_owner_candidates", ["confidence"])
    _create_index_if_missing("ix_strategy_owner_candidates_tradable", "strategy_owner_candidates", ["tradable"])
    _create_index_if_missing("ix_strategy_owner_candidates_generated_at", "strategy_owner_candidates", ["generated_at"])
    _create_index_if_missing("ix_strategy_owner_candidates_created_at", "strategy_owner_candidates", ["created_at"])
    _create_index_if_missing("ix_strategy_owner_candidates_updated_at", "strategy_owner_candidates", ["updated_at"])

    if not _has_table("strategy_owner_decisions"):
        op.create_table(
            "strategy_owner_decisions",
            sa.Column("decision_id", sa.String(length=64), primary_key=True),
            sa.Column("candidate_id", sa.String(length=64), nullable=False),
            sa.Column("source_name", sa.String(length=64), nullable=False),
            sa.Column("strategy_family", sa.String(length=64), nullable=False),
            sa.Column("symbol_or_market", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("overall_score", sa.Float(), nullable=False),
            sa.Column("forwarded_to_risk", sa.String(length=8), nullable=False),
            sa.Column("rejection_reason", sa.String(length=128), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_strategy_owner_decisions_candidate_id", "strategy_owner_decisions", ["candidate_id"])
    _create_index_if_missing("ix_strategy_owner_decisions_source_name", "strategy_owner_decisions", ["source_name"])
    _create_index_if_missing("ix_strategy_owner_decisions_strategy_family", "strategy_owner_decisions", ["strategy_family"])
    _create_index_if_missing("ix_strategy_owner_decisions_symbol_or_market", "strategy_owner_decisions", ["symbol_or_market"])
    _create_index_if_missing("ix_strategy_owner_decisions_status", "strategy_owner_decisions", ["status"])
    _create_index_if_missing("ix_strategy_owner_decisions_overall_score", "strategy_owner_decisions", ["overall_score"])
    _create_index_if_missing("ix_strategy_owner_decisions_forwarded_to_risk", "strategy_owner_decisions", ["forwarded_to_risk"])
    _create_index_if_missing("ix_strategy_owner_decisions_rejection_reason", "strategy_owner_decisions", ["rejection_reason"])
    _create_index_if_missing("ix_strategy_owner_decisions_decided_at", "strategy_owner_decisions", ["decided_at"])
    _create_index_if_missing("ix_strategy_owner_decisions_created_at", "strategy_owner_decisions", ["created_at"])


def downgrade() -> None:
    op.drop_table("strategy_owner_decisions")
    op.drop_table("strategy_owner_candidates")
