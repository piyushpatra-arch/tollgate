"""Cost ledger writes and spend queries — the FinOps system of record."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from gateway.db import Database, LedgerEntry


def month_start_iso(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


class Ledger:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, entry: LedgerEntry) -> None:
        with self._db.session() as s, s.begin():
            s.add(entry)

    def team_spend_since(self, team: str, since_iso: str) -> Decimal:
        stmt = select(
            func.coalesce(func.sum(LedgerEntry.actual_cost_usd + LedgerEntry.shadow_cost_usd), 0)
        ).where(LedgerEntry.team == team, LedgerEntry.ts >= since_iso)
        with self._db.session() as s:
            value = s.execute(stmt).scalar_one()
        return Decimal(str(value))

    def spend_by_team_since(self, since_iso: str) -> dict[str, Decimal]:
        stmt = (
            select(
                LedgerEntry.team,
                func.sum(LedgerEntry.actual_cost_usd + LedgerEntry.shadow_cost_usd),
            )
            .where(LedgerEntry.ts >= since_iso)
            .group_by(LedgerEntry.team)
        )
        with self._db.session() as s:
            rows = s.execute(stmt).all()
        return {team: Decimal(str(total)) for team, total in rows}
