from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compatibility import CompatibilityReport
from .events import EventCandidate
from .ids import to_dict, validate_score


@dataclass(frozen=True)
class EvidenceSpan:
    evidence_span_id: str
    source_doc_id: str
    claim_id: str
    evidence_text: str
    start_char: int
    end_char: int
    source_url: str = ""
    source_role: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    source_doc_id: str
    field_name: str
    value: Any
    value_type: str
    confidence: float
    method: str
    evidence_span_id: str
    event_candidate_id: str = ""
    event_id: str = ""
    review_status: str = "needs_review"
    label_quality: str = ""
    claim_kind: str = "source_assertion"
    claim_truth_status: str = "asserted_by_source"
    source_authority_level: str = ""
    source_role: str = ""
    compatibility_confidence: float = 0.0
    notes: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", validate_score(self.confidence, name="confidence"))
        object.__setattr__(self, "compatibility_confidence", validate_score(self.compatibility_confidence, name="compatibility_confidence"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class ExtractionResult:
    source_doc_id: str
    extractor_name: str
    claim_schema: str
    claims: list[Claim] = field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    event_candidates: list[EventCandidate] = field(default_factory=list)
    compatibility: CompatibilityReport | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
