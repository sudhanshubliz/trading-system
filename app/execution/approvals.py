from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from app.execution.types import Approval
from app.risk.types import RiskAssessment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalStore:
    def __init__(self, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.time_provider = time_provider or utc_now
        self._approvals_by_id: dict[str, Approval] = {}
        self._approval_ids_by_assessment_id: dict[str, str] = {}

    def create_from_assessment(self, assessment: RiskAssessment) -> Approval:
        existing_id = self._approval_ids_by_assessment_id.get(assessment.assessment_id)
        if existing_id is not None:
            return replace(self._approvals_by_id[existing_id])

        if assessment.final_decision != "approved_for_review":
            raise ValueError("assessment_not_approved_for_review")

        approval_id = self._build_approval_id(assessment.assessment_id)
        approval = Approval(
            approval_id=approval_id,
            assessment_id=assessment.assessment_id,
            signal_id=assessment.signal_id,
            symbol=assessment.symbol,
            side=assessment.side,
            strategy_name=assessment.strategy_name,
            status="pending",
            created_at=self.time_provider(),
        )
        self._approvals_by_id[approval_id] = approval
        self._approval_ids_by_assessment_id[assessment.assessment_id] = approval_id
        return replace(approval)

    def approve(self, approval_id: str) -> Approval:
        approval = self._require(approval_id)
        if approval.status == "rejected":
            raise ValueError("approval_rejected")
        if approval.status == "executed":
            return replace(approval)
        if approval.status != "pending":
            raise ValueError("approval_not_pending")
        approval.status = "approved"
        approval.approved_at = self.time_provider()
        return replace(approval)

    def reject(self, approval_id: str, reason: str | None = None) -> Approval:
        approval = self._require(approval_id)
        if approval.status == "executed":
            raise ValueError("approval_already_executed")
        approval.status = "rejected"
        approval.rejected_at = approval.rejected_at or self.time_provider()
        approval.rejection_reason = reason
        return replace(approval)

    def mark_executed(self, approval_id: str, *, trade_id: str, position_id: str) -> Approval:
        approval = self._require(approval_id)
        if approval.status == "rejected":
            raise ValueError("approval_rejected")
        if approval.status == "executed":
            return replace(approval)
        if approval.status != "approved":
            raise ValueError("approval_not_approved")
        approval.status = "executed"
        approval.executed_at = self.time_provider()
        approval.trade_id = trade_id
        approval.position_id = position_id
        return replace(approval)

    def list_all(self) -> list[Approval]:
        approvals = list(self._approvals_by_id.values())
        approvals.sort(key=lambda item: item.created_at, reverse=True)
        return [replace(approval) for approval in approvals]

    def list_pending(self) -> list[Approval]:
        return [approval for approval in self.list_all() if approval.status == "pending"]

    def get(self, approval_id: str) -> Approval | None:
        approval = self._approvals_by_id.get(approval_id)
        return replace(approval) if approval is not None else None

    def remove(self, approval_id: str) -> None:
        approval = self._approvals_by_id.pop(approval_id, None)
        if approval is not None:
            self._approval_ids_by_assessment_id.pop(approval.assessment_id, None)

    def load_approval(self, approval: Approval) -> Approval:
        self._approvals_by_id[approval.approval_id] = replace(approval)
        self._approval_ids_by_assessment_id[approval.assessment_id] = approval.approval_id
        return replace(approval)

    def _require(self, approval_id: str) -> Approval:
        approval = self._approvals_by_id.get(approval_id)
        if approval is None:
            raise KeyError("approval_not_found")
        return approval

    def _build_approval_id(self, assessment_id: str) -> str:
        digest = hashlib.sha1(assessment_id.encode("utf-8")).hexdigest()
        return f"apr_{digest[:12]}"
