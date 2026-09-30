"""Stage 9: tamper-evident audit log (ADR-0006).

Each record stores the hash of the previous record, so editing or deleting any row breaks
the chain from that point on. `verify()` walks the chain and reports the first break.

v1 serializes appends with an in-process lock, which is correct for a single gateway
instance. Multi-instance deployments need a database-level lock (roadmap).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from gateway.db import AuditRecord, Database

GENESIS = "0" * 64
HASHED_FIELDS = (
    "ts",
    "request_id",
    "team",
    "app",
    "task",
    "outcome",
    "status_code",
    "model_tiers",
    "policy_reasons",
    "pii_entities",
    "protected_attributes",
    "prompt_sha256",
    "response_sha256",
    "prompt_tokens",
    "completion_tokens",
    "shadow_cost_usd",
    "prev_hash",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_hash(fields: dict[str, Any]) -> str:
    return sha256(canonical_json({k: fields[k] for k in HASHED_FIELDS}))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records_checked: int
    first_bad_id: int | None = None
    reason: str = ""


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()

    def append(self, fields: dict[str, Any]) -> str:
        """Append a record. `fields` must contain every HASHED_FIELDS key except prev_hash."""
        with self._lock, self._db.session() as s, s.begin():
            last = s.execute(
                select(AuditRecord.record_hash).order_by(AuditRecord.id.desc()).limit(1)
            ).scalar_one_or_none()
            full = {**fields, "prev_hash": last or GENESIS}
            digest = record_hash(full)
            s.add(AuditRecord(**full, record_hash=digest))
            return digest

    def verify(self) -> VerifyResult:
        expected_prev = GENESIS
        count = 0
        with self._db.session() as s:
            for rec in s.execute(select(AuditRecord).order_by(AuditRecord.id)).scalars():
                count += 1
                fields = {k: getattr(rec, k) for k in HASHED_FIELDS}
                if rec.prev_hash != expected_prev:
                    return VerifyResult(False, count, rec.id, "prev_hash does not match chain")
                if record_hash(fields) != rec.record_hash:
                    return VerifyResult(False, count, rec.id, "record contents were modified")
                expected_prev = rec.record_hash
        return VerifyResult(True, count)
