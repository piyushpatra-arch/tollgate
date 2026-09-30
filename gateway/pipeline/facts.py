"""Fact gathering for policy: Python detects, OPA decides (ADR-0004).

The protected-attribute detector is a deliberately simple v1 keyword scan over the
ECOA / Regulation B prohibited bases. It is transparent and testable; an ML classifier is
a roadmap item. It flags *mentions*, which is intentionally conservative for credit tasks.
"""

from __future__ import annotations

import re

PROTECTED_ATTRIBUTE_PATTERNS: dict[str, re.Pattern[str]] = {
    "race_or_color": re.compile(r"\b(race|racial|skin colou?r|ethnicit(y|ies)|ethnic)\b", re.I),
    "religion": re.compile(r"\b(religion|religious)\b", re.I),
    "national_origin": re.compile(r"\b(national origin|nationality|immigrant|citizenship)\b", re.I),
    "sex_or_gender": re.compile(r"\b(sex|gender|pregnan(t|cy))\b", re.I),
    "marital_status": re.compile(r"\b(marital status|married|divorced|single mother)\b", re.I),
    "age": re.compile(r"\b(age|too old|too young|elderly)\b", re.I),
    "public_assistance": re.compile(
        r"\b(public assistance|welfare|food stamps|snap benefits)\b", re.I
    ),
}


def detect_protected_attributes(texts: list[str]) -> list[str]:
    found = {
        category
        for text in texts
        for category, pattern in PROTECTED_ATTRIBUTE_PATTERNS.items()
        if pattern.search(text)
    }
    return sorted(found)
