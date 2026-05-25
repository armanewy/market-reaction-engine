from __future__ import annotations

import json

import pytest

from mre.generic.compatibility import CompatibilityDimension, CompatibilityReport
from mre.generic.compatibility_eval import (
    attach_readiness,
    derive_readiness,
    dimension_notes,
    dimension_score,
    readiness_band,
    summarize_compatibility,
    weighted_score,
)


def _report(dimensions: dict[str, float]) -> CompatibilityReport:
    return CompatibilityReport(
        plugin_name="toy_plugin",
        source_system="toy_source",
        event_family="toy_family",
        claim_schema="toy_schema",
        dimensions=[
            CompatibilityDimension(name=name, score=score, basis=f"{name} basis", notes=f"{name} note")
            for name, score in dimensions.items()
        ],
        missing_capabilities=["manual_review"],
        known_risks=["toy_only"],
    )


def test_dimension_helpers_and_weighted_score():
    report = _report({"document_text_quality": 0.8, "evidence_addressability": 0.6})

    assert dimension_score(report, "document_text_quality") == 0.8
    assert dimension_score(report, "missing", default=0.25) == 0.25
    assert dimension_notes(report, "evidence_addressability") == [
        "evidence_addressability basis",
        "evidence_addressability note",
    ]
    assert weighted_score(report, {"document_text_quality": 1, "missing": 1}) == 0.4
    assert weighted_score(report, {"missing": 1}, default=0.2) == 0.2


def test_readiness_routes_strong_and_weak_reports():
    strong = _report(
        {
            "source_identity_confidence": 0.9,
            "source_authority_confidence": 0.95,
            "document_text_quality": 0.95,
            "evidence_addressability": 0.9,
            "metadata_completeness": 0.9,
            "temporal_resolution_confidence": 0.85,
            "entity_hint_quality": 0.85,
            "entity_resolution_confidence": 0.85,
            "event_detection_confidence": 0.9,
            "claim_schema_alignment": 0.9,
            "claim_extraction_confidence": 0.9,
            "reviewability": 0.85,
            "provenance_completeness": 0.9,
            "reproducibility": 0.8,
            "jurisdiction_support": 0.9,
            "language_support": 1.0,
        }
    )
    weak = _report(
        {
            "source_identity_confidence": 0.7,
            "source_authority_confidence": 0.2,
            "document_text_quality": 0.9,
            "evidence_addressability": 0.3,
            "event_detection_confidence": 0.8,
            "claim_schema_alignment": 0.7,
            "claim_extraction_confidence": 0.8,
            "reviewability": 0.3,
            "provenance_completeness": 0.2,
            "jurisdiction_support": 0.5,
            "language_support": 1.0,
        }
    )

    strong_readiness = derive_readiness(strong)
    weak_readiness = derive_readiness(weak)

    assert strong_readiness["claim_review"] >= 0.8
    assert weak_readiness["exploration"] >= 0.8
    assert weak_readiness["high_trust_report"] < 0.4


def test_missing_dimensions_reduce_readiness_without_crashing():
    report = _report({"document_text_quality": 1.0})
    readiness = derive_readiness(report)

    assert readiness["exploration"] == pytest.approx(0.35)
    assert readiness["high_trust_report"] == 0.0


def test_invalid_weights_and_bands():
    report = _report({"document_text_quality": 0.8})

    with pytest.raises(ValueError):
        weighted_score(report, {"document_text_quality": -1})

    assert readiness_band(0.81) == "high"
    assert readiness_band(0.6) == "medium"
    assert readiness_band(0.35) == "low"
    assert readiness_band(0.1) == "very_low"


def test_summary_is_json_serializable_and_preserves_risks():
    report = attach_readiness(_report({"document_text_quality": 0.8}))
    summary = summarize_compatibility(report)

    assert summary["missing_capabilities"] == ["manual_review"]
    assert summary["known_risks"] == ["toy_only"]
    assert summary["dimension_scores"]["document_text_quality"] == 0.8
    assert json.loads(json.dumps(summary))["plugin_name"] == "toy_plugin"
