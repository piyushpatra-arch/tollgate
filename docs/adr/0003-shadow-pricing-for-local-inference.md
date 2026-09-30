# ADR-0003: Shadow pricing for local inference

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

v1 runs entirely on local Ollama models, so the per-token bill is zero. A FinOps control
plane that reports $0 demonstrates nothing, and it hides the question leaders actually ask:
*what will this workload cost when it runs on a managed cloud model?*

## Decision

Every model call is priced twice and both values are stored in the ledger:

- `actual_cost_usd`: what was really paid (0 for local; optionally amortized local compute
  via `local_compute.usd_per_second`).
- `shadow_cost_usd`: tokens × list price of a **comparable cloud model class**, from
  `config/price_catalog.yaml`, mapped per tier in `config/models.yaml`.

Budgets are enforced on `actual + shadow`, so teams feel cloud-realistic limits during
development. Prices live only in config; code never hard-codes a price, and LiteLLM's own
cost estimates are not the system of record.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A. Track tokens only | Simple | Tokens mean nothing to finance |
| B. Shadow pricing from a catalog (chosen) | Cloud-realistic, finance-readable, comparable across tiers | Prices must be maintained |
| C. Use LiteLLM's built-in cost map | No maintenance | Ties the system of record to a dependency; opaque for local models |

## Consequences

- Easier: chargeback and showback by team and app today, and a "cloud readiness" cost estimate.
- Easier: when a cloud provider is added, `actual_cost_usd` becomes real and can be
  reconciled against shadow estimates.
- Harder: the catalog can drift from real prices. Mitigation: the file is clearly marked
  illustrative, and prices must be checked before any number is published.
- Shadow cost for a small local model priced as a "small cloud class" is an **estimate of
  cost class, not a benchmark claim** about model equivalence.

## Action Items

1. [x] `gateway/finops/pricing.py`, `config/price_catalog.yaml`, ledger columns
2. [ ] Reconciliation job once a paid provider is configured (roadmap)
