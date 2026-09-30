"""End-to-end policy test against a real OPA server running policies/ (skipped if no `opa`)."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.pipeline.policy import OpaPolicyEngine

from .conftest import KYC_KEY, MARKETING_KEY, ROOT, chat

OPA = shutil.which("opa")
pytestmark = pytest.mark.skipif(OPA is None, reason="opa binary not on PATH")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603
        [str(OPA), "run", "--server", f"--addr=127.0.0.1:{port}", str(ROOT / "policies")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield url
    proc.terminate()


@pytest.fixture
def opa_client(make_app: Callable[..., FastAPI], opa_url: str) -> Iterator[TestClient]:
    with TestClient(make_app(OpaPolicyEngine(opa_url))) as c:
        yield c


def test_real_policy_allows_clean_request(opa_client: TestClient) -> None:
    assert chat(opa_client, "Extract the employer name.").status_code == 200


def test_real_policy_blocks_protected_attribute_in_assess(opa_client: TestClient) -> None:
    resp = chat(opa_client, "Factor in the applicant's marital status.", task="assess")
    assert resp.status_code == 403
    assert "protected_attribute_in_credit_task" in resp.json()["error"]["message"]


def test_real_policy_blocks_ssn_from_marketing_app(opa_client: TestClient) -> None:
    resp = chat(opa_client, "Write copy for customer SSN 912-45-6789", key=MARKETING_KEY)
    assert resp.status_code == 403
    assert "restricted_data_not_approved" in resp.json()["error"]["message"]


def test_real_policy_blocks_experimental_model_for_high_risk(opa_client: TestClient) -> None:
    resp = chat(opa_client, "hello", key=KYC_KEY, tier="experimental")
    assert resp.status_code == 403
    assert "model_tier_not_approved" in resp.json()["error"]["message"]
    assert chat(opa_client, "hello", key=MARKETING_KEY, tier="experimental").status_code == 200
