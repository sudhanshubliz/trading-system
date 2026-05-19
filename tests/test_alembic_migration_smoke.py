from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_creates_platform_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_smoke.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert "feature_runs" in tables
    assert "alpha_source_readings" in tables
    assert "fused_opportunities" in tables
    assert "regime_snapshots" in tables
    assert "research_experiments" in tables
    assert "experiment_runs" in tables
    assert "microstructure_feature_snapshots" in tables
    assert "polymarket_markets" in tables
    assert "polymarket_market_snapshots" in tables
    assert "linked_market_validations" in tables
    assert "provider_health_snapshots" in tables
    assert "provider_ingest_runs" in tables
    assert "strategy_promotion_status" in tables
    assert "alert_history" in tables
    assert "portfolio_brain_snapshots" in tables
    assert "mirofish_simulation_runs" in tables
    assert "backfill_jobs" in tables
    assert "replay_fidelity_metadata" in tables


def test_alembic_remaining_hardening_migration_is_safe_if_artifacts_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_partial_existing.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "20260408_0003")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE provider_ingest_runs (run_id VARCHAR(64) PRIMARY KEY, provider_name VARCHAR(64), dataset_type VARCHAR(64), status VARCHAR(32), requested_at DATETIME, completed_at DATETIME, payload_json TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE backfill_jobs (job_id VARCHAR(64) PRIMARY KEY, dataset_type VARCHAR(64), provider_name VARCHAR(64), status VARCHAR(32), started_at DATETIME, finished_at DATETIME, payload_json TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE replay_fidelity_metadata (run_id VARCHAR(64) PRIMARY KEY, fidelity_mode VARCHAR(64), generated_at DATETIME, payload_json TEXT)"
            )
        )
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN category VARCHAR(64)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN source VARCHAR(64)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN impacted_scope VARCHAR(64)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN related_provider VARCHAR(64)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN related_strategy VARCHAR(128)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN related_symbol_or_market VARCHAR(128)"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN acknowledged_at DATETIME"))
        connection.execute(text("ALTER TABLE incident_records ADD COLUMN resolved_at DATETIME"))

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "provider_ingest_runs" in inspector.get_table_names()
    assert "backfill_jobs" in inspector.get_table_names()
    assert "replay_fidelity_metadata" in inspector.get_table_names()
