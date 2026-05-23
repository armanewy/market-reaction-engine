from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.extraction import run_document_extraction
from mre.ingestion import build_sec_source_document_manifest, ingest_source_document_manifest, normalize_document_text
from mre.source_docs import load_source_documents, make_source_docs_template


def test_normalize_document_text_removes_scripts_and_keeps_content() -> None:
    raw = """<html><head><style>.x{}</style></head><body><script>bad()</script><p>Revenue was $1.2 billion.</p><p>EPS was $0.44.</p></body></html>"""
    text = normalize_document_text(raw, content_type="text/html", source_name="release.html")
    assert "bad()" not in text
    assert "Revenue was $1.2 billion" in text
    assert "EPS was $0.44" in text


def test_ingest_source_document_manifest_normalizes_local_html_and_extracts(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    html_path = raw_dir / "release.html"
    html_path.write_text(
        """
        <html><body>
        <h1>ACME Results</h1>
        <p>ACME reported revenue of $2.45 billion. Diluted EPS was $1.14.</p>
        <p>Analysts expected revenue of $2.37 billion and consensus EPS of $1.05.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    input_manifest = tmp_path / "input.csv"
    out_manifest = tmp_path / "source_documents.csv"
    make_source_docs_template(
        input_manifest,
        rows=[
            {
                "source_doc_id": "ACME_release",
                "ticker": "ACME",
                "event_id": "ACME_evt",
                "event_time": "2024-01-31T16:10:00",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "path": "raw/release.html",
            }
        ],
    )
    out, diag = ingest_source_document_manifest(input_manifest, out_manifest, tmp_path / "normalized", overwrite=True)
    assert diag.rows_written == 1
    assert int(out.iloc[0]["text_chars"]) > 100
    assert out.iloc[0]["source_hash"]
    docs = load_source_documents(out_manifest)
    assert len(docs) == 1
    assert "ACME reported revenue" in docs[0].text

    facts, expectations, events, extraction_diag = run_document_extraction(
        out_manifest,
        facts_out=tmp_path / "facts.csv",
        expectations_out=tmp_path / "expectations.csv",
        events_out=tmp_path / "events.csv",
    )
    assert extraction_diag.documents_with_facts == 1
    assert {"actual_revenue", "actual_eps", "consensus_revenue", "consensus_eps"}.issubset(set(facts["fact_name"]))
    assert expectations.iloc[0]["revenue_surprise_pct"] > 0
    assert events.iloc[0]["event_id"] == "ACME_evt"


class FakeSecClient:
    def recent_filings(self, ticker: str, forms=None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "company_name": "Acme Inc",
                    "cik": 123456,
                    "form": "8-K",
                    "items": "2.02,9.01",
                    "filingDate": "2024-01-31",
                    "acceptanceDateTime": "2024-01-31T16:15:00.000Z",
                    "accessionNumber": "0000123456-24-000001",
                    "primaryDocument": "acme-20240131.htm",
                    "primaryDocDescription": "Results of Operations",
                },
                {
                    "ticker": ticker,
                    "company_name": "Acme Inc",
                    "cik": 123456,
                    "form": "8-K",
                    "items": "5.02",
                    "filingDate": "2024-02-01",
                    "acceptanceDateTime": "2024-02-01T16:15:00.000Z",
                    "accessionNumber": "0000123456-24-000002",
                    "primaryDocument": "acme-other.htm",
                    "primaryDocDescription": "Management Change",
                },
            ]
        )

    def filing_documents(self, filing_row, include_primary=True, include_exhibits=True, exhibit_pattern=None):
        return [
            {"name": "acme-20240131.htm", "url": "https://sec.test/acme-primary.htm", "is_primary": True, "is_exhibit": False},
            {"name": "ex99-1.htm", "url": "https://sec.test/ex99-1.htm", "is_primary": False, "is_exhibit": True},
        ]

    def filing_document_url(self, cik: int, accession: str, document_name: str) -> str:
        return f"https://sec.test/{document_name}"

    def fetch_document_text(self, url: str):
        if url.endswith("ex99-1.htm"):
            return (
                "<html><body><p>ACME reported revenue of $2.45 billion. EPS was $1.14.</p>"
                "<p>Analysts expected revenue of $2.37 billion and consensus EPS of $1.05.</p></body></html>",
                "text/html",
            )
        return "<html><body><p>8-K cover page</p></body></html>", "text/html"


def test_build_sec_source_document_manifest_with_fake_client(tmp_path: Path) -> None:
    out_manifest = tmp_path / "sec_source_documents.csv"
    out, diag = build_sec_source_document_manifest(
        FakeSecClient(),
        tickers=["ACME"],
        out_manifest=out_manifest,
        docs_dir=tmp_path / "sec_docs",
        forms=("8-K",),
        item_filter="2.02",
        include_primary=True,
        include_exhibits=True,
        min_text_chars=5,
        overwrite=True,
    )
    assert diag.rows_written == 2
    assert len(out) == 2
    assert set(out["source_type"]) == {"sec_primary_filing", "sec_exhibit"}
    assert all(out["path"].astype(str).str.endswith(".txt"))
    docs = load_source_documents(out_manifest)
    assert len(docs) == 2
    assert any("reported revenue" in d.text for d in docs)
