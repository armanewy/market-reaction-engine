from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import to_dict, validate_score


READINESS_LEVELS = (
    "exploration",
    "internal_research",
    "claim_review",
    "user_facing_draft",
    "reviewed_dataset",
    "high_trust_report",
)


@dataclass(frozen=True)
class CompatibilityDimension:
    name: str
    score: float
    basis: str
    method: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", validate_score(self.score, name="score"))

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class CompatibilityReport:
    plugin_name: str
    source_system: str = ""
    event_family: str = ""
    claim_schema: str = ""
    dimensions: list[CompatibilityDimension] = field(default_factory=list)
    readiness: dict[str, float] = field(default_factory=dict)
    missing_capabilities: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_readiness = {str(k): validate_score(v, name=f"readiness[{k}]") for k, v in self.readiness.items()}
        object.__setattr__(self, "readiness", normalized_readiness)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
