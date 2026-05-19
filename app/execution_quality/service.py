from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.execution.types import Approval, Trade
from app.execution_quality.types import ExecutionQualityRecordData
from app.market_data.types import TickerSnapshot
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.execution_quality_repo import ExecutionQualityRepository
from app.risk.types import RiskAssessment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionQualityService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repo: ExecutionQualityRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo
        self.events_repo = events_repo
        self._records: OrderedDict[str, ExecutionQualityRecordData] = OrderedDict()

    def record_execution(
        self,
        *,
        trade: Trade,
        approval: Approval | None,
        assessment: RiskAssessment | None,
        snapshot: TickerSnapshot | None,
        mode: str,
        execution_policy: str,
        submit_timestamp: datetime | None = None,
        fill_timestamp: datetime | None = None,
        partial_fill_ratio: float = 1.0,
        notes: list[str] | None = None,
    ) -> ExecutionQualityRecordData:
        decision_timestamp = approval.approved_at if approval is not None else assessment.assessed_at if assessment is not None else None
        submit_timestamp = submit_timestamp or trade.opened_at
        fill_timestamp = fill_timestamp or trade.opened_at
        intended_price = trade.requested_entry_price
        arrival_mid = None
        if snapshot is not None and snapshot.bid_price is not None and snapshot.ask_price is not None:
            arrival_mid = (snapshot.bid_price + snapshot.ask_price) / 2
        elif snapshot is not None:
            arrival_mid = snapshot.last_price
        actual_fill = trade.execution_price
        expected_slippage_bps = min(
            self.settings.execution_max_expected_slippage_bps,
            self.settings.max_slippage_pct * 100,
        )
        reference_price = intended_price or arrival_mid or actual_fill or 0.0
        realized_slippage_bps = None
        if actual_fill is not None and reference_price:
            realized_slippage_bps = abs((actual_fill - reference_price) / reference_price) * 10000
        latency_ms = None
        if decision_timestamp is not None and fill_timestamp is not None:
            latency_ms = max(0.0, (fill_timestamp - decision_timestamp).total_seconds() * 1000.0)
        quality_score = self._score(
            expected_slippage_bps=expected_slippage_bps,
            realized_slippage_bps=realized_slippage_bps,
            latency_ms=latency_ms,
            partial_fill_ratio=partial_fill_ratio,
            snapshot=snapshot,
        )
        record = ExecutionQualityRecordData(
            record_id=self._build_id(trade.trade_id, fill_timestamp or trade.opened_at),
            trade_id=trade.trade_id,
            order_id=trade.client_order_id,
            symbol=trade.symbol,
            strategy_name=trade.strategy_name,
            mode=mode,
            intended_action=trade.side,
            execution_policy=execution_policy,
            decision_timestamp=decision_timestamp,
            submit_timestamp=submit_timestamp,
            fill_timestamp=fill_timestamp,
            intended_price=intended_price,
            arrival_mid_price=arrival_mid,
            actual_fill_price=actual_fill,
            expected_slippage_bps=round(expected_slippage_bps, 6) if expected_slippage_bps is not None else None,
            realized_slippage_bps=round(realized_slippage_bps, 6) if realized_slippage_bps is not None else None,
            latency_ms=round(latency_ms, 6) if latency_ms is not None else None,
            partial_fill_ratio=round(partial_fill_ratio, 6),
            fill_quality_score=round(quality_score, 6),
            notes=notes or [],
            explanation=self._explanation(quality_score, realized_slippage_bps, latency_ms, partial_fill_ratio),
            recorded_at=fill_timestamp or trade.opened_at,
        )
        if self.repo is not None:
            self.repo.upsert_record(record)
        self._records[record.record_id] = record
        self._records.move_to_end(record.record_id, last=False)
        while len(self._records) > 500:
            self._records.popitem(last=True)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="execution_quality_recorded",
                entity_id=record.record_id,
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                execution_mode=mode,
                payload={"quality_score": record.fill_quality_score, "execution_policy": record.execution_policy},
            )
        return record

    def list_records(
        self,
        *,
        mode: str | None = None,
        symbol: str | None = None,
        strategy_name: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[ExecutionQualityRecordData]:
        items = self.repo.list_records(
            mode=mode,
            symbol=symbol,
            strategy_name=strategy_name,
            min_score=min_score,
            max_score=max_score,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        ) if self.repo is not None else list(self._records.values())
        filtered = self._filter_records(
            items,
            mode=mode,
            symbol=symbol,
            strategy_name=strategy_name,
            min_score=min_score,
            max_score=max_score,
            start_time=start_time,
            end_time=end_time,
        )
        return filtered[: max(limit, 0)]

    def get_records_for_trade(self, trade_id: str) -> list[ExecutionQualityRecordData]:
        if self.repo is not None:
            return self.repo.get_by_trade_id(trade_id)
        return [item for item in self._records.values() if item.trade_id == trade_id]

    def recent_anomaly_state(self, *, limit: int = 10) -> dict[str, object]:
        records = self.list_records(limit=limit, max_score=self.settings.execution_quality_bad_score_threshold)
        return {
            "bad_record_count": len(records),
            "is_anomalous": len(records) >= 3,
        }

    def _filter_records(
        self,
        items: list[ExecutionQualityRecordData],
        *,
        mode: str | None,
        symbol: str | None,
        strategy_name: str | None,
        min_score: float | None,
        max_score: float | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[ExecutionQualityRecordData]:
        filtered = sorted(items, key=lambda item: item.recorded_at, reverse=True)
        if mode is not None:
            filtered = [item for item in filtered if item.mode == mode]
        if symbol is not None:
            filtered = [item for item in filtered if item.symbol == symbol.upper()]
        if strategy_name is not None:
            filtered = [item for item in filtered if item.strategy_name == strategy_name]
        if min_score is not None:
            filtered = [item for item in filtered if item.fill_quality_score >= min_score]
        if max_score is not None:
            filtered = [item for item in filtered if item.fill_quality_score <= max_score]
        if start_time is not None:
            filtered = [item for item in filtered if item.recorded_at >= start_time]
        if end_time is not None:
            filtered = [item for item in filtered if item.recorded_at <= end_time]
        return filtered

    def _score(
        self,
        *,
        expected_slippage_bps: float | None,
        realized_slippage_bps: float | None,
        latency_ms: float | None,
        partial_fill_ratio: float,
        snapshot: TickerSnapshot | None,
    ) -> float:
        score = 1.0
        if expected_slippage_bps is not None and realized_slippage_bps is not None and expected_slippage_bps > 0:
            slippage_ratio = min(realized_slippage_bps / expected_slippage_bps, 3.0)
            score -= min(0.45, max(0.0, slippage_ratio - 1.0) * 0.25)
        if latency_ms is not None:
            if latency_ms > 3000:
                score -= 0.25
            elif latency_ms > 1000:
                score -= 0.12
        score -= max(0.0, 1.0 - partial_fill_ratio) * 0.25
        if snapshot is not None and (snapshot.spread_bps or 0.0) > self.settings.microstructure_max_relative_spread_bps:
            score -= 0.1
        return max(0.0, min(1.0, score))

    def _explanation(self, quality_score: float, realized_slippage_bps: float | None, latency_ms: float | None, partial_fill_ratio: float) -> str:
        return (
            f"Quality={round(quality_score, 4)} with realized_slippage_bps={round(realized_slippage_bps, 4) if realized_slippage_bps is not None else None}, "
            f"latency_ms={round(latency_ms, 2) if latency_ms is not None else None}, partial_fill_ratio={round(partial_fill_ratio, 4)}."
        )

    def _build_id(self, trade_id: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{trade_id}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"eqr_{digest[:12]}"
