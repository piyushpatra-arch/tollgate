"""Architecture fitness function: only gateway/providers/ may import litellm (ADR-0001)."""

from __future__ import annotations

import re

from .conftest import ROOT

IMPORT_RE = re.compile(r"^\s*(import litellm|from litellm)", re.M)


def test_litellm_imported_only_in_providers() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "gateway").rglob("*.py")
        if IMPORT_RE.search(path.read_text()) and "providers" not in path.parts
    ]
    assert offenders == []
