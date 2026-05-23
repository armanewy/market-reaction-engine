from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.ingestion import build_sec_source_document_manifest, html_to_text, ingest_source_document_manifest
from mre.source_docs import load_source_documents, make_source_docs_template


def test_html_to_text_strips_script_and_preserves_visible_text():
    text = html_to_text("""
        <html><head><style>.x{}</style><script>bad()</script></head>
        <body><h1>Quarterly Results</h1><p>Revenue was $2.4 billion.</p></body></html>
    """)
    assert "Quarterly Results" in text
    assert "Revenue was $2.4 billion" in text
    assert "bad()" not in text
    assert ".x" not in text


def test_ingest_source_document_manifest_local_html(tmp_path: Path):
    raw = tmp_path / "raw.html"
    raw.write_text("<html><body><p>ACME reported revenue of $2.4 billion.</p></body></html>", encoding="utf-8")
    manifest = tmp_path / "sources.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "ACME_Q1",
                "ticker": "ACME",
                "event_id": "ACME_2024Q1",
                "event_time": "2024-04-25T16:05:00",
                "event_type": "earnings",
                "event_subtype": "earnings_release",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "path": raw.name,
            }
        ],
    )
    out_manifest = tmp_path / "source_documents.csv"
    docs_dir = tmp_path / "docs"
    out, diag = ingest_source_document_manifest(manifest, out_manifest, docs_dir, overwrite=True)

    assert diag.rows_written == 1
    assert diag.local_files_read == 1
    assert len(out) == 1
    written_path = tmp_path / out.iloc[0]["path"]
    assert written_path.exists()
    assert "ACME reported revenue" in written_path.read_text(encoding="utf-8")
    docs = load_source_documents(out_manifest)
    assert docs[0].text.startswith("ACME reported")


class FakeSecClient:
    def recent_filings(self, ticker, forms=None):
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "company_name": "Acme Corp",
                    "cik": 123456,
                    "form": "8-K",
                    "filingDate": "2024-04-25",
                    "acceptanceDateTime": "2024-04-25T16:05:00",
                    "accessionNumber": "0000123456-24-000001",
                    "primaryDocument": "form8k.htm",
                    "items": "2.02",
                }
            ]
        )

    def filing_documents(self, filing_row, *, include_primary=True, include_exhibits=True, exhibit_pattern=""):
        return [
            {"name": "form8k.htm", "url": "https://sec.test/form8k.htm", "is_primary": True},
            {"name": "ex99-1.htm", "url": "https://sec.test/ex99-1.htm", "is_exhibit": True},
        ]

    def filing_document_url(self, cik, accession, document_name):
        return f"https://sec.test/{document_name}"

    def fetch_document_text(self, url):
        if url.endswith("ex99-1.htm"):
            return ("<html><body><p>Acme reported revenue of $2.4 billion and EPS of $1.25.</p></body></html>", "text/html")
        return ("<html><body><p>Item 2.02 Results of Operations and Financial Condition.</p></body></html>", "text/html")


def test_build_sec_source_document_manifest_with_fake_client(tmp_path: Path):
    out_manifest = tmp_path / "sec_source_documents.csv"
    docs_dir = tmp_path / "sec_docs"
    df, diag = build_sec_source_document_manifest(
        FakeSecClient(),
        ["ACME"],
        out_manifest,
        docs_dir,
        sector_benchmark="XLK",
        limit_per_ticker=1,
        overwrite=True,
    )

    assert diag.rows_written == 2
    assert len(df) == 2
    assert set(df["source_type"]) == {"sec_primary_filing", "sec_exhibit"}
    assert (tmp_path / df.iloc[1]["path"]).exists()
    assert "Acme reported revenue" in (tmp_path / df.iloc[1]["path"]).read_text(encoding="utf-8")
    docs = load_source_documents(out_manifest)
    assert len(docs) == 2
    assert docs[0].release_session == "after_close"
