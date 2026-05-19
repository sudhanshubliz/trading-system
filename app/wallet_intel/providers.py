from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.providers.common import (
    ExistingAsyncClientContext,
    FallbackProviderAdapter,
    ProviderRuntimeState,
    ensure_datetime,
    local_fallback_allowed,
    safe_float,
    utc_now,
)


class MockWalletProvider:
    def __init__(self) -> None:
        now = utc_now()
        self._wallets = {
            "wal_alpha": {
                "wallet_id": "wal_alpha",
                "first_seen": now - timedelta(days=180),
                "last_seen": now - timedelta(minutes=10),
                "trades": [
                    {
                        "market": "BTCUSDT",
                        "action": "buy",
                        "timestamp": now - timedelta(hours=4),
                        "conviction": 0.8,
                        "size": "medium",
                    },
                    {
                        "market": "pm_us_election_yes",
                        "action": "buy_yes",
                        "timestamp": now - timedelta(hours=2),
                        "conviction": 0.75,
                        "size": "large",
                    },
                ],
                "hit_rate": 0.61,
                "pnl_score": 0.72,
            },
            "wal_crowded": {
                "wallet_id": "wal_crowded",
                "first_seen": now - timedelta(days=90),
                "last_seen": now - timedelta(minutes=5),
                "trades": [
                    {
                        "market": "BTCUSDT",
                        "action": "sell",
                        "timestamp": now - timedelta(hours=1),
                        "conviction": 0.65,
                        "size": "small",
                    },
                    {
                        "market": "BTCUSDT",
                        "action": "sell",
                        "timestamp": now - timedelta(minutes=20),
                        "conviction": 0.55,
                        "size": "small",
                    },
                ],
                "hit_rate": 0.49,
                "pnl_score": 0.44,
            },
        }

    async def list_wallets(self) -> list[str]:
        return list(self._wallets.keys())

    async def get_wallet_profile(self, wallet_id: str) -> dict[str, object] | None:
        return self._wallets.get(wallet_id)

    async def get_wallet_positions(self, wallet_id: str) -> list[dict[str, object]]:
        profile = self._wallets.get(wallet_id)
        if profile is None:
            return []
        return [{"market": trade["market"], "direction": trade["action"]} for trade in profile["trades"][-2:]]

    async def get_wallet_trade_history(self, wallet_id: str) -> list[dict[str, object]]:
        profile = self._wallets.get(wallet_id)
        return list(profile["trades"]) if profile is not None else []

    async def get_wallet_activity_window(self, wallet_id: str) -> list[dict[str, object]]:
        return await self.get_wallet_trade_history(wallet_id)

    async def health_check(self) -> dict[str, object]:
        return {"status": "healthy", "success_rate": 1.0, "stale_data_flag": False, "error_count": 0}


class RealWalletProvider:
    def __init__(self, *, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._wallet_index: dict[str, dict[str, object]] = {}
        self._wallet_activity: dict[str, list[dict[str, object]]] = {}
        self._runtime = ProviderRuntimeState()

    @property
    def has_successful_fetch(self) -> bool:
        return self._runtime.has_successful_fetch

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.wallet_provider_base_url.strip())

    async def list_wallets(self) -> list[str]:
        payload = await self._request_json("/wallets")
        records = self._extract_records(payload, primary_keys=("wallets", "items", "data"))
        normalized = [self._normalize_wallet(item) for item in records if isinstance(item, dict)]
        self._wallet_index.update({item["wallet_id"]: item for item in normalized if item.get("wallet_id")})
        return list(self._wallet_index.keys())

    async def get_wallet_profile(self, wallet_id: str) -> dict[str, object] | None:
        normalized_id = self._normalize_wallet_id(wallet_id)
        if normalized_id in self._wallet_index:
            return dict(self._wallet_index[normalized_id])
        payload = await self._request_json(f"/wallets/{normalized_id}")
        record = self._extract_record(payload, preferred_keys=("wallet", "profile", "data"))
        if not isinstance(record, dict):
            return None
        item = self._normalize_wallet(record, fallback_wallet_id=normalized_id)
        self._wallet_index[item["wallet_id"]] = item
        return dict(item)

    async def get_wallet_positions(self, wallet_id: str) -> list[dict[str, object]]:
        normalized_id = self._normalize_wallet_id(wallet_id)
        try:
            payload = await self._request_json(f"/wallets/{normalized_id}/positions")
        except Exception:
            return []
        records = self._extract_records(payload, primary_keys=("positions", "items", "data"))
        return [self._normalize_position(item) for item in records if isinstance(item, dict)]

    async def get_wallet_trade_history(self, wallet_id: str) -> list[dict[str, object]]:
        normalized_id = self._normalize_wallet_id(wallet_id)
        if normalized_id in self._wallet_activity:
            return list(self._wallet_activity[normalized_id])
        payload = await self._request_json(f"/wallets/{normalized_id}/activity")
        records = self._extract_records(payload, primary_keys=("activity", "trades", "observations", "items", "data"))
        normalized = [self._normalize_trade(item, normalized_id) for item in records if isinstance(item, dict)]
        deduped: dict[str, dict[str, object]] = {}
        for item in normalized:
            key = f"{item['wallet_id']}|{item['market']}|{item['timestamp'].isoformat()}|{item['action']}"
            deduped[key] = item
        values = sorted(deduped.values(), key=lambda item: item["timestamp"], reverse=True)
        self._wallet_activity[normalized_id] = values
        return list(values)

    async def get_wallet_activity_window(self, wallet_id: str) -> list[dict[str, object]]:
        return await self.get_wallet_trade_history(wallet_id)

    async def health_check(self) -> dict[str, object]:
        return self._runtime.build_health(
            max_data_age_seconds=self.settings.wallet_max_data_age_seconds,
            metadata={"provider_mode": "real", "base_url": self.settings.wallet_provider_base_url},
            configured=self.is_configured,
        )

    def should_fallback_on_empty(self, method_name: str, value: object) -> bool:
        return not self.is_configured

    async def _request_json(self, path: str) -> Any:
        started_at = utc_now()
        try:
            async with self._get_client() as client:
                response = await client.get(path)
                response.raise_for_status()
                payload = response.json()
            self._runtime.record_success(started_at=started_at)
            return payload
        except Exception:
            self._runtime.record_failure()
            raise

    def _get_client(self):
        if self._client is not None:
            return ExistingAsyncClientContext(self._client)
        return httpx.AsyncClient(
            base_url=self.settings.wallet_provider_base_url.rstrip("/"),
            timeout=max(self.settings.wallet_provider_timeout_ms / 1000.0, 0.5),
            headers={"Accept": "application/json"},
        )

    def _extract_records(self, payload: Any, *, primary_keys: tuple[str, ...]) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in primary_keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            if isinstance(payload.get("result"), list):
                return payload["result"]
        return []

    def _extract_record(self, payload: Any, *, preferred_keys: tuple[str, ...]) -> Any:
        if isinstance(payload, dict):
            for key in preferred_keys:
                value = payload.get(key)
                if isinstance(value, dict):
                    return value
        return payload

    def _normalize_wallet(self, raw: dict[str, object], *, fallback_wallet_id: str | None = None) -> dict[str, object]:
        wallet_id = self._normalize_wallet_id(
            raw.get("wallet_id") or raw.get("wallet") or raw.get("address") or raw.get("id") or fallback_wallet_id or ""
        )
        first_seen = ensure_datetime(raw.get("first_seen") or raw.get("firstSeen") or raw.get("createdAt")) or utc_now()
        last_seen = ensure_datetime(raw.get("last_seen") or raw.get("lastSeen") or raw.get("updatedAt")) or utc_now()
        hit_rate = safe_float(raw.get("hit_rate") or raw.get("hitRate") or raw.get("winRate"), 0.5) or 0.5
        pnl_score = safe_float(raw.get("pnl_score") or raw.get("pnlScore") or raw.get("performanceScore"), 0.5) or 0.5
        return {
            "wallet_id": wallet_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "hit_rate": hit_rate,
            "pnl_score": pnl_score,
            "metadata": {
                "source": "wallet_real",
                "source_id": raw.get("id"),
                "provenance": raw.get("provider") or "external_wallet_feed",
            },
        }

    def _normalize_position(self, raw: dict[str, object]) -> dict[str, object]:
        return {
            "market": str(raw.get("market") or raw.get("symbol") or raw.get("event") or "unknown"),
            "direction": str(raw.get("direction") or raw.get("side") or raw.get("action") or "flat"),
            "size": safe_float(raw.get("size") or raw.get("quantity")),
        }

    def _normalize_trade(self, raw: dict[str, object], wallet_id: str) -> dict[str, object]:
        action = str(raw.get("action") or raw.get("side") or raw.get("direction") or "observe").lower()
        conviction = safe_float(raw.get("conviction") or raw.get("score") or raw.get("confidence"), 0.5) or 0.5
        size_value = safe_float(raw.get("notional_usd") or raw.get("notional") or raw.get("size") or raw.get("quantity"), 0.0) or 0.0
        if size_value >= 50000:
            size_bucket = "large"
        elif size_value >= 10000:
            size_bucket = "medium"
        else:
            size_bucket = "small"
        return {
            "wallet_id": wallet_id,
            "market": str(raw.get("market") or raw.get("symbol") or raw.get("event_market") or "unknown"),
            "action": action,
            "timestamp": ensure_datetime(raw.get("timestamp") or raw.get("observed_at") or raw.get("createdAt")) or utc_now(),
            "conviction": conviction,
            "size": size_bucket,
            "associated_event": raw.get("event_id"),
            "latency_seconds": safe_float(raw.get("latency_seconds") or raw.get("latency")),
            "metadata": {
                "source": "wallet_real",
                "provider_trade_id": raw.get("trade_id") or raw.get("id"),
                "raw_size": size_value,
            },
        }

    def _normalize_wallet_id(self, value: object) -> str:
        return str(value).strip().lower()


class FallbackWalletProvider:
    def __init__(self, *, real: RealWalletProvider, mock: object, allow_mock_fallback: bool) -> None:
        self._adapter = FallbackProviderAdapter(
            real=real,
            mock=mock,
            allow_mock_fallback=allow_mock_fallback,
            empty_fallback_methods={
                "list_wallets",
                "get_wallet_profile",
                "get_wallet_positions",
                "get_wallet_trade_history",
                "get_wallet_activity_window",
            },
        )

    async def list_wallets(self) -> list[str]:
        return await self._adapter.call("list_wallets")

    async def get_wallet_profile(self, wallet_id: str) -> dict[str, object] | None:
        return await self._adapter.call("get_wallet_profile", wallet_id)

    async def get_wallet_positions(self, wallet_id: str) -> list[dict[str, object]]:
        return await self._adapter.call("get_wallet_positions", wallet_id)

    async def get_wallet_trade_history(self, wallet_id: str) -> list[dict[str, object]]:
        return await self._adapter.call("get_wallet_trade_history", wallet_id)

    async def get_wallet_activity_window(self, wallet_id: str) -> list[dict[str, object]]:
        return await self._adapter.call("get_wallet_activity_window", wallet_id)

    async def health_check(self) -> dict[str, object]:
        return await self._adapter.health_check()


def build_wallet_provider(
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    mock_provider: object | None = None,
):
    resolved = settings or get_settings()
    mock = mock_provider or MockWalletProvider()
    mode = resolved.wallet_provider_mode
    if mode == "mock":
        return mock
    real = RealWalletProvider(settings=resolved, client=client)
    if mode == "real":
        return real
    return FallbackWalletProvider(
        real=real,
        mock=mock,
        allow_mock_fallback=local_fallback_allowed(resolved),
    )
