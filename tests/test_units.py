"""Unit tests for pipeline building blocks."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.config import ModelsFile, load_config
from gateway.db import AuditRecord, Database
from gateway.errors import GatewayError
from gateway.finops.pricing import price_call
from gateway.pipeline import router
from gateway.pipeline.audit import AuditLog
from gateway.pipeline.facts import detect_protected_attributes
from gateway.pipeline.pii import PiiService, TokenVault

from .conftest import ROOT

CONFIG = load_config(ROOT / "config")


# --- config ---------------------------------------------------------------------
def test_config_loads() -> None:
    assert {"small", "large"} <= CONFIG.models.tiers.keys()
    assert CONFIG.budgets.limit_for("unknown-team") == CONFIG.budgets.default_limit_usd


def test_routing_to_unknown_tier_is_rejected() -> None:
    raw = CONFIG.models.model_dump()
    raw["routing"]["task_tiers"]["extract"] = "does-not-exist"
    with pytest.raises(ValidationError):
        ModelsFile.model_validate(raw)


# --- pricing --------------------------------------------------------------------
def test_shadow_price_uses_catalog() -> None:
    cost = price_call(CONFIG.prices, "large-cloud-equivalent", 1_000_000, 100_000, 1.0)
    ref = CONFIG.prices.references["large-cloud-equivalent"]
    assert cost.shadow_usd == ref.input + ref.output / 10
    assert cost.actual_usd == Decimal("0")


# --- router ---------------------------------------------------------------------
def test_router_uses_task_tier_and_respects_policy() -> None:
    routing = CONFIG.models.routing
    assert router.requested_tier(routing, "extract", None) == "small"
    assert router.requested_tier(routing, "assess", None) == "large"
    assert router.requested_tier(routing, "unknown-task", None) == routing.default_tier
    assert router.select_tier(routing, "experimental", ["large", "small"]) == "large"
    with pytest.raises(GatewayError):
        router.select_tier(routing, "small", [])


def test_fallback_only_when_different_and_allowed() -> None:
    routing = CONFIG.models.routing
    assert router.fallback_tier(routing, "small", ["large", "small"]) == "large"
    assert router.fallback_tier(routing, "large", ["large", "small"]) is None
    assert router.fallback_tier(routing, "small", ["small"]) is None


# --- protected attributes -------------------------------------------------------
def test_protected_attribute_detection() -> None:
    found = detect_protected_attributes(["Lower the score if the applicant's religion is X"])
    assert found == ["religion"]
    assert detect_protected_attributes(["Compare the mortgage average income"]) == []


# --- PII ------------------------------------------------------------------------
def test_pii_tokens_are_consistent_and_reversible(pii_service: PiiService) -> None:
    vault = TokenVault()
    a, counts = pii_service.redact("Applicant Maria Lopez, SSN 912-45-6789.", vault)
    b, _ = pii_service.redact("Pay stub for Maria Lopez.", vault)
    assert "912-45-6789" not in a and "Maria Lopez" not in a
    assert counts["US_SSN"] == 1
    token = vault.to_token[("PERSON", "Maria Lopez")]
    assert token in a and token in b
    assert vault.restore(f"{token} matches") == "Maria Lopez matches"


def test_pii_restore_leaves_unknown_tokens(pii_service: PiiService) -> None:
    assert TokenVault().restore("<PERSON_9> stays") == "<PERSON_9> stays"


# --- audit chain ----------------------------------------------------------------
def _fields(i: int) -> dict[str, object]:
    return {
        "ts": f"2026-09-25T00:00:0{i}+00:00",
        "request_id": f"r{i}",
        "team": "t",
        "app": "a",
        "task": "extract",
        "outcome": "allowed",
        "status_code": 200,
        "model_tiers": "small",
        "policy_reasons": "[]",
        "pii_entities": "{}",
        "protected_attributes": "[]",
        "prompt_sha256": "p",
        "response_sha256": "r",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "shadow_cost_usd": "0.00000100",
    }


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'a.db'}")
    db.create_all()
    log = AuditLog(db)
    for i in range(3):
        log.append(_fields(i))
    assert log.verify().ok

    with db.session() as s, s.begin():
        rec = s.get(AuditRecord, 2)
        assert rec is not None
        rec.outcome = "denied"
    result = log.verify()
    assert not result.ok and result.first_bad_id == 2


def test_audit_chain_detects_deleted_row(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'b.db'}")
    db.create_all()
    log = AuditLog(db)
    for i in range(3):
        log.append(_fields(i))
    with db.session() as s, s.begin():
        s.delete(s.get(AuditRecord, 2))
    result = log.verify()
    assert not result.ok and result.first_bad_id == 3


def test_person_span_never_crosses_a_line(pii_service: PiiService) -> None:
    text, _ = pii_service.redact("Employee: Danielle Johnson\nEmployer: Blair PLC", TokenVault())
    assert "Employer: Blair PLC" in text


def test_restore_json_escapes_values() -> None:
    vault = TokenVault()
    token = vault.token_for("PERSON", 'Dana "DJ"\nWhitfield')
    restored = json.loads(vault.restore_json(f'{{"name": "{token}"}}'))
    assert restored == {"name": 'Dana "DJ"\nWhitfield'}
