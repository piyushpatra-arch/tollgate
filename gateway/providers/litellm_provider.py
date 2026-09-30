"""The only module allowed to import litellm (enforced by tests/test_boundaries.py)."""

from __future__ import annotations

from typing import Any

import litellm

from gateway.providers.base import ModelRequest, ModelResponse, ProviderError, extra_kwargs

litellm.telemetry = False


class LiteLLMProvider:
    def __init__(self, ollama_api_base: str, timeout_s: float) -> None:
        self._api_base = ollama_api_base
        self._timeout = timeout_s

    def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs = extra_kwargs(request)
        if request.model.startswith("ollama"):
            kwargs["api_base"] = self._api_base
        try:
            resp: Any = litellm.completion(
                model=request.model,
                messages=request.messages,
                timeout=self._timeout,
                **kwargs,
            )
        except Exception as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return ModelResponse(
            content=choice.message.content or "",
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=str(choice.finish_reason or "stop"),
        )
