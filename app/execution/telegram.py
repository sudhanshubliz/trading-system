from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.config.settings import Settings, get_settings
from app.execution.types import Approval, ControlStatus, PnlSummary, Position
from app.ops.types import IncidentSummary, OperatorStatus, RecoveryReport
from app.risk.types import RiskSummary


def format_approval_message(approval: Approval) -> str:
    return (
        f"Approval {approval.approval_id}\n"
        f"Symbol: {approval.symbol}\n"
        f"Side: {approval.side}\n"
        f"Strategy: {approval.strategy_name}\n"
        f"Status: {approval.status}\n"
        f"Execution mode: {approval.execution_mode}"
    )


def format_positions_message(positions: list[Position]) -> str:
    if not positions:
        return "No open or historical paper positions."
    lines = ["Paper Positions"]
    for position in positions:
        lines.append(
            f"{position.symbol} {position.side} qty={position.quantity_open:.6f} "
            f"entry={position.entry_price:.2f} current={position.current_price:.2f} "
            f"status={position.status}"
        )
    return "\n".join(lines)


def format_pnl_message(summary: PnlSummary) -> str:
    return (
        "Paper PnL\n"
        f"Realized: {summary.realized_pnl_total:.2f}\n"
        f"Unrealized: {summary.unrealized_pnl_total:.2f}\n"
        f"Daily: {summary.daily_pnl:.2f}"
    )


def format_control_message(status: ControlStatus) -> str:
    return (
        "Execution Control\n"
        f"Paused: {status.paused}\n"
        f"Execution mode: {status.execution_mode}\n"
        f"Paper enabled: {status.paper_trading_enabled}\n"
        f"Telegram simulation: {status.telegram_simulation_mode}"
    )


def format_risk_message(summary: RiskSummary) -> str:
    return (
        "Risk Summary\n"
        f"Balance: {summary.account_balance:.2f}\n"
        f"Equity: {summary.equity:.2f}\n"
        f"Open risk %: {summary.open_risk_pct:.2f}\n"
        f"Open positions: {summary.open_positions}\n"
        f"Global risk lock: {summary.global_risk_lock}"
    )


def format_live_status_message(status: Any) -> str:
    payload = asdict(status) if is_dataclass(status) else dict(status)
    active_locks = payload.get("active_locks") or []
    lines = [
        "Live Status",
        f"Enabled: {payload.get('enabled')}",
        f"Armed: {payload.get('armed')}",
        f"Can execute: {payload.get('can_execute')}",
        f"Global pause: {payload.get('global_pause')}",
        f"Stale market data: {payload.get('stale_market_data')}",
        f"Open live positions: {payload.get('open_live_positions')}",
        f"Daily live pnl: {float(payload.get('daily_live_pnl', 0.0)):.2f}",
        f"Weekly live pnl: {float(payload.get('weekly_live_pnl', 0.0)):.2f}",
        f"Active locks: {len(active_locks)}",
    ]
    if active_locks:
        for lock in active_locks:
            item = asdict(lock) if is_dataclass(lock) else dict(lock)
            lines.append(f"- {item.get('lock_type')} ({item.get('lock_id')}): {item.get('reason')}")
    return "\n".join(lines)


def format_live_locks_message(locks: list[Any]) -> str:
    if not locks:
        return "No live locks."
    lines = ["Live Locks"]
    for lock in locks:
        item = asdict(lock) if is_dataclass(lock) else dict(lock)
        lines.append(f"{item.get('lock_id')} {item.get('lock_type')} active={item.get('is_active')} reason={item.get('reason')}")
    return "\n".join(lines)


def format_incidents_message(summary: IncidentSummary) -> str:
    lines = [
        "Incidents",
        f"Status: {summary.status}",
        f"Active locks: {summary.active_lock_count}",
        f"Critical events: {summary.critical_event_count}",
    ]
    if summary.pending_actions:
        lines.append("Pending actions:")
        for item in summary.pending_actions:
            lines.append(f"- {item}")
    for item in summary.items[:5]:
        lines.append(f"[{item.severity}] {item.category}: {item.message}")
    return "\n".join(lines)


def format_recovery_message(report: RecoveryReport) -> str:
    return (
        "Recovery\n"
        f"Type: {report.recovery_type}\n"
        f"OK: {report.ok}\n"
        f"Open positions rebuilt: {report.open_positions_rebuilt}\n"
        f"Pending approvals reloaded: {report.pending_approvals_reloaded}\n"
        f"Active locks reloaded: {report.active_locks_reloaded}\n"
        f"Live armed: {report.live_armed}\n"
        f"Reconciliation attempted: {report.reconciliation_attempted}\n"
        f"Reconciliation ok: {report.reconciliation_ok}\n"
        f"Issues: {', '.join(report.issues) if report.issues else 'none'}"
    )


def format_rollout_status_message(payload: dict[str, Any]) -> str:
    lines = [
        "Rollout Status",
        f"Phase: {payload.get('current_phase')}",
        f"Capital limit: {float(payload.get('current_capital_limit', 0.0)):.2f}",
        f"Allowed phase cap: {float(payload.get('allowed_capital_limit', 0.0)):.2f}",
        f"Deployed capital: {float(payload.get('deployed_capital', 0.0)):.2f}",
        f"Remaining capital: {float(payload.get('remaining_capital', 0.0)):.2f}",
        f"Rollback active: {payload.get('rollback_active')}",
        f"Live effectively allowed: {payload.get('live_effectively_allowed', False)}",
    ]
    strategy_allocations = payload.get("strategy_allocations") or {}
    symbol_allocations = payload.get("symbol_allocations") or {}
    if strategy_allocations:
        lines.append("Strategy allocations:")
        for key, value in strategy_allocations.items():
            lines.append(f"- {key}: {float(value):.2f}")
    if symbol_allocations:
        lines.append("Symbol allocations:")
        for key, value in symbol_allocations.items():
            lines.append(f"- {key}: {float(value):.2f}")
    return "\n".join(lines)


def format_portfolio_status_message(payload: dict[str, Any]) -> str:
    lines = [
        "Portfolio Status",
        f"Mode: {payload.get('execution_mode')}",
        f"Deployed capital: {float(payload.get('deployed_capital', 0.0)):.2f}",
        f"Free cash: {float(payload.get('free_cash', 0.0)):.2f}",
        f"Reserved cash: {float(payload.get('reserved_cash', 0.0)):.2f}",
        f"Pending candidates: {payload.get('pending_candidate_count', 0)}",
        f"Rejected candidates: {payload.get('rejected_candidate_count', 0)}",
    ]
    strategy_allocations = payload.get("strategy_allocations") or {}
    if strategy_allocations:
        lines.append("Top strategies:")
        for item in list(strategy_allocations.values())[:5]:
            strategy_name = item.get("strategy_name") if isinstance(item, dict) else getattr(item, "strategy_name", "")
            deployed = item.get("deployed_capital") if isinstance(item, dict) else getattr(item, "deployed_capital", 0.0)
            pnl_total = item.get("pnl_total") if isinstance(item, dict) else getattr(item, "pnl_total", 0.0)
            lines.append(f"- {strategy_name}: deployed={float(deployed):.2f} pnl={float(pnl_total):.2f}")
    symbol_allocations = payload.get("symbol_allocations") or {}
    if symbol_allocations:
        lines.append("Top symbols:")
        for item in list(symbol_allocations.values())[:5]:
            symbol = item.get("symbol") if isinstance(item, dict) else getattr(item, "symbol", "")
            deployed = item.get("deployed_capital") if isinstance(item, dict) else getattr(item, "deployed_capital", 0.0)
            pnl_total = item.get("pnl_total") if isinstance(item, dict) else getattr(item, "pnl_total", 0.0)
            lines.append(f"- {symbol}: deployed={float(deployed):.2f} pnl={float(pnl_total):.2f}")
    return "\n".join(lines)


def format_analytics_summary_message(payload: dict[str, Any], *, title: str) -> str:
    lines = [title]
    if "current_regime" in payload:
        lines.append(f"Current regime: {payload['current_regime']}")
    if "total_pnl" in payload:
        lines.append(f"Total pnl: {float(payload['total_pnl']):.2f}")
    items = payload.get("items") or []
    for item in items[:5]:
        if "strategy_name" in item:
            lines.append(
                f"- {item['strategy_name']}: pnl={float(item['total_pnl']):.2f} win_rate={float(item['win_rate']):.2f}"
            )
        elif "symbol" in item:
            lines.append(
                f"- {item['symbol']}: pnl={float(item['total_pnl']):.2f} win_rate={float(item['win_rate']):.2f}"
            )
    return "\n".join(lines)


def build_confirmation_prompt(command: str, arg: str | None = None) -> str:
    mapping = {
        "/arm_live": "CONFIRM_ARM",
        "/disarm_live": "CONFIRM_DISARM",
        "/resume": "CONFIRM_RESUME",
        "/clear_lock": "CONFIRM_CLEAR_LOCK",
        "/set_rollout_phase": "CONFIRM_SET_ROLLOUT_PHASE",
        "/scale_up": "CONFIRM_SCALE_UP",
        "/scale_down": "CONFIRM_SCALE_DOWN",
        "/rollback_live": "CONFIRM_ROLLBACK_LIVE",
    }
    token = mapping[command]
    if arg:
        return f"{token} {arg}"
    return token


class TelegramRuntimeController:
    async def handle_command(
        self,
        command_text: str,
        *,
        execution_service: Any,
        risk_service: Any | None = None,
        shadow_service: Any | None = None,
        live_controller: Any | None = None,
        ops_service: Any | None = None,
        rollout_service: Any | None = None,
        portfolio_service: Any | None = None,
        analytics_service: Any | None = None,
        settings: Settings | None = None,
    ) -> str:
        runtime_settings = settings or getattr(execution_service, "settings", None) or get_settings()
        command = command_text.strip()
        if command == "/positions":
            return format_positions_message(await execution_service.get_positions())
        if command == "/pnl":
            return format_pnl_message(await execution_service.get_pnl_summary())
        if command == "/risk":
            if risk_service is None:
                return "Risk service unavailable."
            return format_risk_message(risk_service.get_summary())
        if command == "/pause":
            return format_control_message(await execution_service.pause())
        if command == "/resume":
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/resume")
            return format_control_message(await execution_service.resume())
        if command == "CONFIRM_RESUME":
            return format_control_message(await execution_service.resume())
        if command == "/live_status":
            if live_controller is None:
                return "Live controller unavailable."
            return format_live_status_message(await live_controller.get_live_status())
        if command == "/arm_live":
            if live_controller is None:
                return "Live controller unavailable."
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/arm_live")
            return format_live_status_message(await live_controller.arm_live_trading())
        if command == "CONFIRM_ARM":
            if live_controller is None:
                return "Live controller unavailable."
            return format_live_status_message(await live_controller.arm_live_trading())
        if command == "/disarm_live":
            if live_controller is None:
                return "Live controller unavailable."
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/disarm_live")
            return format_live_status_message(await live_controller.disarm_live_trading())
        if command == "CONFIRM_DISARM":
            if live_controller is None:
                return "Live controller unavailable."
            return format_live_status_message(await live_controller.disarm_live_trading())
        if command == "/locks":
            if live_controller is None:
                return "Live controller unavailable."
            return format_live_locks_message(live_controller.list_locks())
        if command == "/incidents":
            if ops_service is None:
                return "Ops service unavailable."
            return format_incidents_message(await ops_service.get_incident_summary())
        if command == "/recover":
            if ops_service is None:
                return "Ops service unavailable."
            return format_recovery_message(await ops_service.run_recovery())
        if command == "/rollout_status":
            if rollout_service is None:
                return "Rollout service unavailable."
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "/capital_status":
            if rollout_service is None:
                return "Rollout service unavailable."
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "/portfolio_status":
            if portfolio_service is None:
                return "Portfolio service unavailable."
            return format_portfolio_status_message(asdict(portfolio_service.get_portfolio_state("paper")))
        if command == "/allocations":
            if portfolio_service is None:
                return "Portfolio service unavailable."
            return format_portfolio_status_message(portfolio_service.get_allocations("paper"))
        if command == "/rebalance":
            if portfolio_service is None:
                return "Portfolio service unavailable."
            payload = portfolio_service.rebalance_portfolio("paper")
            return f"Rebalance\nEnabled: {payload['enabled']}\nActions: {payload['action_count']}"
        if command == "/strategy_stats":
            if analytics_service is None:
                return "Analytics service unavailable."
            return format_analytics_summary_message(
                analytics_service.get_strategy_attribution(),
                title="Strategy Stats",
            )
        if command == "/symbol_stats":
            if analytics_service is None:
                return "Analytics service unavailable."
            return format_analytics_summary_message(
                analytics_service.get_symbol_attribution(),
                title="Symbol Stats",
            )
        if command == "/regime_status":
            if analytics_service is None:
                return "Analytics service unavailable."
            payload = analytics_service.get_regime_summary()
            return (
                "Regime Status\n"
                f"Current regime: {payload['current_regime']}\n"
                f"Supported: {', '.join(payload['supported_regimes'])}"
            )
        if command.startswith("/set_rollout_phase "):
            if rollout_service is None:
                return "Rollout service unavailable."
            phase = command.split(maxsplit=1)[1].strip().lower()
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/set_rollout_phase", phase)
            rollout_service.set_rollout_phase(phase, changed_by="telegram", reason=f"telegram_set_phase_{phase}")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command.startswith("CONFIRM_SET_ROLLOUT_PHASE "):
            if rollout_service is None:
                return "Rollout service unavailable."
            phase = command.split(maxsplit=1)[1].strip().lower()
            rollout_service.set_rollout_phase(phase, changed_by="telegram", reason=f"telegram_set_phase_{phase}")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "/scale_up":
            if rollout_service is None:
                return "Rollout service unavailable."
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/scale_up")
            rollout_service.scale_up(changed_by="telegram", reason="telegram_scale_up")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "CONFIRM_SCALE_UP":
            if rollout_service is None:
                return "Rollout service unavailable."
            rollout_service.scale_up(changed_by="telegram", reason="telegram_scale_up")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "/scale_down":
            if rollout_service is None:
                return "Rollout service unavailable."
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/scale_down")
            rollout_service.scale_down(changed_by="telegram", reason="telegram_scale_down")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "CONFIRM_SCALE_DOWN":
            if rollout_service is None:
                return "Rollout service unavailable."
            rollout_service.scale_down(changed_by="telegram", reason="telegram_scale_down")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "/rollback_live":
            if rollout_service is None:
                return "Rollout service unavailable."
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/rollback_live")
            rollout_service.rollback_live(changed_by="telegram", reason="telegram_manual_rollback")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command == "CONFIRM_ROLLBACK_LIVE":
            if rollout_service is None:
                return "Rollout service unavailable."
            rollout_service.rollback_live(changed_by="telegram", reason="telegram_manual_rollback")
            payload = rollout_service.get_capital_status()
            payload["live_effectively_allowed"] = (
                payload.get("current_phase") != "disabled"
                and not payload.get("rollback_active", False)
                and live_controller is not None
                and live_controller._is_armed()
            )
            return format_rollout_status_message(payload)
        if command.startswith("/clear_lock "):
            if live_controller is None:
                return "Live controller unavailable."
            lock_id = command.split(maxsplit=1)[1].strip()
            if runtime_settings.telegram_confirm_dangerous_actions:
                return build_confirmation_prompt("/clear_lock", lock_id)
            return format_live_status_message(await live_controller.clear_lock(lock_id))
        if command.startswith("CONFIRM_CLEAR_LOCK "):
            if live_controller is None:
                return "Live controller unavailable."
            lock_id = command.split(maxsplit=1)[1].strip()
            return format_live_status_message(await live_controller.clear_lock(lock_id))
        if command == "/start_shadow":
            if shadow_service is None:
                return "Shadow service unavailable."
            status = await shadow_service.start_shadow()
            return f"Shadow mode running={status['running']}"
        if command == "/stop_shadow":
            if shadow_service is None:
                return "Shadow service unavailable."
            status = await shadow_service.stop_shadow()
            return f"Shadow mode running={status['running']}"
        if command.startswith("/approve "):
            ref = command.split(maxsplit=1)[1].strip()
            approval = await _resolve_approval_ref(execution_service, ref)
            if approval is None:
                return "Approval not found."
            approved = await execution_service.approve_and_execute(approval.approval_id)
            return format_approval_message(approved)
        if command.startswith("/reject "):
            ref = command.split(maxsplit=1)[1].strip()
            approval = await _resolve_approval_ref(execution_service, ref)
            if approval is None:
                return "Approval not found."
            rejected = await execution_service.reject(approval.approval_id, reason="telegram_reject")
            return format_approval_message(rejected)
        return "Unsupported command."


async def _resolve_approval_ref(execution_service: Any, ref: str) -> Approval | None:
    approvals = await execution_service.list_approvals()
    for approval in approvals:
        if approval.approval_id == ref or approval.trade_id == ref:
            return approval
    return None
