from __future__ import annotations

from pathlib import Path

import pandas as pd

from .extraction import run_document_extraction
from .paths import ensure_dir
from .source_docs import make_source_docs_template


def generate_extraction_demo_data(root: str | Path) -> dict[str, Path]:
    """Generate an offline source-document extraction demo."""
    root = Path(root)
    docs_dir = ensure_dir(root / "docs")
    manifest_path = root / "source_documents.csv"
    facts_path = root / "extracted_facts.csv"
    expectations_path = root / "extracted_expectations.csv"
    events_path = root / "extracted_events.csv"

    text1 = """ACME Reports Fiscal Q1 Results
ACME reported revenue of $2.45 billion for the quarter. Diluted EPS was $1.14.
Gross margin was 58.2%.
Analysts expected revenue of $2.37 billion and consensus EPS of $1.05.
For the next quarter, ACME expects revenue between $2.50 billion and $2.60 billion.
The company expects EPS guidance of $1.10 to $1.18 and gross margin between 57.0% and 59.0%.
"""
    text2 = """BETA Announces Quarterly Results
BETA revenue was $875 million, while EPS was $0.42. Gross margin was 43.5%.
Consensus revenue estimate was $910 million and analysts expected EPS of $0.50.
Management forecast revenue of $840 million to $880 million for the current quarter.
"""
    p1 = docs_dir / "acme_q1.txt"
    p2 = docs_dir / "beta_q1.txt"
    p1.write_text(text1, encoding="utf-8")
    p2.write_text(text2, encoding="utf-8")

    make_source_docs_template(
        manifest_path,
        rows=[
            {
                "source_doc_id": "demo_acme_q1",
                "ticker": "ACME",
                "event_id": "demo_acme_earnings_q1",
                "event_time": "2024-04-24T16:10:00",
                "event_type": "earnings",
                "event_subtype": "quarterly_results",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "source_url": "",
                "title": "ACME Reports Fiscal Q1 Results",
                "path": "docs/acme_q1.txt",
                "sector_benchmark": "XLK",
                "notes": "Synthetic extraction demo document.",
            },
            {
                "source_doc_id": "demo_beta_q1",
                "ticker": "BETA",
                "event_id": "demo_beta_earnings_q1",
                "event_time": "2024-04-25T08:00:00",
                "event_type": "earnings",
                "event_subtype": "quarterly_results",
                "release_session": "before_open",
                "source_type": "company_press_release",
                "source_url": "",
                "title": "BETA Announces Quarterly Results",
                "path": "docs/beta_q1.txt",
                "sector_benchmark": "XLK",
                "notes": "Synthetic extraction demo document.",
            },
        ],
    )
    facts, expectations, events, diagnostics = run_document_extraction(
        manifest_path,
        facts_out=facts_path,
        expectations_out=expectations_path,
        events_out=events_path,
    )
    pd.DataFrame([diagnostics.to_dict()]).to_json(root / "extraction_diagnostics.json", orient="records", indent=2)
    return {
        "root": root,
        "manifest": manifest_path,
        "facts": facts_path,
        "expectations": expectations_path,
        "events": events_path,
        "diagnostics": root / "extraction_diagnostics.json",
    }
