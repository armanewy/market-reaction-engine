from __future__ import annotations

import pandas as pd

from mre.claim_review import make_claim_review_queue


def _claims() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "claim_id": "c1",
                "event_id": "e1",
                "field_name": "ransomware_mentioned",
                "value": True,
                "value_type": "boolean",
                "confidence": 0.95,
                "method": "regex",
                "source_doc_id": "doc1",
                "evidence_span_id": "s1",
            },
            {
                "claim_id": "c2",
                "event_id": "e1",
                "field_name": "third_party_vendor_mentioned",
                "value": True,
                "value_type": "boolean",
                "confidence": 0.45,
                "method": "regex",
                "source_doc_id": "doc1",
                "evidence_span_id": "s2",
            },
            {
                "claim_id": "c3",
                "event_id": "e2",
                "field_name": "financial_impact_language",
                "value": "unknown",
                "value_type": "string",
                "confidence": 0.90,
                "method": "regex",
                "source_doc_id": "doc2",
                "evidence_span_id": "missing",
            },
        ]
    )


def _evidence() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "evidence_span_id": "s1",
                "source_doc_id": "doc1",
                "claim_id": "c1",
                "evidence_text": "The incident involved ransomware.",
            },
            {
                "evidence_span_id": "s2",
                "source_doc_id": "doc1",
                "claim_id": "c2",
                "evidence_text": "A third-party vendor was affected.",
            },
        ]
    )


def test_evidence_join_and_auto_accept_high_confidence():
    queue, diagnostics = make_claim_review_queue(_claims(), _evidence(), auto_accept_min_confidence=0.9)

    by_claim = queue.set_index("claim_id")
    assert by_claim.loc["c1", "review_status"] == "machine_high_confidence"
    assert by_claim.loc["c1", "label_quality"] == "machine_high_confidence"
    assert by_claim.loc["c2", "review_status"] == "needs_review"
    assert diagnostics["auto_reviewed"] == 1
    assert diagnostics["claims_with_evidence"] == 2


def test_missing_evidence_flagged():
    queue, diagnostics = make_claim_review_queue(_claims(), _evidence(), auto_accept_min_confidence=0.5)

    row = queue.set_index("claim_id").loc["c3"]

    assert row["evidence_present"] == False
    assert "missing_evidence" in row["issue_flags"]
    assert row["review_status"] == "needs_review"
    assert diagnostics["claims_missing_evidence"] == 1


def test_existing_review_statuses_preserved():
    claims = _claims()
    claims.loc[0, "review_status"] = "rejected"
    claims.loc[1, "review_status"] = "reviewed"

    queue, diagnostics = make_claim_review_queue(claims, _evidence(), auto_accept_min_confidence=0.1)
    by_claim = queue.set_index("claim_id")

    assert by_claim.loc["c1", "review_status"] == "rejected"
    assert by_claim.loc["c2", "review_status"] == "reviewed"
    assert diagnostics["rejected"] == 1


def test_csv_output_writes(tmp_path):
    out_path = tmp_path / "review_queue.csv"

    queue, _ = make_claim_review_queue(_claims(), _evidence(), out_path=out_path)

    assert out_path.exists()
    assert list(pd.read_csv(out_path).columns) == list(queue.columns)
