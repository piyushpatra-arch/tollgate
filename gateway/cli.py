"""Operator CLI.

python -m gateway.cli verify-audit   # walk the hash chain
python -m gateway.cli spend          # month-to-date spend by team
"""

from __future__ import annotations

import argparse
import sys

from gateway.config import load_config
from gateway.db import Database
from gateway.finops.ledger import Ledger, month_start_iso
from gateway.pipeline.audit import AuditLog
from gateway.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tollgate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify-audit", help="verify the audit hash chain")
    sub.add_parser("spend", help="month-to-date spend by team vs budget")
    args = parser.parse_args(argv)

    settings = Settings()
    db = Database(settings.database_url)
    db.create_all()

    if args.cmd == "verify-audit":
        result = AuditLog(db).verify()
        if result.ok:
            print(f"OK: audit chain intact ({result.records_checked} records)")
            return 0
        print(f"FAIL: record id={result.first_bad_id}: {result.reason}")
        return 1

    budgets = load_config(settings.config_dir).budgets
    spend = Ledger(db).spend_by_team_since(month_start_iso())
    print(f"{'team':<20}{'spent (USD)':>14}{'limit (USD)':>14}")
    for team in sorted(set(spend) | set(budgets.teams)):
        print(f"{team:<20}{spend.get(team, 0):>14.6f}{budgets.limit_for(team):>14.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
