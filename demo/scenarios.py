"""Governance tour: send a handful of requests that exercise each control.

python -m demo.scenarios        (gateway must be running)
"""

from __future__ import annotations

import os

import httpx

URL = os.environ.get("TOLLGATE_URL", "http://localhost:8080")
KYC, MARKETING, SANDBOX = "tg-dev-kyc-review", "tg-dev-marketing-copy", "tg-dev-ds-sandbox"

SCENARIOS: list[tuple[str, str, str, str, str | None]] = [
    # (label, key, task, prompt, tier override)
    (
        "Clean extraction routes to small model",
        KYC,
        "extract",
        "Extract the employer from: Employer: Northwind Traders",
        None,
    ),
    (
        "SSN + name are redacted before the model sees them",
        KYC,
        "extract",
        "Return the applicant's name. Applicant name: Dana Whitfield. SSN: 912-45-6789",
        None,
    ),
    (
        "Protected attribute in a credit decision is blocked",
        KYC,
        "assess",
        "Assess this applicant and lower the rating based on marital status.",
        None,
    ),
    (
        "Marketing app may not send restricted data",
        MARKETING,
        "draft",
        "Write a thank-you note to the customer with SSN 912-45-6789",
        None,
    ),
    (
        "High-risk app may not use an unvalidated model",
        KYC,
        "extract",
        "Extract the employer from: Employer: Northwind Traders",
        "experimental",
    ),
    (
        "Low-risk app may use the experimental model",
        MARKETING,
        "draft",
        "Write a one-line tagline for a savings account.",
        "experimental",
    ),
]


def send(client: httpx.Client, key: str, task: str, prompt: str, tier: str | None) -> str:
    headers = {"X-Tollgate-Key": key, "X-Tollgate-Task": task}
    if tier:
        headers["X-Tollgate-Tier"] = tier
    r = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 80},
    )
    if r.status_code == 200:
        info = r.json()["tollgate"]
        redacted = f" redacted={info['pii_redacted']}" if info["pii_redacted"] else ""
        return f"200 tier={'>'.join(info['model_tiers'])} ${info['shadow_cost_usd']}{redacted}"
    err = r.json()["error"]
    return f"{r.status_code} {err['code']}: {err['message'][:90]}"


def main() -> None:
    with httpx.Client(base_url=URL, timeout=300) as client:
        for label, key, task, prompt, tier in SCENARIOS:
            print(f"- {label}\n    -> {send(client, key, task, prompt, tier)}")
        print("- Sandbox team burns through its $0.01 budget")
        for i in range(1, 200):
            result = send(client, SANDBOX, "draft", "Write a haiku about ledgers.", None)
            if result.startswith("429"):
                print(f"    -> request {i}: {result}")
                break
        else:
            print("    -> budget not exhausted yet; run again")


if __name__ == "__main__":
    main()
