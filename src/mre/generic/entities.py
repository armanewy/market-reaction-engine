from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import to_dict, validate_score


@dataclass(frozen=True)
class IdentifierHint:
    namespace: str
    value: str
    label: str = ""
    source_doc_id: str = ""
    evidence_span_id: str = ""
    confidence: float = 0.0
    role: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", validate_score(self.confidence, name="confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class EntityCandidate:
    entity_candidate_id: str
    display_name: str
    identifiers: list[IdentifierHint] = field(default_factory=list)
    confidence: float = 0.0
    resolution_status: str = "candidate"
    basis: str = ""
    notes: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", validate_score(self.confidence, name="confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class EntityResolutionResult:
    source_doc_id: str
    candidates: list[EntityCandidate] = field(default_factory=list)
    unresolved_hints: list[IdentifierHint] = field(default_factory=list)
    overall_confidence: float = 0.0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "overall_confidence", validate_score(self.overall_confidence, name="overall_confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
