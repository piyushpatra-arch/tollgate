# ADR-0004: Policy-as-code with OPA, where Python gathers facts and Rego decides

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

AI governance rules change more often than gateway code, are owned by risk and compliance
rather than engineers, and must be reviewable and testable on their own. Examples in scope:
model approvals per app risk tier, restricted data per app, and ECOA / Reg B concerns for
credit decisions.

## Decision

- Policies are written in **Rego** (`policies/tollgate.rego`) with unit tests
  (`policies/tollgate_test.rego`), evaluated by an **OPA sidecar**.
- The gateway computes **facts** (detected PII entity types, restricted-data flags,
  protected-attribute mentions, app metadata, requested tier) and sends them as policy input.
  It never decides. OPA returns `{allow, reasons[], allowed_tiers[]}`.
- **Fail closed:** if OPA is unreachable or returns no result, the request is denied (503)
  and audited.
- Every denial reason has a stable `id`, which appears in the HTTP error, the audit record,
  and the `tollgate_policy_denials_total{policy_id}` metric.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A. Hard-coded Python checks | Fastest to write | Governance hidden in app code; hard to review; change requires a deploy |
| B. OPA / Rego (chosen) | Industry standard; testable; decoupled lifecycle; readable by non-Python reviewers | Another component; Rego learning curve |
| C. Guardrail library only (e.g. prompt classifiers) | Good content filtering | Not a general authorization and approval engine |

## Consequences

- Easier: policy changes are reviewed as diffs with tests; the same policy can serve other
  gateways or agents later.
- Harder: an extra network hop, a few milliseconds locally. Fact quality bounds policy quality.
  The v1 protected-attribute detector is a transparent keyword scan, which is conservative and
  will produce false positives by design. An ML classifier is on the roadmap.
- Policies are guardrails, not legal advice. Real fair-lending controls need compliance review.

## Action Items

1. [x] Three rules: `protected_attribute_in_credit_task`, `restricted_data_not_approved`,
       `model_tier_not_approved`, with Rego tests
2. [x] Integration tests against a real OPA server (`tests/test_opa_integration.py`)
3. [ ] Policy bundles with signing and versioning (roadmap)
