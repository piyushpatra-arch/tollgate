"""Provider interface. The pipeline depends on this, never on a vendor SDK (ADR-0001)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    model: str  # provider model string, e.g. "ollama_chat/llama3.2:3b"
    messages: list[dict[str, str]]
    temperature: float | None = None
    max_tokens: int | None = None
    json_mode: bool = False


@dataclass(frozen=True)
class ModelResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"
    actual_cost_usd: float = 0.0  # non-zero only for paid providers


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ProviderError(Exception):
    """Raised when the upstream model cannot be reached or errors."""


def extra_kwargs(request: ModelRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs
