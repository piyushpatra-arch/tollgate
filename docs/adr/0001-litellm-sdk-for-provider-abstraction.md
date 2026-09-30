# ADR-0001: Use the LiteLLM Python SDK for model-provider abstraction

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

Tollgate must call LLMs from more than one provider. v1 runs local models through Ollama;
later phases must reach AWS Bedrock and Azure OpenAI without redesigning the gateway.
The project's value lies in the **control plane** — cost attribution, policy enforcement,
PII handling, routing, and audit — not in provider plumbing.

Constraints:

- Very small build budget (~12–15 hours total, AI-assisted implementation)
- Local-first: must run free on a laptop with Ollama
- Cloud portability should be a configuration change, not a code change
- Governance logic (budgets, policy, audit) must be owned, inspectable, and testable in this
  repo, because demonstrating that logic is the purpose of the project

## Decision

Use the **LiteLLM Python SDK as a library** behind a thin internal provider interface
(`gateway/providers/`). Tollgate implements its own budgets, cost ledger, policy, redaction,
routing, and audit. We do **not** deploy the LiteLLM Proxy server or adopt a third-party AI
gateway product for v1.

## Options Considered

### Option A: Hand-written provider clients

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium–High (one client per provider, streaming, retries, error mapping) |
| Cost | Build hours spent on non-differentiating code |
| Scalability | Each new provider is new code |
| Team familiarity | High, but tedious |

**Pros:** No external dependency; full control of behavior.
**Cons:** Consumes most of the time budget on plumbing; reinvents a solved problem; more
surface area to test.

### Option B: LiteLLM Python SDK behind an internal interface (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low — one wrapper module |
| Cost | Free, open source |
| Scalability | Adding Bedrock/Azure is configuration in `config/models.yaml` |
| Team familiarity | Widely used; OpenAI-style interface |

**Pros:** Unified OpenAI-compatible call shape across Ollama, Bedrock, and Azure OpenAI;
token usage returned consistently for cost accounting; frees time for governance features.
**Cons:** Large, fast-moving dependency; its behavior sits in our request path.

### Option C: Adopt LiteLLM Proxy (off-the-shelf gateway)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low to deploy |
| Cost | Free tier; enterprise features may be licensed |
| Scalability | Good |
| Team familiarity | Configuration-driven |

**Pros:** Ships with its own spend tracking, keys, and budgeting.
**Cons:** Governance behavior would be configured rather than designed; policy-as-code, PII
tokenization, and hash-chained audit would need to be bolted on around a product we don't
control. Defeats the purpose of this project.

### Option D: Commercial or other open-source AI gateway

**Pros:** Production-grade features, vendor support.
**Cons:** Same objection as C, plus licensing and heavier local setup.

## Trade-off Analysis

The decisive factor is **where the differentiating logic lives**. Options C and D are
reasonable enterprise choices when the goal is simply to operate a gateway; in many
organizations adopting one would be the default recommendation. This project's goal is to
show the design of the control plane itself, so that logic must be owned in this repo.
Between A and B, B buys provider portability for a single wrapper module, at the cost of a
dependency whose risk we can contain.

## Consequences

- **Easier:** switching Ollama → Bedrock/Azure by config; consistent token usage for the
  ledger; spending build time on governance features.
- **Harder:** we depend on LiteLLM's release cadence and correctness for provider calls.
- **Mitigations:**
  - Only `gateway/providers/` may import `litellm` (enforced by a lint/test check), so it
    can be replaced without touching the pipeline.
  - Pin the version and commit the lockfile; review changelogs before upgrading.
  - Do not use LiteLLM's own cost figures as the system of record — Tollgate computes cost
    from `config/price_catalog.yaml` (see ADR-0003).
- **Revisit when:** moving to production-scale deployment, where adopting a supported
  gateway product (Option C/D) and keeping Tollgate's policy and audit layers as extensions
  may be the better operating model.

## Action Items

1. [x] Create `gateway/providers/base.py` with a `ModelProvider` protocol
       (`complete(request) -> ModelResponse` including token usage).
2. [x] Implement `LiteLLMProvider` in `gateway/providers/litellm_provider.py`.
3. [x] Define Ollama models in `config/models.yaml` (small + large tier).
4. [x] Add a test that fails if `litellm` is imported outside `gateway/providers/`
       (`tests/test_boundaries.py`).
5. [x] Commit `uv.lock` so every install resolves the same `litellm` version.
