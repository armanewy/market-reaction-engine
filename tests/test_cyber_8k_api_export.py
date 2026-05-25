from __future__ import annotations

import json

import pandas as pd

from mre.cyber_8k_api_export import export_cyber_8k_api


def test_export_cyber_8k_api_writes_nested_json_and_nulls(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "ACME",
                "cik": "123456",
                "company_name": "Acme Corp",
                "event_time": "2024-01-02T16:05:00",
                "summary": float("nan"),
                "ransomware_mentioned": True,
            }
        ]
    )
    claims = pd.DataFrame([{"claim_id": "C1", "event_id": "E1", "field_name": "ransomware_mentioned", "value": True}])
    evidence = pd.DataFrame([{"evidence_span_id": "S1", "claim_id": "C1", "evidence_text": "Ransomware affected systems."}])
    events_path = tmp_path / "events.csv"
    claims_path = tmp_path / "claims.csv"
    evidence_path = tmp_path / "evidence.csv"
    events.to_csv(events_path, index=False)
    claims.to_csv(claims_path, index=False)
    evidence.to_csv(evidence_path, index=False)

    outputs = export_cyber_8k_api(events_path, claims_path, evidence_path, tmp_path / "api")

    events_json = json.loads((tmp_path / "api" / "events.json").read_text(encoding="utf-8"))
    compact = json.loads((tmp_path / "api" / "events_compact.json").read_text(encoding="utf-8"))
    fields = json.loads((tmp_path / "api" / "fields_summary.json").read_text(encoding="utf-8"))
    assert events_json[0]["claims"][0]["evidence"][0]["evidence_text"] == "Ransomware affected systems."
    assert compact[0]["summary"] is None
    assert next(row for row in fields if row["field_name"] == "ransomware_mentioned")["count"] == 1
    assert set(outputs) == {"events", "claims", "evidence_spans", "events_compact", "companies", "fields_summary"}


def test_export_cyber_8k_api_can_omit_large_evidence_text(tmp_path):
    events = pd.DataFrame([{"event_id": "E1"}])
    claims = pd.DataFrame([{"claim_id": "C1", "event_id": "E1", "field_name": "item_105_flag", "value": True}])
    evidence = pd.DataFrame([{"evidence_span_id": "S1", "claim_id": "C1", "evidence_text": "long text"}])
    events_path = tmp_path / "events.csv"
    claims_path = tmp_path / "claims.csv"
    evidence_path = tmp_path / "evidence.csv"
    events.to_csv(events_path, index=False)
    claims.to_csv(claims_path, index=False)
    evidence.to_csv(evidence_path, index=False)

    export_cyber_8k_api(events_path, claims_path, evidence_path, tmp_path / "api", include_evidence=False)

    spans = json.loads((tmp_path / "api" / "evidence_spans.json").read_text(encoding="utf-8"))
    assert "evidence_text" not in spans[0]
