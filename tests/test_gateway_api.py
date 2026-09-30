"""HTTP-level tests of the full pipeline with a scripted model and a static policy."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from gateway.db import AuditRecord, LedgerEntry
from gateway.pipeline.policy import PolicyDecision, PolicyReason

from .conftest import KYC_KEY, SANDBOX_KEY, FakeProvider, StaticPolicy, chat

SMALL = "ollama_chat/llama3.2:3b"
LARGE = "ollama_chat/llama3.1:8b"


def _audit(client: TestClient) -> list[AuditRecord]:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.session() as s:
        return list(s.execute(select(AuditRecord).order_by(AuditRecord.id)).scalars())


def _ledger(client: TestClient) -> list[LedgerEntry]:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.session() as s:
        return list(s.execute(select(LedgerEntry).order_by(LedgerEntry.id)).scalars())


def test_happy_path_routes_costs_and_audits(client: TestClient, provider: FakeProvider) -> None:
    provider.default_reply = "Looks consistent."
    resp = chat(client, "Summarize this pay stub.", task="extract")
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "Looks consistent."
    assert body["model"] == SMALL
    assert resp.headers["X-Tollgate-Model-Tier"] == "small"
    # 1000 in * $1/M + 200 out * $5/M = $0.002
    assert resp.headers["X-Tollgate-Shadow-Cost-USD"] == "0.00200000"
    assert [a.outcome for a in _audit(client)] == ["allowed"]
    assert len(_ledger(client)) == 1


def test_assess_task_routes_to_large(client: TestClient, provider: FakeProvider) -> None:
    resp = chat(client, "Assess the risk.", task="assess")
    assert resp.status_code == 200
    assert provider.calls[-1].model == LARGE


def test_pii_never_reaches_model_but_is_restored(
    client: TestClient, provider: FakeProvider
) -> None:
    # the model refers to the placeholder it was given; the caller gets the real value back
    provider.default_reply = "<US_SSN_1> checked"
    resp = chat(client, "Name: Maria Lopez. SSN 912-45-6789.")
    sent = provider.calls[-1].messages
    assert all("912-45-6789" not in m["content"] for m in sent)
    assert all("Maria Lopez" not in m["content"] for m in sent)
    assert sent[0]["role"] == "system"  # placeholder notice added
    assert resp.json()["choices"][0]["message"]["content"] == "912-45-6789 checked"
    assert resp.json()["tollgate"]["pii_redacted"]["US_SSN"] == 1


def test_unknown_key_is_rejected_and_audited(client: TestClient) -> None:
    resp = chat(client, "hi", key="nope")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"
    assert _audit(client)[-1].outcome == "unauthenticated"


def test_policy_denial_is_403_audited_and_model_not_called(
    client: TestClient, policy: StaticPolicy, provider: FakeProvider
) -> None:
    policy.decision = PolicyDecision(
        allow=False,
        reasons=[PolicyReason(id="protected_attribute_in_credit_task", message="no")],
        allowed_tiers=["large", "small"],
    )
    resp = chat(client, "Consider the applicant's religion.", task="assess")
    assert resp.status_code == 403
    assert "protected_attribute_in_credit_task" in resp.json()["error"]["message"]
    assert provider.calls == []
    record = _audit(client)[-1]
    assert record.outcome == "policy_denied"
    assert "protected_attribute_in_credit_task" in record.policy_reasons
    assert policy.inputs[-1]["facts"]["protected_attributes"] == ["religion"]


def test_policy_input_flags_restricted_pii(client: TestClient, policy: StaticPolicy) -> None:
    chat(client, "SSN 912-45-6789")
    assert policy.inputs[-1]["facts"]["restricted_pii"] == ["US_SSN"]


def test_invalid_json_falls_back_to_large_and_both_calls_are_costed(
    client: TestClient, provider: FakeProvider
) -> None:
    provider.replies[SMALL] = ["not json at all"]
    provider.replies[LARGE] = ['```json\n{"income": 5000}\n```']
    resp = chat(client, "Extract income as JSON.", json_mode=True)
    assert resp.status_code == 200
    assert json.loads(resp.json()["choices"][0]["message"]["content"]) == {"income": 5000}
    assert resp.headers["X-Tollgate-Model-Tier"] == "small>large"
    rows = _ledger(client)
    assert [(r.model_tier, r.is_fallback) for r in rows] == [("small", False), ("large", True)]


def test_invalid_json_after_fallback_is_502(client: TestClient, provider: FakeProvider) -> None:
    provider.default_reply = "still not json"
    resp = chat(client, "Extract as JSON.", json_mode=True)
    assert resp.status_code == 502
    assert _audit(client)[-1].model_tiers == "small>large"


def test_hard_budget_limit_returns_429(client: TestClient) -> None:
    # data-science budget is $0.01; each fake call costs $0.002 (small tier)
    statuses = [chat(client, "hello", key=SANDBOX_KEY).status_code for _ in range(7)]
    assert statuses[:5] == [200] * 5
    assert statuses[5:] == [429, 429]
    assert _audit(client)[-1].outcome == "over_budget"


def test_opa_down_fails_closed(make_app: Callable[..., FastAPI], provider: FakeProvider) -> None:
    with TestClient(make_app(None)) as c:  # real OpaPolicyEngine -> nothing listening
        resp = chat(c, "hello")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "policy_unavailable"
    assert provider.calls == []


def test_streaming_and_unknown_tier_rejected(client: TestClient) -> None:
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        headers={"X-Tollgate-Key": KYC_KEY},
    )
    assert resp.status_code == 400
    assert chat(client, "x", tier="gpt-9000").status_code == 400


def test_audit_chain_verifies_after_mixed_traffic(client: TestClient) -> None:
    chat(client, "a")
    chat(client, "b", key="bad")
    chat(client, "c", key=SANDBOX_KEY)
    from gateway.pipeline.audit import AuditLog

    assert AuditLog(client.app.state.db).verify().ok  # type: ignore[attr-defined]


def test_budgets_and_metrics_endpoints(client: TestClient) -> None:
    chat(client, "a")
    budgets = client.get("/v1/budgets").json()
    assert budgets["teams"]["lending-ops"]["spent_usd"] == "0.002000"
    metrics = client.get("/metrics").text
    assert "tollgate_shadow_cost_usd_total" in metrics
