from __future__ import annotations

import json
from pathlib import Path

import pytest

from mre.generic import (
    AssembledEvent,
    Claim,
    CompatibilityDimension,
    CompatibilityReport,
    EntityCandidate,
    EntityResolutionResult,
    EventCandidate,
    EvidenceSpan,
    ExtractionResult,
    IdentifierHint,
    NormalizedSourceDocument,
    PluginCompatibility,
    PluginManifest,
    RawSourceDocument,
    SourceQuery,
    SourceRecord,
    TemporalHint,
    TemporalResolutionResult,
    stable_id,
)


def test_stable_id_is_deterministic_and_json_stable():
    left = stable_id(
        "thing",
        {"b": 2, "a": [Path("alpha/beta"), {"z": "last"}]},
        ("x", "y"),
    )
    right = stable_id(
        "thing",
        {"a": [Path("alpha/beta"), {"z": "last"}], "b": 2},
        ["x", "y"],
    )

    assert left == right
    assert left.startswith("thing_")


def test_compatibility_report_serializes_and_rejects_invalid_scores():
    report = CompatibilityReport(
        plugin_name="toy_plugin",
        source_system="toy_source",
        event_family="toy_family",
        claim_schema="toy_schema",
        dimensions=[
            CompatibilityDimension(name="document_text_quality", score=0.9, basis="clean text"),
            CompatibilityDimension(name="evidence_addressability", score=0.8, basis="offsets"),
        ],
        readiness={"exploration": 0.95, "reviewed_dataset": 0.65},
        missing_capabilities=["human_review"],
        known_risks=["limited_sample"],
        metadata={"nested": {"ok": True}},
    )

    payload = report.to_dict()
    assert payload["dimensions"][0]["score"] == 0.9
    assert json.loads(json.dumps(payload))["plugin_name"] == "toy_plugin"

    with pytest.raises(ValueError):
        CompatibilityDimension(name="bad", score=1.1, basis="outside range")
    with pytest.raises(ValueError):
        CompatibilityReport(plugin_name="bad", readiness={"exploration": -0.1})


def test_source_contracts_are_json_serializable():
    query = SourceQuery(query_id="q1", source_system="toy_source", params={"topic": "sample"}, created_at="2026-01-01T00:00:00")
    record = SourceRecord(
        source_record_id="record1",
        source_system="toy_source",
        source_url="https://example.invalid/source",
        title="Toy notice",
        source_authority_level="official_regulator",
        source_role="canonical",
        entity_hints=[{"namespace": "registry:alpha", "value": "A-1"}],
    )
    raw = RawSourceDocument(source_record_id="record1", source_system="toy_source", raw_bytes_or_text=b"hello")
    normalized = NormalizedSourceDocument(
        source_doc_id="doc1",
        source_record_id="record1",
        source_system="toy_source",
        source_authority_level="official_company",
        source_role="canonical",
        text="Reportable event text.",
        entity_hints=[{"namespace": "domain:name", "value": "Toy Co"}],
        temporal_hints=[{"kind": "observed_at", "value": "2026-01-01"}],
    )

    for obj in (query, record, raw, normalized):
        json.dumps(obj.to_dict())


def test_identifier_hints_accept_arbitrary_namespaces():
    hint = IdentifierHint(namespace="registry:alpha", value="A-1", label="Alpha", confidence=0.8)
    alias = IdentifierHint(namespace="text:alias", value="A", confidence=0.4)
    candidate = EntityCandidate(
        entity_candidate_id="entity1",
        display_name="Alpha",
        identifiers=[hint, alias],
        confidence=0.75,
        resolution_status="candidate",
        basis="two hints",
    )
    result = EntityResolutionResult(source_doc_id="doc1", candidates=[candidate], unresolved_hints=[], overall_confidence=0.75)

    payload = result.to_dict()
    assert payload["candidates"][0]["identifiers"][0]["namespace"] == "registry:alpha"
    assert json.loads(json.dumps(payload))["overall_confidence"] == 0.75


def test_temporal_hints_accept_arbitrary_kinds():
    hint = TemporalHint(kind="observed_window_start", value="2026-01-01T12:00:00", confidence=0.7, basis="text phrase")
    result = TemporalResolutionResult(source_doc_id="doc1", hints=[hint], selected={"preferred": hint}, overall_confidence=0.7)

    payload = result.to_dict()
    assert payload["selected"]["preferred"]["kind"] == "observed_window_start"
    assert json.loads(json.dumps(payload))["hints"][0]["confidence"] == 0.7


def test_event_candidate_can_exist_without_resolved_entity():
    candidate = EventCandidate(
        event_candidate_id="cand1",
        event_family="toy_family",
        event_type="toy_type",
        event_subtype="toy_subtype",
        source_doc_id="doc1",
        detection_confidence=0.6,
        detection_method="toy_detector",
        evidence_span_id="span1",
    )
    assembled = AssembledEvent(
        event_id="event1",
        event_family="toy_family",
        event_type="toy_type",
        event_candidate_ids=["cand1"],
        source_doc_ids=["doc1"],
        entity_confidence=0.0,
        temporal_confidence=0.0,
    )

    assert candidate.to_dict()["entity_candidates"] == []
    assert assembled.to_dict()["entity_id"] == ""


def test_claim_and_extraction_result_serialize_nested_objects():
    event_candidate = EventCandidate(
        event_candidate_id="cand1",
        event_family="toy_family",
        event_type="toy_type",
        event_subtype="toy_subtype",
        source_doc_id="doc1",
        detection_confidence=0.7,
    )
    claim = Claim(
        claim_id="claim1",
        event_candidate_id="cand1",
        source_doc_id="doc1",
        field_name="impact_language",
        value="impact described",
        value_type="string",
        confidence=0.8,
        method="toy_regex",
        evidence_span_id="span1",
        claim_kind="allegation",
        claim_truth_status="asserted_by_source",
        source_authority_level="recognized_news",
        source_role="early_signal",
        compatibility_confidence=0.6,
    )
    span = EvidenceSpan(
        evidence_span_id="span1",
        source_doc_id="doc1",
        claim_id="claim1",
        evidence_text="impact described",
        start_char=0,
        end_char=16,
        source_url="https://example.invalid/doc",
    )
    result = ExtractionResult(
        source_doc_id="doc1",
        extractor_name="toy_extractor",
        claim_schema="toy_schema",
        claims=[claim],
        evidence_spans=[span],
        event_candidates=[event_candidate],
        diagnostics={"claims_total": 1},
    )

    payload = result.to_dict()
    assert payload["claims"][0]["claim_kind"] == "allegation"
    assert payload["claims"][0]["claim_truth_status"] == "asserted_by_source"
    assert json.loads(json.dumps(payload))["evidence_spans"][0]["start_char"] == 0


def test_plugin_manifest_serializes():
    manifest = PluginManifest(
        plugin_name="toy_plugin",
        plugin_version="0.1.0",
        plugin_kind="claim_extractor",
        supported_source_systems=["toy_source"],
        supported_event_families=["toy_family"],
        supported_claim_schemas=["toy_schema"],
        required_capabilities=["text"],
        optional_capabilities=["metadata"],
        known_risks=["toy_only"],
        output_contracts=["claims"],
    )
    compatibility = CompatibilityReport(plugin_name="toy_plugin", readiness={"exploration": 0.9})
    plugin_compatibility = PluginCompatibility(manifest=manifest, compatibility=compatibility)

    payload = plugin_compatibility.to_dict()
    assert payload["manifest"]["plugin_kind"] == "claim_extractor"
    assert json.loads(json.dumps(payload))["compatibility"]["readiness"]["exploration"] == 0.9
