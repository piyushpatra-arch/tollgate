# ADR-0007: Local-first deployment, cloud-portable by configuration

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Piyush (architect)

## Context

The project must be runnable by anyone reviewing it, for free, in minutes, without cloud
accounts or API keys, while still showing a credible path to AWS or Azure.

## Decision

- Ship a **Docker Compose** stack: gateway, Postgres, OPA, Prometheus, Grafana.
- Use **Ollama** for models. On macOS it runs on the host, because Docker cannot use Apple
  GPUs. On Linux an optional `ollama` compose profile is provided.
- Keep every environment-specific value in env vars or `config/`. Moving a tier to
  Bedrock or Azure OpenAI is a change to `litellm_model` in `config/models.yaml` plus
  credentials, with no code changes (ADR-0001).

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A. Local-first Compose (chosen) | Free, reproducible, reviewer-friendly | Not production topology |
| B. Cloud-first (Terraform to AWS/Azure) | Production-like | Costs money; reviewers can't run it; slows iteration |
| C. Kubernetes (kind/minikube) | Closer to production | Heavy for a laptop demo |

## Consequences

- Easier: `make up` → working stack; CI runs the full test suite without any model.
- Harder: production concerns (HA, secrets management, network policy) are documented
  rather than implemented.
- Revisit with a Terraform module for one cloud once v1 is published (roadmap).
