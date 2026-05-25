from __future__ import annotations

import pandas as pd

from mre.cyber_8k_digest import build_cyber_8k_digest


def test_build_cyber_8k_digest_filters_and_writes(tmp_path):
    events = pd.DataFrame(
        [
            {"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02", "summary": "Cyber incident", "amendment_flag": False},
            {"event_id": "E2", "ticker": "BETA", "event_time": "2024-02-02", "summary": "Outside range", "amendment_flag": True},
        ]
    )
    claims = pd.DataFrame(
        [
            {"claim_id": "C1", "event_id": "E1", "field_name": "operational_disruption_mentioned", "review_status": "reviewed"},
            {"claim_id": "C2", "event_id": "E2", "field_name": "third_party_vendor_mentioned", "review_status": "needs_review"},
        ]
    )
    evidence = pd.DataFrame([{"claim_id": "C1", "field_name": "operational_disruption_mentioned", "evidence_text": "Operations were disrupted.", "source_url": "https://sec.test/acme"}])
    events_path = tmp_path / "events.csv"
    claims_path = tmp_path / "claims.csv"
    evidence_path = tmp_path / "evidence.csv"
    events.to_csv(events_path, index=False)
    claims.to_csv(claims_path, index=False)
    evidence.to_csv(evidence_path, index=False)

    digest = build_cyber_8k_digest(events_path, claims_path, evidence_path, start_date="2024-01-01", end_date="2024-01-31", out_path=tmp_path / "digest.md")

    assert "Cyber 8-K Watch Digest" in digest
    assert "new events: 1" in digest
    assert "operational_disruption_mentioned" in digest
    assert "Operations were disrupted." in digest
    assert "Outside range" not in digest
    assert (tmp_path / "digest.md").exists()


def test_build_cyber_8k_digest_empty_period():
    events = pd.DataFrame([{"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02"}])
    claims = pd.DataFrame(columns=["claim_id", "event_id", "field_name", "review_status"])
    evidence = pd.DataFrame(columns=["claim_id", "field_name", "evidence_text"])

    digest = build_cyber_8k_digest(events, claims, evidence, start_date="2025-01-01", end_date="2025-01-31")

    assert "new events: 0" in digest
    assert "No Cyber 8-K events found" in digest
