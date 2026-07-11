from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260408_0002"
down_revision = "20260408_0001"
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
    if not _has_table("microstructure_feature_snapshots"):
        op.create_table(
            "microstructure_feature_snapshots",
            sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("signal_policy", sa.String(length=64), nullable=False),
            sa.Column("state", sa.String(length=64), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing(
        "ix_microstructure_feature_snapshots_symbol",
        "microstructure_feature_snapshots",
        ["symbol"],
    )
    _create_index_if_missing(
        "ix_microstructure_feature_snapshots_generated_at",
        "microstructure_feature_snapshots",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_table("microstructure_feature_snapshots")
