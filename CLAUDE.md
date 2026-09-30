# CLAUDE.md — Tollgate

Instructions for AI coding agents working in this repository. Read this file fully before
making changes. The architecture is owned by the human architect. Your job is to implement
it faithfully, keep it tested, and flag (not silently change) anything that conflicts with it.

## What this project is

Tollgate is a **governed LLM gateway** for regulated AI workloads. Every model request passes
through a control plane that costs it, checks it against policy, scrubs PII, routes it to the
right model, and writes a tamper-evident audit record. A demo **KYC / loan-document review
agent** exercises the gateway with synthetic financial-services data.

## Architecture (source of truth: `docs/architecture.md` and `docs/adr/`)

Request pipeline, implemented in `gateway/pipeline/orchestrator.py`. **Order matters. Do not
reorder without an ADR.**

1. **Identify caller**: `X-Tollgate-Key` → app, team, risk tier (`config/apps.yaml`)
2. **Budget check**: soft limit → `X-Tollgate-Budget-State: soft_limit`; hard limit → 429
3. **Facts + policy**: detect PII entity types and protected-attribute mentions (facts),
   then query OPA `data.tollgate.decision`. Deny → 403 with reason IDs
4. **Tokenize PII**: only redacted text may leave the gateway
5. **Route**: task tag → tier, constrained to the tiers policy approved
6. **Model call**: via the provider interface (LiteLLM → Ollama)
7. **Output checks**: JSON / JSON Schema validation; one fallback to the fallback tier;
   count new PII in the output
8. **Restore tokens** in the response (inside parsed JSON for JSON mode)
9. **Record**: one ledger row per model call; one hash-chained audit record per request.
   **Every request is audited, including denied, failed, and over-budget ones** (`finally`).

The external API is **OpenAI-compatible** (`POST /v1/chat/completions`). Tollgate inputs
travel as headers (`X-Tollgate-Key`, `X-Tollgate-Task`, `X-Tollgate-Tier`), never as breaking
changes to the OpenAI request shape.

## Stack

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x (tables via `create_all` in v1;
  Alembic is roadmap)
- LiteLLM **Python SDK only**. No LiteLLM Proxy (ADR-0001)
- Ollama for local models (host on macOS; optional compose profile on Linux)
- Postgres 16 (SQLite in tests), OPA sidecar, Presidio + spaCy `en_core_web_sm`
- Prometheus client → Prometheus → Grafana (provisioned from `grafana/`)
- `uv` (lockfile committed), Docker Compose, ruff, mypy (strict), pytest, `opa test`

## Repository layout

```
docs/adr/          ADRs: numbered, immutable once Accepted (supersede, don't edit)
gateway/
  api/             HTTP routes and OpenAI-compatible schemas
  pipeline/        identity, budget, facts, policy, pii, router, audit, orchestrator
  finops/          shadow pricing, ledger
  providers/       provider interface + LiteLLM wrapper (the ONLY place importing litellm)
  cli.py           verify-audit, spend
policies/          Rego policies + tests
config/            apps, budgets, models, price catalog
demo/              synthetic data generator, KYC agent, governance scenarios
evals/             routed vs large-only evaluation
grafana/ prometheus/
tests/             unit, API, real-OPA integration, architecture fitness tests
```

## Commands

```bash
make setup | up | down | data | tour | review | eval | test | lint | verify-audit | spend
uv run pytest            # unit + API tests; real-OPA tests run when `opa` is on PATH
opa test policies/ -v
```

## Hard rules

1. **No real personal data, ever.** Data is generated with Faker. SSNs use the 9xx area.
2. **No secrets in the repo.** Env vars only; `.env.example` documents them. Demo keys in
   `config/apps.yaml` are the single documented exception.
3. **Raw prompts and responses are never logged or persisted.** Only hashes, counts, IDs.
4. **The audit log is append-only.** No UPDATE/DELETE paths. Keep `verify` passing.
5. **Only `gateway/providers/` imports `litellm`** (enforced by `tests/test_boundaries.py`).
6. **Policies live in Rego, not Python.** Python gathers facts; OPA decides.
7. **Prices live in `config/price_catalog.yaml`.** Never hard-code prices.
8. **Fail closed.** If OPA or the budget store is unavailable, deny and audit.

## How to work

- **Plan before coding** for any change touching more than one pipeline stage: list the files
  to change and the tests to add, then wait for approval.
- **Small, reviewable changes**, one stage or feature per commit, always with tests:
  unit tests per stage, a Rego test per policy rule, API tests for new behavior.
- **Architecture conflicts:** if an instruction conflicts with an Accepted ADR or this file,
  stop and say so. Propose a new ADR instead of working around it.
- Keep `docs/architecture.md` and the README current when behavior changes.
- Do not add dependencies without stating why. `uv lock` after changes.
- `make lint` and `make test` must pass before a change is done.

## Scope

v1 is implemented (see README). Roadmap items: cloud providers, a classifier router,
a human-in-the-loop queue, PDF/OCR, MCP tool governance, a model registry, Terraform, audit
anchoring, and Alembic. Build these **only when asked**, each starting with an ADR.
