.PHONY: setup models up down logs data tour review eval test lint verify-audit spend

SMALL_MODEL ?= llama3.2:3b
LARGE_MODEL ?= llama3.1:8b

setup:          ## install Python deps for tests, demo and evals
	uv sync

models:         ## pull the local models (Ollama must be running)
	ollama pull $(SMALL_MODEL)
	ollama pull $(LARGE_MODEL)

up:             ## start gateway, postgres, opa, prometheus, grafana
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f gateway

data:           ## generate 50 synthetic applicants
	uv run python -m demo.kyc_agent.generate --n 50

tour:           ## governance scenarios: redaction, denials, budget 429
	uv run python -m demo.scenarios

review:         ## run the KYC agent on one applicant
	uv run python -m demo.kyc_agent.agent --id APP-0001

eval:           ## routed vs large-only comparison -> evals/results.md
	uv run python -m evals.run --n 20

test:
	uv run pytest
	opa test policies/ -v

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy

verify-audit:   ## verify the audit hash chain in the running stack
	docker compose exec gateway /app/.venv/bin/python -m gateway.cli verify-audit

spend:          ## month-to-date spend by team vs budget
	docker compose exec gateway /app/.venv/bin/python -m gateway.cli spend
