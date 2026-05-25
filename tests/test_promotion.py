from __future__ import annotations

import json

import pandas as pd

from mre.promotion import evaluate_model_readiness


def _events(n: int = 80, **overrides) -> pd.DataFrame:
    rows = []
    for i in range(n):
        row = {
            "event_id": f"e{i:03d}",
            "ticker": "AAA",
            "event_time": f"2024-01-{(i % 28) + 1:02d}T16:05:00",
            "event_type": "cybersecurity",
            "summary": "Material incident disclosed.",
            "review_status": "reviewed",
            "label_quality": "high",
            "evidence_status": "source_backed",
            "source_doc_ids": f"doc-{i}",
            "release_session": "after_close",
            "duplicate_status": "primary",
            "timestamp_audit_status": "clear",
            "execution_survivability_class": "delayed-digestion",
            "event_status": "ok",
            "corpus_validation_status": "ok",
        }
        row.update(overrides)
        rows.append(row)
    return pd.DataFrame(rows)


def test_model_ready_report_is_json_serializable():
    report = evaluate_model_readiness(_events())

    assert report["decision"] == "model_ready"
    assert report["failed_gates"] == []
    assert report["summary"]["n_model_eligible_rows"] == 80
    json.dumps(report)


def test_underpowered_corpus_is_monitor_only():
    report = evaluate_model_readiness(_events(20))

    assert report["decision"] == "monitor_only"
    assert "min_reviewed_rows" in report["failed_gates"]
    assert "min_model_eligible_rows" in report["failed_gates"]


def test_unknown_release_session_rejects_modeling():
    report = evaluate_model_readiness(_events(release_session="unknown"))

    assert report["decision"] == "reject_modeling"
    assert "known_release_session" in report["failed_gates"]
    assert report["summary"]["n_model_eligible_rows"] == 0


def test_missing_evidence_rejects_modeling():
    report = evaluate_model_readiness(_events(evidence_status="missing", source_doc_ids=""))

    assert report["decision"] == "reject_modeling"
    assert "evidence" in report["failed_gates"]
    assert report["summary"]["n_model_eligible_rows"] == 0


def test_duplicate_and_timestamp_risk_rows_reject_modeling():
    frame = _events()
    frame.loc[0, "duplicate_status"] = "duplicate"
    frame.loc[1, "timestamp_audit_status"] = "needs_timestamp_review"

    report = evaluate_model_readiness(frame)

    assert report["decision"] == "reject_modeling"
    assert "duplicate_status" in report["failed_gates"]
    assert "timestamp_audit" in report["failed_gates"]


def test_absent_optional_audit_columns_warn_without_crashing():
    frame = _events().drop(columns=["duplicate_status", "timestamp_audit_status", "execution_survivability_class"])

    report = evaluate_model_readiness(frame)

    assert report["decision"] == "needs_review"
    assert report["failed_gates"] == []
    assert report["warnings"]
