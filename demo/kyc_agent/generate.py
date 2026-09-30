"""Generate SYNTHETIC loan applicants with planted, labeled inconsistencies.

No real personal data is used anywhere in this project. SSNs use the 9xx area range,
which the US Social Security Administration never issues.

    python -m demo.kyc_agent.generate --n 50 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

OUT = Path(__file__).resolve().parents[1] / "data" / "applicants.jsonl"
INCOME_TOLERANCE = 0.15  # documented rule the agent is asked to apply
PURPOSES = ["home improvement", "debt consolidation", "vehicle purchase", "small business"]


def _ssn(rng: random.Random) -> str:
    return f"9{rng.randint(0, 99):02d}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"


def _address(fake: Faker) -> str:
    return f"{fake.street_address()}, {fake.city()}, {fake.state_abbr()} {fake.zipcode()}"


def make_applicant(i: int, fake: Faker, rng: random.Random, today: date) -> dict[str, object]:
    labels = {
        "income_mismatch": rng.random() < 0.3,
        "address_mismatch": rng.random() < 0.25,
        "name_mismatch": rng.random() < 0.15,
        "expired_id": rng.random() < 0.2,
    }
    first, last = fake.first_name(), fake.last_name()
    name = f"{first} {last}"
    other_name = f"{first} {fake.last_name()}" if labels["name_mismatch"] else name
    dob = fake.date_of_birth(minimum_age=22, maximum_age=70)
    address = _address(fake)
    other_address = _address(fake) if labels["address_mismatch"] else address
    employer = fake.company()
    income = rng.randrange(42_000, 185_000, 500)
    ratio = rng.uniform(0.55, 0.75) if labels["income_mismatch"] else rng.uniform(0.97, 1.03)
    monthly_gross = round(income / 12 * ratio, 2)
    expiry = (
        today - timedelta(days=rng.randint(30, 900))
        if labels["expired_id"]
        else today + timedelta(days=rng.randint(120, 2000))
    )

    documents = {
        "application": (
            "LOAN APPLICATION\n"
            f"Applicant name: {name}\n"
            f"Date of birth: {dob.isoformat()}\n"
            f"SSN: {_ssn(rng)}\n"
            f"Home address: {address}\n"
            f"Phone: {fake.numerify('(###) 555-01##')}\n"
            f"Employer: {employer}\n"
            f"Stated annual income: ${income:,}\n"
            f"Requested loan amount: ${rng.randrange(5_000, 60_000, 500):,}\n"
            f"Loan purpose: {rng.choice(PURPOSES)}\n"
        ),
        "pay_stub": (
            "EARNINGS STATEMENT\n"
            f"Employee: {other_name}\n"
            f"Employer: {employer}\n"
            f"Pay period: {(today - timedelta(days=30)).strftime('%B %Y')}\n"
            f"Gross monthly pay: ${monthly_gross:,.2f}\n"
            f"Net pay: ${monthly_gross * 0.74:,.2f}\n"
        ),
        "bank_statement": (
            "BANK STATEMENT SUMMARY\n"
            f"Account holder: {name}\n"
            f"Mailing address: {other_address}\n"
            f"Account number: {rng.randint(10**11, 10**12 - 1)}\n"
            f"Average monthly deposits (last 3 months): ${monthly_gross * 0.74:,.2f}\n"
        ),
        "id_record": (
            "IDENTITY DOCUMENT RECORD\n"
            f"Full name: {name}\n"
            f"Date of birth: {dob.isoformat()}\n"
            f"Address: {address}\n"
            f"Expiration date: {expiry.isoformat()}\n"
        ),
    }
    return {"id": f"APP-{i:04d}", "documents": documents, "labels": labels}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    fake = Faker("en_US")
    Faker.seed(args.seed)
    rng = random.Random(args.seed)
    today = date.today()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for i in range(1, args.n + 1):
            fh.write(json.dumps(make_applicant(i, fake, rng, today)) + "\n")
    print(f"wrote {args.n} synthetic applicants to {args.out}")


if __name__ == "__main__":
    main()
