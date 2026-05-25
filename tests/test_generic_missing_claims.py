from __future__ import annotations

import json

import pandas as pd

from mre.generic.missing_claims import build_missing_claim_recall_report, write_missing_claim_audit_template


def test_missing_claim_template_can_expand_events_and_fields(tmp_path):
    out = tmp_path / "missing_claims.csv"
    frame = write_missing_claim_audit_template(
        out,
        events=[{"event_id": "e1", "event_candidate_id": "ec1", "source_doc_id": "doc1"}],
        expected_fields=["impact_language", "data_exposure"],
    )

    assert out.exists()
    assert list(frame["expected_field"]) == ["impact_language", "data_exposure"]
    assert set(frame["review_status"]) == {"needs_review"}
    loaded = pd.read_csv(out)
    assert len(loaded) == 2


def test_missing_claim_recall_report_counts_expected_missing_claims(tmp_path):
    claims = [
        {"claim_id": "c1", "field_name": "impact_language", "review_status": "human_reviewed"},
        {"claim_id": "c2", "field_name": "impact_language", "review_status": "rejected"},
        {"claim_id": "c3", "field_name": "data_exposure", "review_status": "machine_high_confidence"},
        {"claim_id": "c4", "field_name": "vendor_involved", "review_status": "needs_review"},
    ]
    audit = [
        {
            "source_doc_id": "doc1",
            "event_id": "e1",
            "event_candidate_id": "",
            "expected_field": "impact_language",
            "expected_value": "yes",
            "evidence_text": "Impact language was present.",
            "review_status": "human_reviewed",
            "missed_reason": "pattern_gap",
            "reviewer_notes": "",
        },
        {
            "source_doc_id": "doc1",
            "event_id": "e1",
            "event_candidate_id": "",
            "expected_field": "data_exposure",
            "expected_value": "yes",
            "evidence_text": "Data exposure language was present.",
            "review_status": "rejected",
            "missed_reason": "not_really_missing",
            "reviewer_notes": "",
        },
    ]
    out_json = tmp_path / "recall.json"
    out_md = tmp_path / "recall.md"

    report = build_missing_claim_recall_report(
        claims=claims,
        missing_claim_audit=audit,
        out_json=out_json,
        out_md=out_md,
    )

    assert report["total_extracted_accepted_claims"] == 2
    assert report["total_expected_missing_claims"] == 1
    assert report["overall_estimated_recall"] == 2 / 3
    assert report["field_recall"] == [
        {
            "field_name": "data_exposure",
            "extracted_accepted_count": 1,
            "expected_missing_count": 0,
            "estimated_recall": 1.0,
        },
        {
            "field_name": "impact_language",
            "extracted_accepted_count": 1,
            "expected_missing_count": 1,
            "estimated_recall": 0.5,
        },
    ]
    assert "Field Recall" in out_md.read_text(encoding="utf-8")
    json.loads(out_json.read_text(encoding="utf-8"))


def test_missing_claim_recall_report_uses_review_queue_overrides():
    report = build_missing_claim_recall_report(
        claims=[{"claim_id": "c1", "field_name": "field", "review_status": "needs_review"}],
        review_queue=[{"claim_id": "c1", "review_status": "human_reviewed"}],
        missing_claim_audit=[
            {
                "source_doc_id": "doc1",
                "event_id": "e1",
                "event_candidate_id": "",
                "expected_field": "field",
                "expected_value": "yes",
                "evidence_text": "Missed evidence.",
                "review_status": "needs_review",
                "missed_reason": "pattern_gap",
                "reviewer_notes": "",
            }
        ],
    )

    assert report["total_extracted_accepted_claims"] == 1
    assert report["total_expected_missing_claims"] == 1
    assert report["overall_estimated_recall"] == 0.5
