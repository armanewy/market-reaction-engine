from __future__ import annotations

import pandas as pd

from mre.disclosure_similarity import find_similar_events, peer_field_benchmark


def _frames():
    events = pd.DataFrame(
        [
            {"event_id": "E1", "ticker": "AAA", "sector": "tech", "summary": "ransomware disrupted operations", "event_time": "2024-01-01"},
            {"event_id": "E2", "ticker": "BBB", "sector": "tech", "summary": "ransomware affected systems", "event_time": "2024-01-02"},
            {"event_id": "E3", "ticker": "AAA", "sector": "tech", "summary": "same issuer similar ransomware", "event_time": "2024-01-03"},
            {"event_id": "E4", "ticker": "CCC", "sector": "retail", "summary": "routine executive appointment", "event_time": "2024-01-04"},
        ]
    )
    claims = pd.DataFrame(
        [
            {"claim_id": "C1", "event_id": "E1", "field_name": "ransomware_mentioned", "value": True},
            {"claim_id": "C2", "event_id": "E2", "field_name": "ransomware_mentioned", "value": True},
            {"claim_id": "C3", "event_id": "E2", "field_name": "operational_disruption_mentioned", "value": True},
            {"claim_id": "C4", "event_id": "E4", "field_name": "third_party_vendor_mentioned", "value": True},
        ]
    )
    evidence = pd.DataFrame(
        [
            {"claim_id": "C2", "evidence_text": "Ransomware affected systems and interrupted operations."},
            {"claim_id": "C4", "evidence_text": "The vendor notice was unrelated."},
        ]
    )
    return events, claims, evidence


def test_find_similar_events_ranks_expected_and_excludes_same_issuer():
    events, claims, evidence = _frames()

    result = find_similar_events(events, claims, evidence, "E1", k=2, exclude_same_issuer=True)

    assert result.iloc[0]["event_id"] == "E2"
    assert "Ransomware affected systems" in result.iloc[0]["evidence_preview"]
    assert "E3" not in set(result["event_id"])


def test_peer_field_benchmark_computes_group_rates():
    events, claims, _ = _frames()

    report = peer_field_benchmark(events, claims, group_col="sector")
    tech = report.set_index("sector").loc["tech"]

    assert tech["n_events"] == 3
    assert tech["ransomware_mentioned_count"] == 2
    assert tech["ransomware_mentioned_rate"] == 2 / 3
