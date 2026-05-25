from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .compatibility import CompatibilityReport
from .events import EventCandidate
from .ids import to_dict
from .sources import NormalizedSourceDocument


@dataclass(frozen=True)
class EventDetectorDiagnostics:
    documents_total: int = 0
    candidates_total: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return to_dict(self)


class EventCandidateDetector(Protocol):
    name: str
    event_family: str

    def detect(self, doc: NormalizedSourceDocument) -> tuple[list[EventCandidate], EventDetectorDiagnostics]: ...

    def compatibility(self, doc: NormalizedSourceDocument) -> CompatibilityReport: ...
