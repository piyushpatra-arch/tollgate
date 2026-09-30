# ADR-0002: Rule-based model routing with validation fallback

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

Most enterprise LLM traffic is simple (field extraction, classification, short drafts), but
teams default to the largest model for everything. Routing easy work to a small model is the
single biggest cost lever, as long as quality is protected. The router must be explainable
to risk and audit teams, and it must never override policy.

## Decision

Route by an explicit **task tag** supplied by the caller (`X-Tollgate-Task`), mapped to a
tier in `config/models.yaml` (e.g. `extract → small`, `assess → large`). Policy returns the
set of **approved tiers** for the app, and the router only chooses within it.

For JSON-mode requests, the gateway validates the output (JSON parse, plus JSON Schema when
supplied). If the small model's output is invalid, it retries **once** on the fallback tier.
Both calls are recorded in the ledger, so the cost of fallbacks stays visible.

## Options Considered

| Option | Complexity | Explainability | Notes |
|---|---|---|---|
| A. Rule-based on task tag (chosen) | Low | High, a config lookup | Relies on callers tagging honestly |
| B. Prompt-length / heuristic scoring | Low | Medium | Weak proxy for difficulty |
| C. ML classifier (learned router) | High | Low–Medium | Needs labeled traffic we don't have yet |
| D. Cascade everything (small, then escalate) | Medium | Medium | Doubles latency on hard tasks |

## Trade-off Analysis

A task tag makes routing a **business decision the architect owns in config**, not an opaque
model output, which matters in regulated settings. Validation-based fallback gives the
safety of a cascade (D) only where output quality can be checked mechanically.

## Consequences

- Easier: explaining every routing decision; measuring cost vs. quality per task (`evals/`).
- Harder: misdeclared task tags route incorrectly. Mitigation: tags are recorded in the ledger
  and audit log, so misuse is visible per app.
- Revisit when eval data exists to train a classifier (option C), or when free-text quality
  checks (not just JSON validity) are needed.

## Action Items

1. [x] `gateway/pipeline/router.py` and `routing` section of `config/models.yaml`
2. [x] Fallback with both calls costed (`tests/test_gateway_api.py`)
3. [ ] Classifier-based router (roadmap)
