from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .claims import Claim, EvidenceSpan, ExtractionResult
from .compatibility import CompatibilityReport
from .events import EventCandidate
from .ids import to_dict
from .sources import NormalizedSourceDocument, SourceQuery


@dataclass(frozen=True)
class PluginRunStep:
    name: str
    status: str
    message: str = ""
    metrics: dict[str, object] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class PluginRunReport:
    plugin_name: str
    status: str
    steps: list[PluginRunStep] = field(default_factory=list)
    compatibility_reports: list[CompatibilityReport] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


def _diagnostics_dict(value: object) -> dict:
    return value.to_dict() if hasattr(value, "to_dict") else {}


def run_source_to_extraction(
    *,
    source_adapter,
    query: SourceQuery,
    claim_extractor,
    event_detector=None,
) -> PluginRunReport:
    steps: list[PluginRunStep] = []
    compatibility_reports: list[CompatibilityReport] = []
    warnings: list[str] = []
    normalized_documents: list[NormalizedSourceDocument] = []
    event_candidates: list[EventCandidate] = []
    claims: list[Claim] = []
    evidence_spans: list[EvidenceSpan] = []

    records, discover_diagnostics = source_adapter.discover(query)
    steps.append(
        PluginRunStep(
            name="discover",
            status="completed",
            metrics={"records": len(records)},
            outputs={"diagnostics": _diagnostics_dict(discover_diagnostics)},
        )
    )
    compatibility_reports.append(source_adapter.compatibility(query))

    for record in records:
        try:
            raw, fetch_diagnostics = source_adapter.fetch(record)
            steps.append(
                PluginRunStep(
                    name="fetch",
                    status="completed",
                    metrics={"records": 1},
                    outputs={"diagnostics": _diagnostics_dict(fetch_diagnostics)},
                )
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"fetch_failed:{record.source_record_id}:{type(exc).__name__}")
            steps.append(PluginRunStep(name="fetch", status="failed", message=str(exc), metrics={"records": 1}))
            continue

        try:
            doc, normalize_diagnostics = source_adapter.normalize(raw, record)
            normalized_documents.append(doc)
            steps.append(
                PluginRunStep(
                    name="normalize",
                    status="completed",
                    metrics={"documents": 1},
                    outputs={"diagnostics": _diagnostics_dict(normalize_diagnostics)},
                )
            )
            compatibility_reports.append(source_adapter.compatibility(doc))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"normalize_failed:{record.source_record_id}:{type(exc).__name__}")
            steps.append(PluginRunStep(name="normalize", status="failed", message=str(exc), metrics={"records": 1}))
            continue

        doc_candidates: list[EventCandidate] = []
        if event_detector is not None:
            detected, detector_diagnostics = event_detector.detect(doc)
            doc_candidates.extend(detected)
            event_candidates.extend(detected)
            compatibility_reports.append(event_detector.compatibility(doc))
            steps.append(
                PluginRunStep(
                    name="detect",
                    status="completed",
                    metrics={"candidates": len(detected)},
                    outputs={"diagnostics": _diagnostics_dict(detector_diagnostics)},
                )
            )

        targets = doc_candidates or [None]
        for candidate in targets:
            result: ExtractionResult = claim_extractor.extract(doc, candidate)
            claims.extend(result.claims)
            evidence_spans.extend(result.evidence_spans)
            event_candidates.extend(result.event_candidates)
            if result.compatibility is not None:
                compatibility_reports.append(result.compatibility)
            steps.append(
                PluginRunStep(
                    name="extract",
                    status="completed",
                    metrics={"claims": len(result.claims), "evidence_spans": len(result.evidence_spans)},
                    outputs={"diagnostics": result.diagnostics},
                )
            )

    status = "ok" if not any(step.status == "failed" for step in steps) else "partial"
    return PluginRunReport(
        plugin_name=getattr(claim_extractor, "name", "claim_extractor"),
        status=status,
        steps=steps,
        compatibility_reports=compatibility_reports,
        diagnostics={
            "documents": len(normalized_documents),
            "event_candidates": len(event_candidates),
            "claims": len(claims),
            "evidence_spans": len(evidence_spans),
        },
        artifacts={
            "normalized_documents": normalized_documents,
            "event_candidates": event_candidates,
            "claims": claims,
            "evidence_spans": evidence_spans,
            "compatibility_reports": compatibility_reports,
        },
        warnings=warnings,
    )
