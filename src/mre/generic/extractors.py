from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Protocol

from .claims import Claim, EvidenceSpan, ExtractionResult
from .compatibility import CompatibilityReport
from .events import EventCandidate
from .ids import stable_id, to_dict
from .sources import NormalizedSourceDocument


@dataclass(frozen=True)
class ClaimExtractorDiagnostics:
    documents_total: int = 0
    claims_total: int = 0
    evidence_spans_total: int = 0
    event_candidates_total: int = 0
    counts_by_field: dict[str, int] = field(default_factory=dict)
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return to_dict(self)


class ClaimExtractor(Protocol):
    name: str
    claim_schema: str

    def extract(
        self,
        doc: NormalizedSourceDocument,
        event_candidate: EventCandidate | None = None,
    ) -> ExtractionResult: ...

    def compatibility(self, doc: NormalizedSourceDocument) -> CompatibilityReport: ...


def evidence_for_match(source_text: str, match: re.Match[str]) -> tuple[str, int, int]:
    start = match.start()
    end = match.end()
    left_candidates = [source_text.rfind(ch, 0, start) for ch in ".!?\n"]
    left = max(left_candidates)
    left = 0 if left < 0 else left + 1
    right_candidates = [idx for ch in ".!?\n" if (idx := source_text.find(ch, end)) != -1]
    right = min(right_candidates) + 1 if right_candidates else len(source_text)
    raw = source_text[left:right]
    leading = len(raw) - len(raw.lstrip())
    trailing = len(raw) - len(raw.rstrip())
    clean = re.sub(r"\s+", " ", raw).strip()
    return clean, left + leading, right - trailing


def make_claim_with_evidence(
    *,
    source_doc_id: str,
    field_name: str,
    value: Any,
    value_type: str,
    method: str,
    confidence: float,
    evidence_text: str,
    start_char: int,
    end_char: int,
    source_url: str = "",
    event_candidate_id: str = "",
    event_id: str = "",
    claim_kind: str = "source_assertion",
    claim_truth_status: str = "asserted_by_source",
    source_authority_level: str = "",
    source_role: str = "",
    metadata: dict[str, object] | None = None,
) -> tuple[Claim, EvidenceSpan]:
    if not source_doc_id:
        raise ValueError("source_doc_id is required")
    claim_id = stable_id("claim", source_doc_id, event_candidate_id, event_id, field_name, value, evidence_text)
    evidence_span_id = stable_id("evidence_span", source_doc_id, start_char, end_char)
    claim = Claim(
        claim_id=claim_id,
        event_candidate_id=event_candidate_id,
        event_id=event_id,
        source_doc_id=source_doc_id,
        field_name=field_name,
        value=value,
        value_type=value_type,
        confidence=confidence,
        method=method,
        evidence_span_id=evidence_span_id,
        claim_kind=claim_kind,
        claim_truth_status=claim_truth_status,
        source_authority_level=source_authority_level,
        source_role=source_role,
        metadata=metadata or {},
    )
    span = EvidenceSpan(
        evidence_span_id=evidence_span_id,
        source_doc_id=source_doc_id,
        claim_id=claim_id,
        evidence_text=evidence_text,
        start_char=start_char,
        end_char=end_char,
        source_url=source_url,
        source_role=source_role,
        metadata=metadata or {},
    )
    return claim, span
