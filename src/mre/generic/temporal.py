from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import to_dict, validate_score


@dataclass(frozen=True)
class TemporalHint:
    kind: str
    value: str
    confidence: float
    basis: str
    source_doc_id: str = ""
    evidence_span_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", validate_score(self.confidence, name="confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class TemporalResolutionResult:
    source_doc_id: str
    hints: list[TemporalHint] = field(default_factory=list)
    selected: dict[str, TemporalHint] = field(default_factory=dict)
    overall_confidence: float = 0.0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "overall_confidence", validate_score(self.overall_confidence, name="overall_confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
