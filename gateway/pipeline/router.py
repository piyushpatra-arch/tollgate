"""Stage 5: choose a model tier. Rule-based in v1 (ADR-0002); policy constrains the choice."""

from __future__ import annotations

from gateway.config import RoutingConfig
from gateway.errors import GatewayError


def requested_tier(routing: RoutingConfig, task: str, override: str | None) -> str:
    """The tier the caller asked for (override) or the task's default tier."""
    if override:
        return override
    return routing.task_tiers.get(task, routing.default_tier)


def select_tier(routing: RoutingConfig, wanted: str, allowed: list[str]) -> str:
    if wanted in allowed:
        return wanted
    for tier in routing.preference:
        if tier in allowed:
            return tier
    raise GatewayError(403, "no_approved_model", "no model tier is approved for this app")


def fallback_tier(routing: RoutingConfig, current: str, allowed: list[str]) -> str | None:
    fb = routing.fallback_tier
    return fb if fb != current and fb in allowed else None
