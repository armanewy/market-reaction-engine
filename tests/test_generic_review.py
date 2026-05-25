from __future__ import annotations

import pandas as pd

from mre.generic.review import make_generic_claim_review_queue


def test_generic_review_queue_flags_missing_evidence_and_auto_accepts(tmp_path):
    claims = pd.DataFrame(
        [
            {
                "claim_id": "c1",
                "event_id": "e1",
                "field_name": "impact_language",
                "value": "impact",
                "value_type": "string",
                "confidence": 0.95,
                "method": "toy",
                "source_doc_id": "doc1",
                "source_system": "toy_source",
                "source_authority_level": "official_regulator",
                "source_role": "canonical",
                "claim_kind": "source_assertion",
                "claim_truth_status": "asserted_by_source",
                "evidence_span_id": "s1",
            },
            {
                "claim_id": "c2",
                "event_id": "e1",
                "field_name": "weak_claim",
                "value": "maybe",
                "value_type": "string",
                "confidence": 0.4,
                "method": "toy",
                "source_doc_id": "doc1",
                "evidence_span_id": "missing",
            },
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "evidence_span_id": "s1",
                "source_doc_id": "doc1",
                "claim_id": "c1",
                "evidence_text": "impact",
            }
        ]
    )

    queue, diagnostics = make_generic_claim_review_queue(
        claims,
        evidence,
        out_path=tmp_path / "queue.csv",
        auto_accept_min_confidence=0.9,
    )

    by_id = queue.set_index("claim_id")
    assert by_id.loc["c1", "review_status"] == "machine_high_confidence"
    assert by_id.loc["c1", "source_role"] == "canonical"
    assert by_id.loc["c2", "review_status"] == "needs_review"
    assert by_id.loc["c2", "issue_flags"] == "missing_evidence"
    assert diagnostics["claims_with_evidence"] == 1
    assert diagnostics["claims_missing_evidence"] == 1
    assert (tmp_path / "queue.csv").exists()


def test_generic_review_queue_preserves_human_and_rejected_statuses():
    claims = pd.DataFrame(
        [
            {"claim_id": "c1", "source_doc_id": "doc1", "evidence_span_id": "s1", "confidence": 0.99, "review_status": "human_reviewed"},
            {"claim_id": "c2", "source_doc_id": "doc1", "evidence_span_id": "s2", "confidence": 0.99, "review_status": "rejected"},
        ]
    )
    evidence = pd.DataFrame(
        [
            {"claim_id": "c1", "source_doc_id": "doc1", "evidence_span_id": "s1", "evidence_text": "one"},
            {"claim_id": "c2", "source_doc_id": "doc1", "evidence_span_id": "s2", "evidence_text": "two"},
        ]
    )

    queue, diagnostics = make_generic_claim_review_queue(claims, evidence, auto_accept_min_confidence=0.9)

    assert list(queue["review_status"]) == ["human_reviewed", "rejected"]
    assert diagnostics["machine_high_confidence"] == 0
    assert diagnostics["rejected"] == 1
