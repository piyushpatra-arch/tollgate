# ADR-0006: Hash-chained, append-only audit log

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

Regulators and internal audit ask "show me every AI decision, including the ones you
blocked, and prove the record hasn't been edited." Application logs are mutable, sampled,
and often contain raw prompts, which is its own privacy problem.

## Decision

Write one audit record per request, **including denied, over-budget, and failed requests**,
in `audit_log`. Each record stores `prev_hash` and
`record_hash = sha256(canonical_json(fields + prev_hash))`, forming a chain. There are no
update or delete code paths. `python -m gateway.cli verify-audit` walks the chain and reports
the first broken record.

Records hold **no raw prompts or responses**: only SHA-256 hashes, token counts, PII entity
counts, policy reason IDs, model tiers, and cost. Values are stored as strings so hashes
reproduce exactly across databases.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A. Plain audit table | Simple | Silent edits undetectable |
| B. Hash chain in Postgres (chosen) | Tamper-evident; zero extra infrastructure; easy to explain | Detects, not prevents; single writer in v1 |
| C. WORM storage / ledger database / external anchoring | Tamper-resistant | Cloud-specific infrastructure; out of scope for local-first v1 |

## Consequences

- Easier: proving completeness and integrity; linking a prompt to its decision by hash
  without storing the prompt.
- Known limits, documented honestly:
  - **Tail truncation** (deleting the newest records) is not detectable from the chain alone.
    Mitigation (roadmap): periodically anchor the head hash externally (e.g. object storage
    with object lock).
  - Appends are serialized with an in-process lock, which is correct for **one gateway
    instance**. Multi-instance deployments need a database-level lock.
  - An attacker with database write access can rewrite the whole chain. Anchoring addresses
    this too.

## Action Items

1. [x] `gateway/pipeline/audit.py`, `verify` CLI, tamper and deletion tests
2. [ ] Head-hash anchoring and a DB-level append lock (roadmap)
