from __future__ import annotations

import json
from pathlib import Path

from .extraction import run_document_extraction
from .ingestion import ingest_source_document_manifest
from .paths import ensure_parent
from .source_docs import make_source_docs_template


def generate_source_ingestion_demo_data(root: str | Path) -> dict[str, Path]:
    """Offline demo for URL/local/HTML source ingestion.

    This deliberately avoids network access: it writes a local HTML earnings
    release, ingests it into a normalized source manifest, then runs the existing
    evidence-grounded extractor on the normalized text file.
    """
    root = Path(root)
    docs_raw = root / "raw_docs"
    normalized = root / "normalized_docs"
    docs_raw.mkdir(parents=True, exist_ok=True)
    html_path = docs_raw / "example_q1_earnings.html"
    html_path.write_text(
        """
        <html>
          <head><title>ExampleCo Q1 Results</title><style>.hidden{display:none}</style></head>
          <body>
            <h1>ExampleCo Reports First Quarter Results</h1>
            <script>window.noise = "ignore me";</script>
            <p>ExampleCo reported revenue of $2.4 billion and diluted EPS of $1.25 for the quarter.</p>
            <p>Analysts expected revenue of $2.2 billion and EPS of $1.10.</p>
            <p>For the next quarter, the company expects revenue of $2.5 billion to $2.7 billion and EPS of $1.30 to $1.40.</p>
            <p>Gross margin was 58.0%; analysts expected gross margin of 56.0%.</p>
          </body>
        </html>
        """.strip(),
        encoding="utf-8",
    )

    input_manifest = root / "source_ingestion_input.csv"
    ingested_manifest = root / "source_documents_ingested.csv"
    facts_out = root / "extracted_facts.csv"
    expectations_out = root / "extracted_expectations.csv"
    events_out = root / "extracted_events.csv"
    diag_out = root / "ingestion_diagnostics.json"

    make_source_docs_template(
        input_manifest,
        rows=[
            {
                "source_doc_id": "EXCO_2024Q1_html_release",
                "ticker": "EXCO",
                "event_id": "EXCO_2024Q1_EARNINGS",
                "event_time": "2024-04-25T16:05:00",
                "event_type": "earnings",
                "event_subtype": "earnings_release",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "source_url": "",
                "title": "ExampleCo Q1 2024 earnings release",
                "path": str(html_path.relative_to(root)),
                "text": "",
                "fiscal_period_end": "2024-03-31",
                "sector_benchmark": "XLK",
                "notes": "Offline source-ingestion demo row.",
            }
        ],
    )
    ingested, diag = ingest_source_document_manifest(input_manifest, ingested_manifest, normalized, overwrite=True)
    facts, expectations, events, extraction_diag = run_document_extraction(
        ingested_manifest,
        facts_out=facts_out,
        expectations_out=expectations_out,
        events_out=events_out,
    )
    ensure_parent(diag_out)
    diag_out.write_text(
        json.dumps({"ingestion": diag.to_dict(), "extraction": extraction_diag.to_dict()}, indent=2),
        encoding="utf-8",
    )
    return {
        "raw_html": html_path,
        "input_manifest": input_manifest,
        "ingested_manifest": ingested_manifest,
        "normalized_docs_dir": normalized,
        "facts": facts_out,
        "expectations": expectations_out,
        "events": events_out,
        "diagnostics": diag_out,
    }
