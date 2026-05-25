from __future__ import annotations

import json

from mre.event_graph import (
    Claim,
    EvidenceSpan,
    Event,
    claim_id,
    dataclasses_to_frame,
    evidence_span_id,
    frame_to_claims,
    frame_to_evidence_spans,
    read_csv,
    stable_id,
    write_csv,
)


def test_stable_ids_are_deterministic_and_offsets_matter():
    assert stable_id("event", "ABC", "2024-01-01") == stable_id("event", "ABC", "2024-01-01")
    assert claim_id("E1", "ransomware_mentioned", "ransomware") != claim_id("E1", "vendor", "ransomware")
    assert evidence_span_id("doc1", 10, 20) != evidence_span_id("doc1", 10, 21)


def test_dataclass_to_dict_is_json_serializable():
    event = Event(
        event_id="E1",
        issuer_id="issuer_abc",
        filing_id="filing_abc",
        event_type="cybersecurity",
        summary="Item 1.05 disclosure",
    )

    payload = event.to_dict()

    assert payload["release_session"] == "unknown"
    json.dumps(payload)


def test_claims_and_evidence_round_trip_through_csv(tmp_path):
    claim = Claim(
        claim_id="claim1",
        event_id="event1",
        field_name="ransomware_mentioned",
        value=True,
        value_type="boolean",
        confidence=0.91,
        method="regex",
        evidence_span_id="span1",
        source_doc_id="doc1",
    )
    span = EvidenceSpan(
        evidence_span_id="span1",
        source_doc_id="doc1",
        claim_id="claim1",
        evidence_text="The incident involved ransomware.",
        start_char=12,
        end_char=41,
        source_url="https://sec.test/doc",
    )

    claims_path = tmp_path / "claims.csv"
    spans_path = tmp_path / "spans.csv"
    write_csv(claims_path, [claim])
    write_csv(spans_path, [span])

    claims = read_csv(claims_path, "claims")
    spans = read_csv(spans_path, "evidence_spans")

    assert claims[0].field_name == "ransomware_mentioned"
    assert frame_to_claims(dataclasses_to_frame([claim]))[0].claim_id == "claim1"
    assert spans[0].evidence_text == "The incident involved ransomware."
    assert frame_to_evidence_spans(dataclasses_to_frame([span]))[0].end_char == 41


def test_missing_optional_values_do_not_crash():
    frame = dataclasses_to_frame(
        [
            {
                "claim_id": "claim1",
                "event_id": "event1",
                "field_name": "materiality_language",
                "value": "material",
            }
        ]
    )

    claim = frame_to_claims(frame)[0]

    assert claim.value_type == "string"
    assert claim.source_doc_id == ""
