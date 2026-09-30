"""Application factory. Dependencies are injectable so tests can swap the model and OPA."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from gateway.api.routes import gateway_error_handler, router
from gateway.config import load_config
from gateway.db import Database
from gateway.errors import GatewayError
from gateway.finops.ledger import Ledger
from gateway.pipeline.audit import AuditLog
from gateway.pipeline.orchestrator import Gateway
from gateway.pipeline.pii import PiiService
from gateway.pipeline.policy import OpaPolicyEngine, PolicyEngine
from gateway.providers.base import ModelProvider
from gateway.settings import Settings

# Never log request bodies: they may contain PII before redaction.
logging.getLogger("LiteLLM").setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None,
    provider: ModelProvider | None = None,
    policy: PolicyEngine | None = None,
    pii: PiiService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    config = load_config(settings.config_dir)
    db = Database(settings.database_url)
    db.create_all()

    if provider is None:
        from gateway.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(settings.ollama_api_base, settings.model_timeout_s)

    gateway = Gateway(
        config=config,
        provider=provider,
        policy=policy or OpaPolicyEngine(settings.opa_url, settings.opa_timeout_s),
        pii=pii or PiiService(settings.pii_score_threshold),
        ledger=Ledger(db),
        audit=AuditLog(db),
    )

    app = FastAPI(
        title="Tollgate",
        version="0.1.0",
        description="Governed LLM gateway: FinOps, policy-as-code, PII redaction, audit.",
    )
    app.state.gateway = gateway
    app.state.db = db
    app.include_router(router)
    app.add_exception_handler(GatewayError, gateway_error_handler)
    return app


def app_factory() -> FastAPI:  # used by: uvicorn --factory gateway.main:app_factory
    return create_app()
