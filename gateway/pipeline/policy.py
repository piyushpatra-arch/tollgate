"""Stage 3: ask OPA for a decision. Policies live in policies/*.rego, not here (ADR-0004)."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from gateway.errors import GatewayError


class PolicyReason(BaseModel):
    id: str
    message: str


class PolicyDecision(BaseModel):
    allow: bool
    reasons: list[PolicyReason] = Field(default_factory=list)
    allowed_tiers: list[str] = Field(default_factory=list)


class PolicyEngine(Protocol):
    def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision: ...


class OpaPolicyEngine:
    """Queries data.tollgate.decision on an OPA server. Fails closed."""

    def __init__(self, base_url: str, timeout_s: float = 2.0) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/data/tollgate/decision"
        self._client = httpx.Client(timeout=timeout_s)

    def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision:
        try:
            resp = self._client.post(self._url, json={"input": policy_input})
            resp.raise_for_status()
            result = resp.json().get("result")
            if result is None:
                raise ValueError("policy returned no result (is the bundle loaded?)")
            return PolicyDecision.model_validate(result)
        except Exception as exc:
            raise GatewayError(
                503, "policy_unavailable", "policy engine unavailable; request denied (fail closed)"
            ) from exc
