"""HTTP layer: translate between OpenAI-style HTTP and the Gateway pipeline."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from gateway.api.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    TollgateInfo,
    Usage,
)
from gateway.errors import GatewayError
from gateway.finops.ledger import month_start_iso
from gateway.pipeline.orchestrator import Gateway, GatewayRequest

router = APIRouter()


def _gateway(request: Request) -> Gateway:
    gw: Gateway = request.app.state.gateway
    return gw


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    response: Response,
    x_tollgate_key: Annotated[str | None, Header()] = None,
    x_tollgate_task: Annotated[str, Header()] = "general",
    x_tollgate_tier: Annotated[str | None, Header()] = None,
) -> ChatCompletionResponse:
    if body.stream:
        raise GatewayError(400, "unsupported", "streaming is not supported in v1")
    result = _gateway(request).handle(
        GatewayRequest(
            messages=[m.model_dump() for m in body.messages],
            api_key=x_tollgate_key,
            task=x_tollgate_task,
            tier_override=x_tollgate_tier,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            response_format=body.response_format,
        )
    )
    response.headers.update(
        {
            "X-Tollgate-Request-Id": result.request_id,
            "X-Tollgate-Model-Tier": ">".join(result.model_tiers),
            "X-Tollgate-Shadow-Cost-USD": f"{result.shadow_cost_usd:.8f}",
            "X-Tollgate-Budget-State": result.budget_state,
        }
    )
    return ChatCompletionResponse(
        id=result.request_id,
        created=int(time.time()),
        model=result.model,
        choices=[
            Choice(
                message=ChatMessage(role="assistant", content=result.content),
                finish_reason=result.finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        tollgate=TollgateInfo(
            request_id=result.request_id,
            model_tiers=result.model_tiers,
            shadow_cost_usd=f"{result.shadow_cost_usd:.8f}",
            budget_state=result.budget_state,
            pii_redacted=result.pii_redacted,
        ),
    )


@router.get("/v1/budgets")
def budgets(request: Request) -> dict[str, object]:
    gw = _gateway(request)
    teams = {a.team for a in gw.config.apps.apps}
    out = {}
    for team in sorted(teams):
        spent, limit = gw.budgets.status(team)
        out[team] = {"spent_usd": f"{spent:.6f}", "limit_usd": f"{limit:.2f}"}
    return {"period_start": month_start_iso(), "teams": out}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def gateway_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GatewayError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": "tollgate_error", "code": exc.code, "message": exc.message}},
    )
