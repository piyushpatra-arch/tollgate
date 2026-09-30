"""Prometheus metrics. Counters reset on restart; the Postgres ledger is the system of record."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "tollgate_requests_total",
    "Gateway requests by outcome",
    ["team", "app", "task", "outcome"],
)
MODEL_CALLS = Counter(
    "tollgate_model_calls_total",
    "Model calls by tier (fallbacks count as separate calls)",
    ["team", "app", "model_tier", "fallback"],
)
SHADOW_COST = Counter(
    "tollgate_shadow_cost_usd_total", "Shadow cost in USD", ["team", "app", "model_tier"]
)
TOKENS = Counter("tollgate_tokens_total", "Tokens", ["team", "model_tier", "direction"])
POLICY_DENIALS = Counter("tollgate_policy_denials_total", "Policy denials", ["app", "policy_id"])
PII_ENTITIES = Counter("tollgate_pii_entities_redacted_total", "PII entities redacted", ["entity"])
LATENCY = Histogram(
    "tollgate_model_latency_seconds",
    "Model call latency",
    ["model_tier"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128),
)
