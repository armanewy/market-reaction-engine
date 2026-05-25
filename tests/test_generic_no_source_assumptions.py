from __future__ import annotations

from pathlib import Path


def test_generic_modules_do_not_contain_source_specific_terms():
    root = Path("src/mre/generic")
    forbidden = (
        "cyber",
        "sec",
        "edgar",
        "8-k",
        "item 1.05",
        "cik",
        "ticker",
        "accession",
        "lei",
    )

    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            if term in text:
                offenders.append(f"{path}:{term}")

    assert offenders == []
