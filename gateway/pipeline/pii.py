"""Stages 3–4 and 8: detect PII, tokenize it before the model call, restore it afterwards.

Tokenization is consistent within a request: the same value always gets the same token
(e.g. both documents mentioning "Maria Lopez" become <PERSON_1>), so a model can still
compare values across documents without ever seeing them. See ADR-0005.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

ENTITIES = [
    "PERSON",
    "US_SSN",
    "US_ITIN",
    "CREDIT_CARD",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
]

# Restricted data: only apps with restricted_data_approved may send it (enforced in Rego).
RESTRICTED_ENTITIES = frozenset(
    {
        "US_SSN",
        "US_ITIN",
        "CREDIT_CARD",
        "US_BANK_NUMBER",
        "IBAN_CODE",
        "US_PASSPORT",
        "US_DRIVER_LICENSE",
    }
)

TOKEN_RE = re.compile(r"<([A-Z_]+)_(\d+)>")

# Small NER models sometimes pull a role word into a PERSON span ("Applicant Maria Lopez").
# Trimming these keeps tokens consistent across documents that mention the same person.
PERSON_PREFIXES = re.compile(
    r"^(?:(?:applicant|borrower|co-borrower|customer|employee|mr|mrs|ms|dr)\.?\s+)+", re.I
)

PLACEHOLDER_NOTICE = (
    "Note from the gateway: some personal data in this conversation was replaced with "
    "placeholders such as <PERSON_1>. Treat each placeholder as an opaque value, compare "
    "placeholders by exact equality, and reproduce them exactly when you need to refer to them."
)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity: str


@dataclass
class TokenVault:
    """Per-request mapping between original values and placeholder tokens."""

    to_token: dict[tuple[str, str], str] = field(default_factory=dict)
    to_value: dict[str, str] = field(default_factory=dict)
    _counters: Counter[str] = field(default_factory=Counter)

    def token_for(self, entity: str, value: str) -> str:
        key = (entity, value)
        if key not in self.to_token:
            self._counters[entity] += 1
            token = f"<{entity}_{self._counters[entity]}>"
            self.to_token[key] = token
            self.to_value[token] = value
        return self.to_token[key]

    def restore(self, text: str) -> str:
        return TOKEN_RE.sub(lambda m: self.to_value.get(m.group(0), m.group(0)), text)

    def restore_json(self, text: str) -> str:
        """Restore inside parsed JSON so values with quotes/newlines cannot break the document."""
        return json.dumps(self._restore_obj(json.loads(text)))

    def _restore_obj(self, obj: object) -> object:
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, list):
            return [self._restore_obj(v) for v in obj]
        if isinstance(obj, dict):
            return {self.restore(str(k)): self._restore_obj(v) for k, v in obj.items()}
        return obj


def _non_overlapping(results: list[RecognizerResult]) -> list[Span]:
    """Keep the highest-scoring, then longest, span wherever detections overlap."""
    ordered = sorted(results, key=lambda r: (-r.score, -(r.end - r.start), r.start))
    chosen: list[Span] = []
    for r in ordered:
        if all(r.end <= c.start or r.start >= c.end for c in chosen):
            chosen.append(Span(r.start, r.end, r.entity_type))
    return sorted(chosen, key=lambda s: s.start)


def _trim_person(text: str, span: Span) -> Span:
    """Clean NER span edges: drop role words and never let a name run across a line break."""
    if span.entity != "PERSON":
        return span
    start, end = span.start, span.end
    value = text[start:end]
    match = PERSON_PREFIXES.match(value)
    if match and match.end() < len(value):
        start += match.end()
    newline = text.find("\n", start, end)
    if newline != -1:
        end = newline
    return Span(start, end, span.entity)


class PiiService:
    def __init__(self, score_threshold: float = 0.4, spacy_model: str = "en_core_web_sm") -> None:
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": spacy_model}],
            }
        )
        self._analyzer = AnalyzerEngine(
            nlp_engine=provider.create_engine(), supported_languages=["en"]
        )
        self._threshold = score_threshold

    def detect(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        results = self._analyzer.analyze(
            text=text, language="en", entities=ENTITIES, score_threshold=self._threshold
        )
        return [_trim_person(text, span) for span in _non_overlapping(results)]

    def redact(self, text: str, vault: TokenVault) -> tuple[str, Counter[str]]:
        spans = self.detect(text)
        counts: Counter[str] = Counter()
        out: list[str] = []
        cursor = 0
        for span in spans:
            out.append(text[cursor : span.start])
            out.append(vault.token_for(span.entity, text[span.start : span.end]))
            counts[span.entity] += 1
            cursor = span.end
        out.append(text[cursor:])
        return "".join(out), counts
