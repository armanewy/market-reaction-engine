from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mre.extraction import build_extraction_packets, facts_to_expectations, run_document_extraction, validate_llm_facts_jsonl
from mre.source_docs import load_source_documents, make_source_docs_template


def test_source_docs_manifest_reads_relative_path(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "release.txt").write_text("ACME revenue was $1.20 billion. EPS was $0.90.", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "doc1",
                "ticker": "acme",
                "event_id": "evt1",
                "event_time": "2024-01-31T16:10:00",
                "release_session": "after_close",
                "path": "docs/release.txt",
            }
        ],
    )
    docs = load_source_documents(manifest)
    assert len(docs) == 1
    assert docs[0].ticker == "ACME"
    assert "revenue" in docs[0].text
    assert docs[0].event_id == "evt1"


def test_run_document_extraction_produces_grounded_facts(tmp_path: Path) -> None:
    text = """ACME reported revenue of $2.45 billion. Diluted EPS was $1.14. Gross margin was 58.2%.
Analysts expected revenue of $2.37 billion and consensus EPS of $1.05.
For the next quarter, ACME expects revenue between $2.50 billion and $2.60 billion.
"""
    manifest = tmp_path / "manifest.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "doc1",
                "ticker": "ACME",
                "event_id": "evt1",
                "event_time": "2024-01-31T16:10:00",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "text": text,
            }
        ],
    )
    facts, expectations, events, diag = run_document_extraction(
        manifest,
        facts_out=tmp_path / "facts.csv",
        expectations_out=tmp_path / "expectations.csv",
        events_out=tmp_path / "events.csv",
    )
    assert diag.documents_total == 1
    assert diag.documents_with_facts == 1
    names = set(facts["fact_name"])
    assert {"actual_revenue", "actual_eps", "consensus_revenue", "consensus_eps", "guidance_revenue_low", "guidance_revenue_high"}.issubset(names)
    row = expectations.iloc[0]
    assert row["actual_revenue"] == 2450.0
    assert row["consensus_revenue"] == 2370.0
    assert row["actual_eps"] == 1.14
    assert row["consensus_eps"] == 1.05
    assert row["revenue_surprise_pct"] > 0
    assert events.iloc[0]["source_doc_id"] == "doc1"
    assert (tmp_path / "facts.csv").exists()


def test_facts_to_expectations_chooses_highest_confidence() -> None:
    facts = pd.DataFrame(
        [
            {"event_id": "evt", "ticker": "ACME", "event_time": "2024-01-01T16:00:00", "source_doc_id": "a", "fact_name": "actual_eps", "value": 1.0, "confidence": 0.2, "evidence_text": "weak", "source_url": ""},
            {"event_id": "evt", "ticker": "ACME", "event_time": "2024-01-01T16:00:00", "source_doc_id": "b", "fact_name": "actual_eps", "value": 1.2, "confidence": 0.9, "evidence_text": "strong", "source_url": ""},
            {"event_id": "evt", "ticker": "ACME", "event_time": "2024-01-01T16:00:00", "source_doc_id": "b", "fact_name": "consensus_eps", "value": 1.0, "confidence": 0.9, "evidence_text": "estimate", "source_url": ""},
        ]
    )
    out = facts_to_expectations(facts)
    assert out.iloc[0]["actual_eps"] == 1.2
    assert out.iloc[0]["eps_surprise_pct"] == pytest.approx(0.2)


def test_extraction_packets_and_validated_llm_facts(tmp_path: Path) -> None:
    text = "ACME reported revenue of $2.45 billion."
    manifest = tmp_path / "manifest.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "doc1",
                "ticker": "ACME",
                "event_id": "evt1",
                "event_time": "2024-01-31T16:10:00",
                "text": text,
            }
        ],
    )
    packet_path = tmp_path / "packets.jsonl"
    assert build_extraction_packets(manifest, packet_path, max_chars=1000) == 1
    packet = json.loads(packet_path.read_text(encoding="utf-8").splitlines()[0])
    assert packet["source_doc_id"] == "doc1"
    assert "actual_revenue" in packet["allowed_fact_names"]

    llm_path = tmp_path / "llm.jsonl"
    llm_path.write_text(
        json.dumps(
            {
                "source_doc_id": "doc1",
                "event_id": "evt1",
                "facts": [
                    {
                        "fact_name": "actual_revenue",
                        "value": 2450.0,
                        "unit": "usd_millions",
                        "evidence_text": "ACME reported revenue of $2.45 billion.",
                        "confidence": 0.9,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = validate_llm_facts_jsonl(manifest, llm_path, tmp_path / "facts.csv")
    assert len(out) == 1
    assert out.iloc[0]["start_char"] == 0
