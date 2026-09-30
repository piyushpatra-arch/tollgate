"""Typed loaders for the YAML files in config/. Prices and limits live in config, never in code."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

RiskTier = Literal["low", "medium", "high"]


class AppConfig(BaseModel):
    name: str
    team: str
    risk_tier: RiskTier
    restricted_data_approved: bool = False
    api_key: str


class AppsFile(BaseModel):
    apps: list[AppConfig]


class TeamBudget(BaseModel):
    limit_usd: Decimal


class BudgetsFile(BaseModel):
    period: Literal["monthly"] = "monthly"
    soft_limit_pct: int = Field(80, ge=1, le=100)
    default_limit_usd: Decimal
    teams: dict[str, TeamBudget] = {}

    def limit_for(self, team: str) -> Decimal:
        budget = self.teams.get(team)
        return budget.limit_usd if budget else self.default_limit_usd


class TierConfig(BaseModel):
    litellm_model: str
    shadow_reference: str


class RoutingConfig(BaseModel):
    task_tiers: dict[str, str]
    default_tier: str
    fallback_tier: str
    preference: list[str]


class ModelsFile(BaseModel):
    tiers: dict[str, TierConfig]
    routing: RoutingConfig

    @model_validator(mode="after")
    def _tiers_exist(self) -> ModelsFile:
        referenced = {
            *self.routing.task_tiers.values(),
            self.routing.default_tier,
            self.routing.fallback_tier,
            *self.routing.preference,
        }
        missing = referenced - self.tiers.keys()
        if missing:
            raise ValueError(f"routing references unknown tiers: {sorted(missing)}")
        return self


class PriceRef(BaseModel):
    description: str = ""
    input: Decimal
    output: Decimal


class LocalCompute(BaseModel):
    enabled: bool = False
    usd_per_second: Decimal = Decimal("0")


class PriceCatalog(BaseModel):
    currency: Literal["USD"] = "USD"
    unit: Literal["per_million_tokens"] = "per_million_tokens"
    references: dict[str, PriceRef]
    local_compute: LocalCompute = LocalCompute()


class GatewayConfig(BaseModel):
    apps: AppsFile
    budgets: BudgetsFile
    models: ModelsFile
    prices: PriceCatalog

    @model_validator(mode="after")
    def _cross_checks(self) -> GatewayConfig:
        for name, tier in self.models.tiers.items():
            if tier.shadow_reference not in self.prices.references:
                raise ValueError(f"tier '{name}' uses unknown shadow_reference")
        keys = [a.api_key for a in self.apps.apps]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate api_key in apps.yaml")
        return self


def _read(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(config_dir: Path) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "apps": _read(config_dir / "apps.yaml"),
            "budgets": _read(config_dir / "budgets.yaml"),
            "models": _read(config_dir / "models.yaml"),
            "prices": _read(config_dir / "price_catalog.yaml"),
        }
    )
