"""Persistence: cost ledger and hash-chained audit log.

v1 creates tables on startup (create_all). Schema migrations (Alembic) are on the roadmap.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class LedgerEntry(Base):
    """One row per model call (a fallback produces two rows for one request)."""

    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(32), index=True)  # ISO-8601 UTC
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    team: Mapped[str] = mapped_column(String(64), index=True)
    app: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(String(32))
    model_tier: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    shadow_reference: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    actual_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    shadow_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    latency_ms: Mapped[int] = mapped_column(Integer)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditRecord(Base):
    """Append-only, hash-chained. Values are stored as strings so the hash is reproducible."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(32), index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    team: Mapped[str] = mapped_column(String(64))
    app: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int] = mapped_column(Integer)
    model_tiers: Mapped[str] = mapped_column(String(128))  # e.g. "small>large" on fallback
    policy_reasons: Mapped[str] = mapped_column(Text)  # canonical JSON
    pii_entities: Mapped[str] = mapped_column(Text)  # canonical JSON counts, no values
    protected_attributes: Mapped[str] = mapped_column(Text)  # canonical JSON
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    response_sha256: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    shadow_cost_usd: Mapped[str] = mapped_column(String(24))
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
