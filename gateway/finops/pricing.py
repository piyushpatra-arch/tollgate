"""Shadow pricing (ADR-0003): price every call against a comparable cloud model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gateway.config import PriceCatalog

MILLION = Decimal(1_000_000)
QUANT = Decimal("0.00000001")


@dataclass(frozen=True)
class CallCost:
    actual_usd: Decimal
    shadow_usd: Decimal
    shadow_reference: str


def price_call(
    catalog: PriceCatalog,
    shadow_reference: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_s: float,
    actual_usd: Decimal = Decimal("0"),
) -> CallCost:
    ref = catalog.references[shadow_reference]
    shadow = (
        Decimal(prompt_tokens) * ref.input + Decimal(completion_tokens) * ref.output
    ) / MILLION
    if catalog.local_compute.enabled:
        actual_usd += catalog.local_compute.usd_per_second * Decimal(str(latency_s))
    return CallCost(
        actual_usd=actual_usd.quantize(QUANT),
        shadow_usd=shadow.quantize(QUANT),
        shadow_reference=shadow_reference,
    )
