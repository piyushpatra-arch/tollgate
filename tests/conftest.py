from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.pipeline.pii import PiiService
from gateway.pipeline.policy import PolicyDecision
from gateway.providers.base import ModelRequest, ModelResponse
from gateway.settings import Settings

ROOT = Path(__file__).resolve().parents[1]

KYC_KEY = "tg-dev-kyc-review"
MARKETING_KEY = "tg-dev-marketing-copy"
SANDBOX_KEY = "tg-dev-ds-sandbox"


class FakeProvider:
    """Scripted model. `replies` maps model string -> list of replies consumed in order."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []
        self.replies: dict[str, list[str]] = {}
        self.default_reply = '{"ok": true}'

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        queue = self.replies.get(request.model, [])
        content = queue.pop(0) if queue else self.default_reply
        return ModelResponse(content=content, prompt_tokens=1000, completion_tokens=200)


class StaticPolicy:
    """Stand-in for OPA in unit tests; tests/test_opa_integration.py uses the real thing."""

    def __init__(self) -> None:
        self.decision = PolicyDecision(allow=True, allowed_tiers=["large", "small"])
        self.inputs: list[dict[str, Any]] = []

    def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision:
        self.inputs.append(policy_input)
        return self.decision


@pytest.fixture(scope="session")
def pii_service() -> PiiService:
    return PiiService()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        config_dir=ROOT / "config",
        opa_url="http://127.0.0.1:1",  # nothing listens here
    )


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def policy() -> StaticPolicy:
    return StaticPolicy()


@pytest.fixture
def make_app(
    settings: Settings, provider: FakeProvider, pii_service: PiiService
) -> Callable[..., FastAPI]:
    def _make(policy: Any = None) -> FastAPI:
        return create_app(settings, provider=provider, policy=policy, pii=pii_service)

    return _make


@pytest.fixture
def client(make_app: Callable[..., FastAPI], policy: StaticPolicy) -> Iterator[TestClient]:
    with TestClient(make_app(policy)) as c:
        yield c


def chat(
    client: TestClient,
    content: str,
    key: str | None = KYC_KEY,
    task: str = "extract",
    tier: str | None = None,
    json_mode: bool = False,
) -> Any:
    headers = {"X-Tollgate-Task": task}
    if key:
        headers["X-Tollgate-Key"] = key
    if tier:
        headers["X-Tollgate-Tier"] = tier
    body: dict[str, Any] = {"messages": [{"role": "user", "content": content}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return client.post("/v1/chat/completions", json=body, headers=headers)
