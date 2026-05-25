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
    assert "machine_high_confidence" in event_html
    assert "<mark>" not in event_html


def test_static_site_uses_review_queue_statuses_and_escapes_notes(tmp_path: Path):
    events = pd.DataFrame([{"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02T16:05:00", "summary": "Cyber event"}])
    claims = pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "event_id": "E1",
                "field_name": "ransomware_mentioned",
                "value": True,
                "confidence": 0.95,
                "review_status": "needs_review",
                "label_quality": "",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S1",
            },
            {
                "claim_id": "C2",
                "event_id": "E1",
                "field_name": "third_party_vendor_mentioned",
                "value": True,
                "confidence": 0.91,
                "review_status": "needs_review",
                "label_quality": "",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S2",
            },
            {
                "claim_id": "C3",
                "event_id": "E1",
                "field_name": "customer_data_exposure_mentioned",
                "value": True,
                "confidence": 0.55,
                "review_status": "needs_review",
                "label_quality": "",
                "method": "regex",
                "source_doc_id": "D1",
                "evidence_span_id": "S3",
            },
        ]
    )
    evidence = pd.DataFrame(
        [
            {"evidence_span_id": "S1", "source_doc_id": "D1", "claim_id": "C1", "evidence_text": "ransomware"},
            {"evidence_span_id": "S2", "source_doc_id": "D1", "claim_id": "C2", "evidence_text": "vendor"},
            {"evidence_span_id": "S3", "source_doc_id": "D1", "claim_id": "C3", "evidence_text": "customer data"},
        ]
    )
    review_queue = pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "review_status": "human_reviewed",
                "label_quality": "human_reviewed",
                "reviewer_notes": "safe <b>note</b>",
            },
            {
                "claim_id": "C2",
                "review_status": "machine_high_confidence",
                "label_quality": "machine_high_confidence",
                "reviewer_notes": "",
            },
            {
                "claim_id": "C3",
                "review_status": "rejected",
                "label_quality": "human_reviewed",
                "reviewer_notes": "false positive",
            },
        ]
    )
    paths = {}
    for name, df in [("events", events), ("claims", claims), ("evidence", evidence), ("review_queue", review_queue)]:
        path = tmp_path / f"{name}.csv"
        df.to_csv(path, index=False)
        paths[name] = path

    build_cyber_8k_static_site(
        paths["events"],
        paths["claims"],
        paths["evidence"],
        tmp_path / "site",
        review_queue_csv=paths["review_queue"],
    )

    event_html = (tmp_path / "site" / "event" / "E1.html").read_text(encoding="utf-8")
    claims_json = json.loads((tmp_path / "site" / "api" / "claims.json").read_text(encoding="utf-8"))
    statuses = {row["claim_id"]: row["review_status"] for row in claims_json}
    assert statuses == {"C1": "human_reviewed", "C2": "machine_high_confidence", "C3": "rejected"}
    assert {row["claim_id"]: row["reviewer_notes"] for row in claims_json}["C1"] == "safe <b>note</b>"
    assert "human_reviewed" in event_html
    assert "machine_high_confidence" in event_html
    assert "rejected" in event_html
