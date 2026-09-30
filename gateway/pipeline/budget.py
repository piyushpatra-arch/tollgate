"""Stage 2: enforce team budgets before any tokens are spent."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from gateway.config import BudgetsFile
from gateway.errors import GatewayError
from gateway.finops.ledger import Ledger, month_start_iso

BudgetState = Literal["ok", "soft_limit"]


@dataclass(frozen=True)
class BudgetStatus:
    team: str
    spent_usd: Decimal
    limit_usd: Decimal
    state: BudgetState


class BudgetGuard:
    def __init__(self, budgets: BudgetsFile, ledger: Ledger) -> None:
        self._budgets = budgets
        self._ledger = ledger

    def status(self, team: str) -> tuple[Decimal, Decimal]:
        try:
            spent = self._ledger.team_spend_since(team, month_start_iso())
        except Exception as exc:  # fail closed: no ledger, no spend
            raise GatewayError(503, "budget_unavailable", "budget store unavailable") from exc
        return spent, self._budgets.limit_for(team)

    def check(self, team: str) -> BudgetStatus:
        spent, limit = self.status(team)
        if spent >= limit:
            raise GatewayError(
                429,
                "over_budget",
                f"team '{team}' has used ${spent:.4f} of its ${limit:.2f} monthly budget",
            )
        soft = limit * Decimal(self._budgets.soft_limit_pct) / Decimal(100)
        state: BudgetState = "soft_limit" if spent >= soft else "ok"
        return BudgetStatus(team=team, spent_usd=spent, limit_usd=limit, state=state)
