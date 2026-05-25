from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mre.cli import main
from mre.cyber_8k_quality import build_cyber_8k_quality_report


def _write_quality_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "ACME",
                "timestamp_readiness_status": "ok",
                "event_review_status": "needs_review",
                "amended_later": True,
                "amendment_count": 1,
            },
            {
                "event_id": "E2",
                "ticker": "BETA",
                "timestamp_readiness_status": "warning",
                "event_review_status": "draft",
                "amended_later": False,
                "amendment_count": 0,
            },
        ]
    )
    claims = pd.DataFrame(
        [
            {"claim_id": "C1", "event_id": "E1", "field_name": "ransomware_mentioned", "confidence": 0.95, "evidence_span_id": "S1"},
            {"claim_id": "C2", "event_id": "E1", "field_name": "ransomware_mentioned", "confidence": 0.65, "evidence_span_id": "S2"},
            {"claim_id": "C3", "event_id": "E2", "field_name": "third_party_vendor_mentioned", "confidence": 0.88, "evidence_span_id": ""},
            {"claim_id": "C4", "event_id": "E2", "field_name": "impact_unknown_or_not_determined", "confidence": 0.9, "evidence_span_id": "S4"},
        ]
    )
    evidence = pd.DataFrame(
        [
            {"evidence_span_id": "S1", "claim_id": "C1", "evidence_text": "ransomware"},
            {"evidence_span_id": "S2", "claim_id": "C2", "evidence_text": "ransomware"},
            {"evidence_span_id": "S4", "claim_id": "C4", "evidence_text": "impact unknown"},
        ]
    )
    review = pd.DataFrame(
        [
            {"claim_id": "C1", "field_name": "ransomware_mentioned", "review_status": "reviewed", "evidence_present": True},
            {"claim_id": "C2", "field_name": "ransomware_mentioned", "review_status": "rejected", "evidence_present": True},
            {"claim_id": "C3", "field_name": "third_party_vendor_mentioned", "review_status": "needs_review", "evidence_present": False},
            {"claim_id": "C4", "field_name": "impact_unknown_or_not_determined", "review_status": "needs_review", "evidence_present": True},
        ]
    )
    paths = []
    for name, df in [("events", events), ("claims", claims), ("evidence", evidence), ("review", review)]:
        path = tmp_path / f"{name}.csv"
        df.to_csv(path, index=False)
        paths.append(path)
    return tuple(paths)  # type: ignore[return-value]


def test_build_cyber_8k_quality_report_counts_and_warnings(tmp_path: Path):
    events, claims, evidence, review = _write_quality_inputs(tmp_path)
    out_json = tmp_path / "quality.json"
    out_md = tmp_path / "quality.md"

    report = build_cyber_8k_quality_report(events, claims, evidence, review, out_json=out_json, out_md=out_md)

    assert report["n_events"] == 2
    assert report["n_companies"] == 2
    assert report["n_claims"] == 4
    assert report["n_reviewed_claims"] == 1
    assert report["n_rejected_claims"] == 1
    assert report["n_missing_evidence_claims"] == 1
    assert report["timestamp_readiness_status_counts"] == {"ok": 1, "warning": 1}
    assert report["amendment_coverage"]["events_amended_later"] == 1
    assert "low_review_coverage" in report["warnings"]
    assert "missing_evidence" in report["warnings"]
    assert "unknown_or_non_ok_timestamp_readiness" in report["warnings"]
    assert "high_rejection_rate_fields:ransomware_mentioned" in report["warnings"]
    assert json.loads(out_json.read_text(encoding="utf-8"))["n_claims"] == 4
    assert "Cyber 8-K Quality Report" in out_md.read_text(encoding="utf-8")


def test_cyber_8k_quality_report_cli_writes_outputs(tmp_path: Path):
    events, claims, evidence, review = _write_quality_inputs(tmp_path)
    out_json = tmp_path / "quality.json"
    out_md = tmp_path / "quality.md"

    main(
        [
            "cyber-8k-quality-report",
            "--events",
            str(events),
            "--claims",
            str(claims),
            "--evidence-spans",
            str(evidence),
            "--review-queue",
            str(review),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert json.loads(out_json.read_text(encoding="utf-8"))["n_events"] == 2
    assert out_md.exists()
