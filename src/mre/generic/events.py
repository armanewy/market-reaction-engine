from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compatibility import CompatibilityReport
from .ids import to_dict, validate_score


@dataclass(frozen=True)
class EventCandidate:
    event_candidate_id: str
    event_family: str
    event_type: str
    event_subtype: str
    source_doc_id: str
    entity_candidates: list[dict] = field(default_factory=list)
    temporal_hints: list[dict] = field(default_factory=list)
    detection_confidence: float = 0.0
    detection_method: str = ""
    evidence_span_id: str = ""
    source_role: str = ""
    status: str = "candidate"
    metadata: dict[str, object] = field(default_factory=dict)
    compatibility: CompatibilityReport | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "detection_confidence", validate_score(self.detection_confidence, name="detection_confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class AssembledEvent:
    event_id: str
    event_family: str
    event_type: str
    event_subtype: str = ""
    event_candidate_ids: list[str] = field(default_factory=list)
    source_doc_ids: list[str] = field(default_factory=list)
    entity_id: str = ""
    entity_confidence: float = 0.0
    event_time: str = ""
    temporal_confidence: float = 0.0
    status: str = "draft"
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_confidence", validate_score(self.entity_confidence, name="entity_confidence"))
        object.__setattr__(self, "temporal_confidence", validate_score(self.temporal_confidence, name="temporal_confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
