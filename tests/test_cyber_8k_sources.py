from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.cyber_8k_sources import build_cyber_8k_source_documents
from mre.source_docs import load_source_documents


class FakeCyberSecClient:
    def recent_filings(self, ticker, forms=None):
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "company_name": "Acme Corp",
                    "cik": 123456,
                    "form": "8-K",
                    "filingDate": "2024-01-02",
                    "acceptanceDateTime": "2024-01-02T16:05:00",
                    "accessionNumber": "0000123456-24-000001",
                    "primaryDocument": "cyber-primary.htm",
                    "items": "1.05",
                },
                {
                    "ticker": ticker,
                    "company_name": "Acme Corp",
                    "cik": 123456,
                    "form": "8-K/A",
                    "filingDate": "2024-01-04",
                    "acceptanceDateTime": "2024-01-04T08:05:00",
                    "accessionNumber": "0000123456-24-000002",
                    "primaryDocument": "cyber-amendment.htm",
                    "items": "1.05",
                },
                {
                    "ticker": ticker,
                    "company_name": "Acme Corp",
                    "cik": 123456,
                    "form": "8-K",
                    "filingDate": "2024-01-05",
                    "acceptanceDateTime": "2024-01-05T12:05:00",
                    "accessionNumber": "0000123456-24-000003",
                    "primaryDocument": "executive-change.htm",
                    "items": "5.02",
                },
                {
                    "ticker": ticker,
                    "company_name": "Acme Corp",
                    "cik": 123456,
                    "form": "8-K",
                    "filingDate": "2024-01-06",
                    "acceptanceDateTime": "2024-01-06T16:30:00",
                    "accessionNumber": "0000123456-24-000004",
                    "primaryDocument": "missing-item.htm",
                    "items": "",
                },
            ]
        )

    def filing_documents(self, filing_row, *, include_primary=True, include_exhibits=True, exhibit_pattern=""):
        primary = str(filing_row["primaryDocument"])
        out = []
        if include_primary:
            out.append({"name": primary, "url": f"https://sec.test/{primary}", "is_primary": True})
        if include_exhibits and primary == "cyber-primary.htm":
            out.append({"name": "ex99-cyber.htm", "url": "https://sec.test/ex99-cyber.htm", "is_exhibit": True})
        return out

    def filing_document_url(self, cik, accession, document_name):
        return f"https://sec.test/{document_name}"

    def fetch_document_text(self, url):
        mapping = {
            "https://sec.test/cyber-primary.htm": "<html><body><p>Item 1.05 Material Cybersecurity Incident. Acme identified a cyber incident affecting operations.</p></body></html>",
            "https://sec.test/ex99-cyber.htm": "<html><body><p>Item 1.05 update. Acme continues to investigate the cybersecurity incident.</p></body></html>",
            "https://sec.test/cyber-amendment.htm": "<html><body><p>Item 1.05 Material Cybersecurity Incident amendment. Acme provides an update.</p></body></html>",
            "https://sec.test/executive-change.htm": "<html><body><p>Item 5.02 Departure of Directors or Certain Officers.</p></body></html>",
            "https://sec.test/missing-item.htm": "<html><body><p>Item 1.05 Material Cybersecurity Incident. Item metadata was missing from submissions.</p></body></html>",
        }
        return mapping[url], "text/html"


def test_build_cyber_8k_source_documents_filters_and_writes_manifest(tmp_path: Path):
    out_manifest = tmp_path / "source_documents.csv"
    docs_dir = tmp_path / "docs"

    df, diagnostics = build_cyber_8k_source_documents(
        FakeCyberSecClient(),
        tickers=["ACME"],
        out_manifest=out_manifest,
        docs_dir=docs_dir,
        overwrite=True,
        min_text_chars=20,
    )

    assert diagnostics.tickers_total == 1
    assert diagnostics.filings_seen == 4
    assert diagnostics.filings_kept == 3
    assert diagnostics.docs_written == 4
    assert diagnostics.skipped_reasons["non item 1.05 filing"] == 1
    assert set(df["form"]) == {"8-K", "8-K/A"}
    assert "0000123456-24-000003" not in set(df["accession"])
    assert "document_text_item_105" in set(df["source_confidence"])
    assert out_manifest.exists()

    for rel_path in df["path"]:
        path = tmp_path / rel_path
        assert path.exists()
        assert "Item 1.05" in path.read_text(encoding="utf-8")

    docs = load_source_documents(out_manifest)
    assert len(docs) == 4
    assert docs[0].event_type == "cybersecurity"
    assert docs[0].release_session == "after_close"
