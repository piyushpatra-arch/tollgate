"""KYC / loan-document review agent. Every model call goes through Tollgate.

Step 1 (task=extract, small model): pull structured fields from each document.
Step 2 (task=assess, large model):  cross-check the fields and flag inconsistencies.

    python -m demo.kyc_agent.agent --id APP-0001
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from demo.kyc_agent.generate import INCOME_TOLERANCE, OUT

GATEWAY_URL = os.environ.get("TOLLGATE_URL", "http://localhost:8080")
API_KEY = os.environ.get("TOLLGATE_KEY", "tg-dev-kyc-review")

EXTRACT_FIELDS = {
    "application": "applicant_name, date_of_birth, home_address, employer, "
    "stated_annual_income (number), requested_loan_amount (number)",
    "pay_stub": "employee_name, employer, gross_monthly_pay (number)",
    "bank_statement": "account_holder_name, mailing_address, average_monthly_deposits (number)",
    "id_record": "full_name, date_of_birth, address, expiration_date (YYYY-MM-DD)",
}

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "income_mismatch",
        "address_mismatch",
        "name_mismatch",
        "expired_id",
        "risk_level",
        "summary",
    ],
    "properties": {
        "income_mismatch": {"type": "boolean"},
        "address_mismatch": {"type": "boolean"},
        "name_mismatch": {"type": "boolean"},
        "expired_id": {"type": "boolean"},
        "risk_level": {"enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
    },
}

ASSESS_RULES = f"""You are a KYC analyst reviewing a loan file. Today is {{today}}.
Apply these rules exactly:
- income_mismatch: true if (gross_monthly_pay x 12) differs from stated_annual_income by more
  than {int(INCOME_TOLERANCE * 100)}%.
- address_mismatch: true if any address differs from the application's home_address
  (ignore formatting differences only).
- name_mismatch: true if any document's name differs from the application's applicant_name.
- expired_id: true if the ID expiration_date is before today.
- risk_level: high if 2+ flags, medium if exactly 1 flag, otherwise low.
Base the assessment only on the documents. Respond with JSON only, using keys:
income_mismatch, address_mismatch, name_mismatch, expired_id, risk_level, summary."""


@dataclass
class CallLog:
    tiers: list[str] = field(default_factory=list)
    shadow_cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class TollgateClient:
    def __init__(self, url: str = GATEWAY_URL, key: str = API_KEY, force_tier: str | None = None):
        self._http = httpx.Client(base_url=url, timeout=300)
        self._key = key
        self._force_tier = force_tier
        self.log = CallLog()

    def chat(self, task: str, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        headers = {"X-Tollgate-Key": self._key, "X-Tollgate-Task": task}
        if self._force_tier:
            headers["X-Tollgate-Tier"] = self._force_tier
        response_format: dict[str, Any] = (
            {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
            if schema
            else {"type": "json_object"}
        )
        resp = self._http.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": response_format,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.json()['error']['message']}")
        body = resp.json()
        self.log.tiers.extend(body["tollgate"]["model_tiers"])
        self.log.shadow_cost += float(body["tollgate"]["shadow_cost_usd"])
        self.log.prompt_tokens += body["usage"]["prompt_tokens"]
        self.log.completion_tokens += body["usage"]["completion_tokens"]
        return json.loads(body["choices"][0]["message"]["content"])


def review(applicant: dict[str, Any], client: TollgateClient) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for doc_type, text in applicant["documents"].items():
        extracted[doc_type] = client.chat(
            task="extract",
            system=f"Extract these fields as a flat JSON object: {EXTRACT_FIELDS[doc_type]}. "
            "Copy values exactly as written. Use null if a field is missing.",
            user=text,
        )
    assessment: dict[str, Any] = client.chat(
        task="assess",
        system=ASSESS_RULES.format(today=date.today().isoformat()),
        user=json.dumps(extracted, indent=2),
        schema=ASSESSMENT_SCHEMA,
    )
    return {"id": applicant["id"], "extracted": extracted, "assessment": assessment}


def load_applicants(path: Path = OUT) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit("no data yet: run `python -m demo.kyc_agent.generate` first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default="APP-0001")
    args = parser.parse_args()
    applicant = next(a for a in load_applicants() if a["id"] == args.id)
    client = TollgateClient()
    result = review(applicant, client)
    print(json.dumps(result["assessment"], indent=2))
    print(f"\nexpected flags: {applicant['labels']}")
    print(f"model tiers used: {client.log.tiers}  shadow cost: ${client.log.shadow_cost:.6f}")


if __name__ == "__main__":
    main()
