from __future__ import annotations

from .claims import Claim, EvidenceSpan, ExtractionResult
from .compatibility import CompatibilityDimension, CompatibilityReport
from .entities import EntityCandidate, EntityResolutionResult, IdentifierHint
from .events import AssembledEvent, EventCandidate
from .ids import stable_id
from .plugins import PluginCompatibility, PluginManifest
from .sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord
from .temporal import TemporalHint, TemporalResolutionResult

__all__ = [
    "AssembledEvent",
    "Claim",
    "CompatibilityDimension",
    "CompatibilityReport",
    "EntityCandidate",
    "EntityResolutionResult",
    "EventCandidate",
    "EvidenceSpan",
    "ExtractionResult",
    "IdentifierHint",
    "NormalizedSourceDocument",
    "PluginCompatibility",
    "PluginManifest",
    "RawSourceDocument",
    "SourceQuery",
    "SourceRecord",
    "TemporalHint",
    "TemporalResolutionResult",
    "stable_id",
]
