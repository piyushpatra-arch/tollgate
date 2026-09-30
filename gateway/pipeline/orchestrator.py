"""The request pipeline. Stage order is an architectural decision — see CLAUDE.md and
docs/architecture.md before changing it.

  1 identify -> 2 budget -> 3 gather facts + policy -> 4 redact -> 5 route -> 6 call model
  -> 7 output checks (+ fallback) -> 8 restore -> 9 ledger + audit (always, in `finally`)
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import jsonschema

from gateway.config import AppConfig, GatewayConfig
from gateway.db import LedgerEntry
from gateway.errors import GatewayError
from gateway.finops.ledger import Ledger
from gateway.finops.pricing import price_call
from gateway.metrics import (
    LATENCY,
    MODEL_CALLS,
    PII_ENTITIES,
    POLICY_DENIALS,
    REQUESTS,
    SHADOW_COST,
    TOKENS,
)
from gateway.pipeline import router
from gateway.pipeline.audit import AuditLog, canonical_json, sha256
from gateway.pipeline.budget import BudgetGuard
from gateway.pipeline.facts import detect_protected_attributes
from gateway.pipeline.identity import IdentityResolver
from gateway.pipeline.pii import PLACEHOLDER_NOTICE, RESTRICTED_ENTITIES, PiiService, TokenVault
from gateway.pipeline.policy import PolicyEngine, PolicyReason
from gateway.providers.base import ModelProvider, ModelRequest, ModelResponse, ProviderError

FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


@dataclass
class GatewayRequest:
    messages: list[dict[str, str]]
    api_key: str | None
    task: str = "general"
    tier_override: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None


@dataclass
class GatewayResult:
    request_id: str
    content: str
    model: str
    model_tiers: list[str]
    prompt_tokens: int
    completion_tokens: int
    shadow_cost_usd: Decimal
    budget_state: str
    pii_redacted: dict[str, int]
    finish_reason: str = "stop"


@dataclass
class _Trace:
    """Everything the audit record needs, filled in as the pipeline progresses."""

    request_id: str
    task: str
    team: str = "unknown"
    app: str = "unknown"
    outcome: str = "error"
    status_code: int = 500
    tiers: list[str] = field(default_factory=list)
    reasons: list[PolicyReason] = field(default_factory=list)
    pii_in: Counter[str] = field(default_factory=Counter)
    pii_out_new: Counter[str] = field(default_factory=Counter)
    protected: list[str] = field(default_factory=list)
    prompt_hash: str = ""
    response_hash: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    shadow_cost: Decimal = Decimal("0")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_expectation(response_format: dict[str, Any] | None) -> tuple[bool, dict[str, Any] | None]:
    if not response_format:
        return False, None
    kind = response_format.get("type")
    if kind == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
        return True, schema if isinstance(schema, dict) else None
    return kind == "json_object", None


def _clean_json(content: str, schema: dict[str, Any] | None) -> str | None:
    """Return the JSON text if valid (stripping markdown fences), else None."""
    match = FENCE_RE.match(content)
    text = match.group(1) if match else content.strip()
    try:
        parsed = json.loads(text)
        if schema is not None:
            jsonschema.validate(parsed, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError):
        return None
    return text


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        provider: ModelProvider,
        policy: PolicyEngine,
        pii: PiiService,
        ledger: Ledger,
        audit: AuditLog,
    ) -> None:
        self.config = config
        self._provider = provider
        self._policy = policy
        self._pii = pii
        self._ledger = ledger
        self._audit = audit
        self._identity = IdentityResolver(config.apps)
        self.budgets = BudgetGuard(config.budgets, ledger)

    # ------------------------------------------------------------------ public
    def handle(self, req: GatewayRequest) -> GatewayResult:
        trace = _Trace(request_id=f"tg-{uuid.uuid4().hex[:20]}", task=req.task)
        trace.prompt_hash = sha256(canonical_json(req.messages))
        try:
            result = self._run(req, trace)
            trace.outcome, trace.status_code = "allowed", 200
            return result
        except GatewayError as exc:
            trace.outcome, trace.status_code = exc.code, exc.status_code
            raise
        finally:
            self._record_audit(trace)
            REQUESTS.labels(trace.team, trace.app, trace.task, trace.outcome).inc()

    # ---------------------------------------------------------------- pipeline
    def _run(self, req: GatewayRequest, trace: _Trace) -> GatewayResult:
        # 1. identity
        app = self._identity.resolve(req.api_key)
        trace.team, trace.app = app.team, app.name

        # 2. budget (before any tokens are spent)
        budget = self.budgets.check(app.team)

        # 3. facts + policy
        vault = TokenVault()
        redacted_messages: list[dict[str, str]] = []
        for msg in req.messages:
            text, counts = self._pii.redact(msg["content"], vault)
            trace.pii_in.update(counts)
            redacted_messages.append({"role": msg["role"], "content": text})
        trace.protected = detect_protected_attributes([m["content"] for m in req.messages])

        wanted = router.requested_tier(self.config.models.routing, req.task, req.tier_override)
        if req.tier_override and req.tier_override not in self.config.models.tiers:
            raise GatewayError(400, "unknown_tier", f"unknown tier '{req.tier_override}'")
        decision = self._policy.evaluate(self._policy_input(app, req, wanted, trace))
        trace.reasons = decision.reasons
        if not decision.allow:
            for reason in decision.reasons:
                POLICY_DENIALS.labels(app.name, reason.id).inc()
            detail = "; ".join(f"[{r.id}] {r.message}" for r in decision.reasons)
            raise GatewayError(403, "policy_denied", detail or "denied by policy")

        # 4. redaction takes effect: only redacted text leaves the gateway
        if vault.to_value:
            redacted_messages.insert(0, {"role": "system", "content": PLACEHOLDER_NOTICE})
            for entity, n in trace.pii_in.items():
                PII_ENTITIES.labels(entity).inc(n)

        # 5. route
        tier = router.select_tier(self.config.models.routing, wanted, decision.allowed_tiers)

        # 6–7. call model, validate, fall back once if JSON is invalid
        expects_json, schema = _json_expectation(req.response_format)
        resp = self._call(app, req, tier, redacted_messages, expects_json, trace, fallback=False)
        content = resp.content
        if expects_json:
            cleaned = _clean_json(resp.content, schema)
            fb = router.fallback_tier(self.config.models.routing, tier, decision.allowed_tiers)
            if cleaned is None and fb:
                tier = fb
                resp = self._call(app, req, tier, redacted_messages, True, trace, fallback=True)
                cleaned = _clean_json(resp.content, schema)
            if cleaned is None:
                raise GatewayError(502, "invalid_model_output", "model did not return valid JSON")
            content = cleaned

        # output scan: PII the model produced that did not come from the (redacted) input
        for span in self._pii.detect(content):
            trace.pii_out_new[span.entity] += 1

        # 8. restore placeholders for the caller
        restored = vault.restore_json(content) if expects_json else vault.restore(content)
        trace.response_hash = sha256(restored)

        return GatewayResult(
            request_id=trace.request_id,
            content=restored,
            model=self.config.models.tiers[tier].litellm_model,
            model_tiers=list(trace.tiers),
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            shadow_cost_usd=trace.shadow_cost,
            budget_state=budget.state,
            pii_redacted=dict(trace.pii_in),
            finish_reason=resp.finish_reason,
        )

    # ----------------------------------------------------------------- helpers
    def _policy_input(
        self, app: AppConfig, req: GatewayRequest, wanted: str, trace: _Trace
    ) -> dict[str, Any]:
        return {
            "app": {
                "name": app.name,
                "team": app.team,
                "risk_tier": app.risk_tier,
                "restricted_data_approved": app.restricted_data_approved,
            },
            "request": {
                "task": req.task,
                "requested_tier": wanted,
                "tier_override": req.tier_override is not None,
            },
            "facts": {
                "pii_entities": sorted(trace.pii_in),
                "restricted_pii": sorted(set(trace.pii_in) & RESTRICTED_ENTITIES),
                "protected_attributes": trace.protected,
            },
        }

    def _call(
        self,
        app: AppConfig,
        req: GatewayRequest,
        tier: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        trace: _Trace,
        *,
        fallback: bool,
    ) -> ModelResponse:
        tier_cfg = self.config.models.tiers[tier]
        started = time.perf_counter()
        try:
            resp = self._provider.complete(
                ModelRequest(
                    model=tier_cfg.litellm_model,
                    messages=messages,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    json_mode=json_mode,
                )
            )
        except ProviderError as exc:
            trace.tiers.append(tier)
            raise GatewayError(502, "model_unavailable", f"model call failed: {exc}") from exc
        latency = time.perf_counter() - started

        cost = price_call(
            self.config.prices,
            tier_cfg.shadow_reference,
            resp.prompt_tokens,
            resp.completion_tokens,
            latency,
            actual_usd=Decimal(str(resp.actual_cost_usd)),
        )
        self._ledger.record(
            LedgerEntry(
                ts=_now_iso(),
                request_id=trace.request_id,
                team=app.team,
                app=app.name,
                task=req.task,
                model_tier=tier,
                model=tier_cfg.litellm_model,
                shadow_reference=cost.shadow_reference,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                actual_cost_usd=cost.actual_usd,
                shadow_cost_usd=cost.shadow_usd,
                latency_ms=int(latency * 1000),
                is_fallback=fallback,
            )
        )
        trace.tiers.append(tier)
        trace.prompt_tokens += resp.prompt_tokens
        trace.completion_tokens += resp.completion_tokens
        trace.shadow_cost += cost.shadow_usd + cost.actual_usd

        MODEL_CALLS.labels(app.team, app.name, tier, str(fallback).lower()).inc()
        SHADOW_COST.labels(app.team, app.name, tier).inc(float(cost.shadow_usd))
        TOKENS.labels(app.team, tier, "input").inc(resp.prompt_tokens)
        TOKENS.labels(app.team, tier, "output").inc(resp.completion_tokens)
        LATENCY.labels(tier).observe(latency)
        return resp

    def _record_audit(self, trace: _Trace) -> None:
        self._audit.append(
            {
                "ts": _now_iso(),
                "request_id": trace.request_id,
                "team": trace.team,
                "app": trace.app,
                "task": trace.task,
                "outcome": trace.outcome,
                "status_code": trace.status_code,
                "model_tiers": ">".join(trace.tiers),
                "policy_reasons": canonical_json([r.model_dump() for r in trace.reasons]),
                "pii_entities": canonical_json(
                    {"input": dict(trace.pii_in), "output_new": dict(trace.pii_out_new)}
                ),
                "protected_attributes": canonical_json(trace.protected),
                "prompt_sha256": trace.prompt_hash,
                "response_sha256": trace.response_hash,
                "prompt_tokens": trace.prompt_tokens,
                "completion_tokens": trace.completion_tokens,
                "shadow_cost_usd": f"{trace.shadow_cost:.8f}",
            }
        )
