from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mre.cyber_8k_site import build_cyber_8k_static_site, evidence_highlight_html


def test_build_cyber_8k_static_site_outputs_html_and_json(tmp_path: Path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "ACME",
                "cik": "123456",
                "company_name": "Acme <Corp>",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
                "summary": "Item 1.05 disclosure",
                "form": "8-K",
                "accession": "0000123456-24-000001",
                "source_url": "https://sec.test/acme",
            }
        ]
    )
    claims = pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "event_id": "E1",
                "field_name": "ransomware_mentioned",
                "value": True,
                "confidence": 0.95,
                "review_status": "reviewed",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S1",
            }
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "evidence_span_id": "S1",
                "source_doc_id": "D1",
                "claim_id": "C1",
                "evidence_text": "Ransomware <script>alert(1)</script> affected systems.",
                "start_char": 8,
                "end_char": 62,
                "source_text": "Notice: Ransomware <script>alert(1)</script> affected systems. More text.",
                "source_url": "https://sec.test/acme",
            }
        ]
    )
    events_csv = tmp_path / "events.csv"
    claims_csv = tmp_path / "claims.csv"
    evidence_csv = tmp_path / "evidence.csv"
    events.to_csv(events_csv, index=False)
    claims.to_csv(claims_csv, index=False)
    evidence.to_csv(evidence_csv, index=False)

    result = build_cyber_8k_static_site(events_csv, claims_csv, evidence_csv, tmp_path / "site")

    assert Path(result["index"]).exists()
    assert (tmp_path / "site" / "events.html").exists()
    assert (tmp_path / "site" / "event" / "E1.html").exists()
    assert (tmp_path / "site" / "company" / "ACME.html").exists()
    event_html = (tmp_path / "site" / "event" / "E1.html").read_text(encoding="utf-8")
    assert "ransomware_mentioned" in event_html
    assert "<mark>Ransomware &lt;script&gt;alert(1)&lt;/script&gt; affected systems.</mark>" in event_html
    assert "<script>alert(1)</script>" not in event_html
    assert json.loads((tmp_path / "site" / "api" / "events.json").read_text(encoding="utf-8"))[0]["event_id"] == "E1"
    assert json.loads((tmp_path / "site" / "api" / "claims.json").read_text(encoding="utf-8"))[0]["claim_id"] == "C1"
    assert json.loads((tmp_path / "site" / "api" / "evidence_spans.json").read_text(encoding="utf-8"))[0]["evidence_span_id"] == "S1"


def test_evidence_highlight_html_escapes_and_handles_bad_offsets():
    source = "Before <b>important</b> after"

    highlighted = evidence_highlight_html(source, 7, 23)

    assert highlighted == "Before <mark>&lt;b&gt;important&lt;/b&gt;</mark> after"
    assert evidence_highlight_html(source, 100, 110) == ""


def test_static_site_highlights_source_text_loaded_from_manifest_path(tmp_path: Path):
    source_text = "Intro. Ransomware <b>affected</b> operations. Outro."
    start = source_text.index("Ransomware")
    end = source_text.index(" operations") + len(" operations")
    doc_path = tmp_path / "docs" / "d1.txt"
    doc_path.parent.mkdir()
    doc_path.write_text(source_text, encoding="utf-8")
    source_documents = pd.DataFrame(
        [
            {
                "source_doc_id": "D1",
                "ticker": "ACME",
                "event_time": "2024-01-02T16:05:00",
                "path": "docs/d1.txt",
            }
        ]
    )
    events = pd.DataFrame([{"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02T16:05:00", "summary": "Cyber event"}])
    claims = pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "event_id": "E1",
                "field_name": "ransomware_mentioned",
                "value": True,
                "confidence": 0.95,
                "review_status": "machine_high_confidence",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S1",
            }
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "evidence_span_id": "S1",
                "source_doc_id": "D1",
                "claim_id": "C1",
                "evidence_text": "Ransomware <b>affected</b> operations",
                "start_char": start,
                "end_char": end,
            }
        ]
    )
    paths = {}
    for name, df in [("source_documents", source_documents), ("events", events), ("claims", claims), ("evidence", evidence)]:
        path = tmp_path / f"{name}.csv"
        df.to_csv(path, index=False)
        paths[name] = path

    build_cyber_8k_static_site(
        paths["events"],
        paths["claims"],
        paths["evidence"],
        tmp_path / "site",
        source_documents_csv=paths["source_documents"],
    )

    event_html = (tmp_path / "site" / "event" / "E1.html").read_text(encoding="utf-8")
    assert "<mark>Ransomware &lt;b&gt;affected&lt;/b&gt; operations</mark>" in event_html
    assert "<b>affected</b>" not in event_html


def test_static_site_falls_back_to_evidence_text_without_source_text(tmp_path: Path):
    events = pd.DataFrame([{"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02T16:05:00", "summary": "Cyber event"}])
    claims = pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "event_id": "E1",
                "field_name": "ransomware_mentioned",
                "value": True,
                "confidence": 0.95,
                "review_status": "machine_high_confidence",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S1",
            }
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "evidence_span_id": "S1",
                "source_doc_id": "D1",
                "claim_id": "C1",
                "evidence_text": "Ransomware <b>affected</b> operations",
                "start_char": 0,
                "end_char": 10,
            }
        ]
    )
    paths = {}
    for name, df in [("events", events), ("claims", claims), ("evidence", evidence)]:
        path = tmp_path / f"{name}.csv"
        df.to_csv(path, index=False)
        paths[name] = path

    build_cyber_8k_static_site(paths["events"], paths["claims"], paths["evidence"], tmp_path / "site")

    event_html = (tmp_path / "site" / "event" / "E1.html").read_text(encoding="utf-8")
    assert "Ransomware &lt;b&gt;affected&lt;/b&gt; operations" in event_html
    assert "<mark>" not in event_html
