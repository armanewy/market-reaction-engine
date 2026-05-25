from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Protocol

from .compatibility import CompatibilityDimension, CompatibilityReport
from .entities import EntityCandidate, EntityResolutionResult, IdentifierHint
from .ids import stable_id, to_dict
from .temporal import TemporalHint, TemporalResolutionResult


@dataclass(frozen=True)
class EntityResolverDiagnostics:
    hints_total: int = 0
    candidates_total: int = 0
    unresolved_total: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return to_dict(self)


class EntityResolver(Protocol):
    name: str

    def resolve(
        self,
        hints: list[IdentifierHint],
        *,
        context: dict | None = None,
    ) -> tuple[EntityResolutionResult, EntityResolverDiagnostics]: ...

    def compatibility(self, hints: list[IdentifierHint]) -> CompatibilityReport: ...


def _hint_key(hint: IdentifierHint) -> str:
    return (hint.value or hint.label).strip().lower()


class SimpleHintEntityResolver:
    name = "simple_hint_entity_resolver"

    def resolve(
        self,
        hints: list[IdentifierHint],
        *,
        context: dict | None = None,
    ) -> tuple[EntityResolutionResult, EntityResolverDiagnostics]:
        context = context or {}
        source_doc_id = str(context.get("source_doc_id", ""))
        if not hints:
            result = EntityResolutionResult(source_doc_id=source_doc_id, candidates=[], unresolved_hints=[], overall_confidence=0.0, notes="no hints")
            diagnostics = EntityResolverDiagnostics(hints_total=0, candidates_total=0, unresolved_total=0, warnings=["no_hints"])
            return result, diagnostics

        groups: dict[str, list[IdentifierHint]] = defaultdict(list)
        for hint in hints:
            key = _hint_key(hint)
            if key:
                groups[key].append(hint)

        candidates: list[EntityCandidate] = []
        for key, grouped_hints in groups.items():
            average_confidence = sum(hint.confidence for hint in grouped_hints) / len(grouped_hints)
            support_bonus = min(len(grouped_hints) * 0.08, 0.24)
            evidence_bonus = 0.08 if any(hint.evidence_span_id or hint.source_doc_id for hint in grouped_hints) else 0.0
            confidence = min(1.0, average_confidence + support_bonus + evidence_bonus)
            display_name = next((hint.label for hint in grouped_hints if hint.label), key)
            candidates.append(
                EntityCandidate(
                    entity_candidate_id=stable_id("entity_candidate", key, [hint.to_dict() for hint in grouped_hints]),
                    display_name=display_name,
                    identifiers=grouped_hints,
                    confidence=confidence,
                    resolution_status="candidate",
                    basis=f"{len(grouped_hints)} hint(s)",
                )
            )

        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        if candidates:
            top = candidates[0].confidence
            tied = len(candidates) > 1 and abs(top - candidates[1].confidence) <= 0.05
            status = "ambiguous" if tied else "resolved"
            candidates[0] = replace(candidates[0], resolution_status=status)
            overall = candidates[0].confidence
        else:
            overall = 0.0

        result = EntityResolutionResult(source_doc_id=source_doc_id, candidates=candidates, unresolved_hints=[], overall_confidence=overall)
        diagnostics = EntityResolverDiagnostics(hints_total=len(hints), candidates_total=len(candidates), unresolved_total=0)
        return result, diagnostics

    def compatibility(self, hints: list[IdentifierHint]) -> CompatibilityReport:
        if not hints:
            quality = 0.0
        else:
            quality = sum(hint.confidence for hint in hints) / len(hints)
        return CompatibilityReport(
            plugin_name=self.name,
            dimensions=[
                CompatibilityDimension(name="entity_hint_quality", score=quality, basis="mean hint confidence"),
                CompatibilityDimension(name="entity_resolution_confidence", score=quality, basis="simple hint grouping"),
            ],
        )


@dataclass(frozen=True)
class TemporalResolverDiagnostics:
    hints_total: int = 0
    selected_total: int = 0
    unresolved_total: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return to_dict(self)


class TemporalResolver(Protocol):
    name: str

    def resolve(
        self,
        hints: list[TemporalHint],
        *,
        preferred_kinds: list[str] | None = None,
    ) -> tuple[TemporalResolutionResult, TemporalResolverDiagnostics]: ...

    def compatibility(self, hints: list[TemporalHint]) -> CompatibilityReport: ...


class SimpleTemporalResolver:
    name = "simple_temporal_resolver"

    def resolve(
        self,
        hints: list[TemporalHint],
        *,
        preferred_kinds: list[str] | None = None,
    ) -> tuple[TemporalResolutionResult, TemporalResolverDiagnostics]:
        if not hints:
            result = TemporalResolutionResult(source_doc_id="", hints=[], selected={}, overall_confidence=0.0, notes="no hints")
            diagnostics = TemporalResolverDiagnostics(hints_total=0, selected_total=0, unresolved_total=0, warnings=["no_hints"])
            return result, diagnostics

        by_kind: dict[str, TemporalHint] = {}
        for hint in sorted(hints, key=lambda item: item.confidence, reverse=True):
            by_kind.setdefault(hint.kind, hint)

        selected: dict[str, TemporalHint] = {}
        preferred = preferred_kinds or list(by_kind.keys())
        for kind in preferred:
            if kind in by_kind:
                selected[kind] = by_kind[kind]
        for kind, hint in by_kind.items():
            selected.setdefault(kind, hint)

        confidence = sum(hint.confidence for hint in selected.values()) / len(selected) if selected else 0.0
        source_doc_id = next((hint.source_doc_id for hint in hints if hint.source_doc_id), "")
        result = TemporalResolutionResult(source_doc_id=source_doc_id, hints=hints, selected=selected, overall_confidence=confidence)
        diagnostics = TemporalResolverDiagnostics(hints_total=len(hints), selected_total=len(selected), unresolved_total=0)
        return result, diagnostics

    def compatibility(self, hints: list[TemporalHint]) -> CompatibilityReport:
        quality = sum(hint.confidence for hint in hints) / len(hints) if hints else 0.0
        return CompatibilityReport(
            plugin_name=self.name,
            dimensions=[
                CompatibilityDimension(name="temporal_resolution_confidence", score=quality, basis="highest confidence per kind"),
            ],
        )
