from __future__ import annotations

from dataclasses import replace
from typing import Any

from .compatibility import CompatibilityReport
from .ids import validate_score


DEFAULT_READINESS_LEVELS = (
    "exploration",
    "internal_research",
    "claim_review",
    "user_facing_draft",
    "reviewed_dataset",
    "high_trust_report",
)

DEFAULT_READINESS_WEIGHTS: dict[str, dict[str, float]] = {
    "exploration": {
        "document_text_quality": 0.35,
        "event_detection_confidence": 0.25,
        "claim_extraction_confidence": 0.20,
        "source_identity_confidence": 0.10,
        "language_support": 0.10,
    },
    "internal_research": {
        "document_text_quality": 0.20,
        "evidence_addressability": 0.20,
        "metadata_completeness": 0.15,
        "event_detection_confidence": 0.15,
        "claim_schema_alignment": 0.15,
        "provenance_completeness": 0.15,
    },
    "claim_review": {
        "evidence_addressability": 0.25,
        "reviewability": 0.25,
        "claim_extraction_confidence": 0.20,
        "document_text_quality": 0.15,
        "provenance_completeness": 0.15,
    },
    "user_facing_draft": {
        "source_authority_confidence": 0.15,
        "evidence_addressability": 0.20,
        "metadata_completeness": 0.15,
        "claim_schema_alignment": 0.20,
        "reviewability": 0.15,
        "provenance_completeness": 0.15,
    },
    "reviewed_dataset": {
        "source_authority_confidence": 0.15,
        "evidence_addressability": 0.20,
        "entity_resolution_confidence": 0.15,
        "temporal_resolution_confidence": 0.15,
        "claim_schema_alignment": 0.15,
        "provenance_completeness": 0.10,
        "reproducibility": 0.10,
    },
    "high_trust_report": {
        "source_authority_confidence": 0.15,
        "evidence_addressability": 0.15,
        "entity_resolution_confidence": 0.15,
        "temporal_resolution_confidence": 0.15,
        "claim_schema_alignment": 0.15,
        "reviewability": 0.10,
        "provenance_completeness": 0.10,
        "jurisdiction_support": 0.05,
    },
}


def dimension_score(report: CompatibilityReport, name: str, default: float = 0.0) -> float:
    for dimension in report.dimensions:
        if dimension.name == name:
            return dimension.score
    return validate_score(default, name="default")


def dimension_notes(report: CompatibilityReport, name: str) -> list[str]:
    notes: list[str] = []
    for dimension in report.dimensions:
        if dimension.name == name:
            if dimension.basis:
                notes.append(dimension.basis)
            if dimension.notes:
                notes.append(dimension.notes)
    return notes


def weighted_score(report: CompatibilityReport, weights: dict[str, float], *, default: float = 0.0) -> float:
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("weights must be non-negative")
    total = 0.0
    weight_total = 0.0
    names = {dimension.name for dimension in report.dimensions}
    seen = False
    for name, weight in weights.items():
        if name in names:
            seen = True
        total += dimension_score(report, name, default=default) * weight
        weight_total += weight
    if weight_total == 0 or not seen:
        return validate_score(default, name="default")
    return validate_score(total / weight_total)


def derive_readiness(report: CompatibilityReport, *, custom_weights: dict[str, dict[str, float]] | None = None) -> dict[str, float]:
    weights_by_level = {**DEFAULT_READINESS_WEIGHTS, **(custom_weights or {})}
    return {
        level: weighted_score(report, weights_by_level.get(level, {}), default=0.0)
        for level in DEFAULT_READINESS_LEVELS
    }


def attach_readiness(report: CompatibilityReport, readiness: dict[str, float] | None = None) -> CompatibilityReport:
    return replace(report, readiness=readiness or derive_readiness(report))


def readiness_band(score: float) -> str:
    value = validate_score(score)
    if value >= 0.80:
        return "high"
    if value >= 0.60:
        return "medium"
    if value >= 0.35:
        return "low"
    return "very_low"


def summarize_compatibility(report: CompatibilityReport) -> dict[str, Any]:
    readiness = report.readiness or derive_readiness(report)
    return {
        "plugin_name": report.plugin_name,
        "source_system": report.source_system,
        "event_family": report.event_family,
        "claim_schema": report.claim_schema,
        "readiness": readiness,
        "readiness_bands": {level: readiness_band(score) for level, score in readiness.items()},
        "missing_capabilities": list(report.missing_capabilities),
        "known_risks": list(report.known_risks),
        "dimension_scores": {dimension.name: dimension.score for dimension in report.dimensions},
    }
