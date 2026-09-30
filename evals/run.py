"""Evaluate the KYC agent through Tollgate: routed vs. large-only baseline.

    python -m evals.run --n 20

Writes evals/results.md and evals/results.json. Numbers depend on your models and
hardware — publish what you measure, not what you expect.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from demo.kyc_agent.agent import TollgateClient, load_applicants, review

FLAGS = ["income_mismatch", "address_mismatch", "name_mismatch", "expired_id"]
HERE = Path(__file__).resolve().parent


def run_mode(applicants: list[dict[str, Any]], force_tier: str | None) -> dict[str, Any]:
    client = TollgateClient(force_tier=force_tier)
    correct = dict.fromkeys(FLAGS, 0)
    exact = errors = 0
    started = time.perf_counter()
    for i, applicant in enumerate(applicants, 1):
        try:
            got = review(applicant, client)["assessment"]
        except Exception as exc:  # count and continue: a failed file is a wrong answer
            errors += 1
            print(f"  {applicant['id']}: error {exc}")
            continue
        hits = [bool(got.get(f)) == applicant["labels"][f] for f in FLAGS]
        for f, hit in zip(FLAGS, hits, strict=True):
            correct[f] += hit
        exact += all(hits)
        print(f"  [{i}/{len(applicants)}] {applicant['id']} {'ok' if all(hits) else 'miss'}")
    n = len(applicants)
    tiers = client.log.tiers
    return {
        "mode": "routed" if force_tier is None else f"all-{force_tier}",
        "applicants": n,
        "exact_match_rate": exact / n,
        "flag_accuracy": {f: correct[f] / n for f in FLAGS},
        "errors": errors,
        "model_calls": len(tiers),
        "calls_by_tier": {t: tiers.count(t) for t in sorted(set(tiers))},
        "shadow_cost_usd": round(client.log.shadow_cost, 6),
        "tokens": client.log.prompt_tokens + client.log.completion_tokens,
        "wall_clock_s": round(time.perf_counter() - started, 1),
    }


def to_markdown(results: list[dict[str, Any]]) -> str:
    routed, base = results
    saving = (
        1 - routed["shadow_cost_usd"] / base["shadow_cost_usd"] if base["shadow_cost_usd"] else 0
    )
    rows = [
        ("Applicants reviewed", "applicants", "{}"),
        ("All four flags correct", "exact_match_rate", "{:.0%}"),
        ("Model calls", "model_calls", "{}"),
        ("Shadow cost (USD)", "shadow_cost_usd", "${:.4f}"),
        ("Tokens", "tokens", "{:,}"),
        ("Errors", "errors", "{}"),
        ("Wall clock (s)", "wall_clock_s", "{}"),
    ]
    lines = [
        "# Evaluation results",
        "",
        f"| Metric | {routed['mode']} | {base['mode']} |",
        "|---|---|---|",
        *[
            f"| {label} | {fmt.format(routed[k])} | {fmt.format(base[k])} |"
            for label, k, fmt in rows
        ],
        *[
            f"| {f} accuracy | {routed['flag_accuracy'][f]:.0%} | {base['flag_accuracy'][f]:.0%} |"
            for f in FLAGS
        ],
        f"| Calls by tier | {routed['calls_by_tier']} | {base['calls_by_tier']} |",
        "",
        f"**Shadow-cost change from routing: {-saving:+.0%}** "
        "(priced with config/price_catalog.yaml — check prices before quoting).",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args()
    applicants = load_applicants()[: args.n]
    results = []
    for force in (None, "large"):
        print(f"mode: {'routed' if force is None else 'all-' + force}")
        results.append(run_mode(applicants, force))
    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (HERE / "results.md").write_text(to_markdown(results), encoding="utf-8")
    print((HERE / "results.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
