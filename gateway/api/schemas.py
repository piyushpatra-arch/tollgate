"""OpenAI-compatible request/response shapes (the subset Tollgate supports in v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "auto"  # ignored: the router chooses; use X-Tollgate-Tier to request a tier
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    response_format: dict[str, Any] | None = None
    stream: bool = False


class TollgateInfo(BaseModel):
    request_id: str
    model_tiers: list[str]
    shadow_cost_usd: str
    budget_state: str
    pii_redacted: dict[str, int]


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
    tollgate: TollgateInfo
