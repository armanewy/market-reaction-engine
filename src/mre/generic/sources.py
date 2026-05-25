from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compatibility import CompatibilityReport
from .ids import to_dict


@dataclass(frozen=True)
class SourceQuery:
    query_id: str
    source_system: str
    params: dict[str, object] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class SourceRecord:
    source_record_id: str
    source_system: str
    source_url: str = ""
    title: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    document_type: str = ""
    document_subtype: str = ""
    source_authority_level: str = "unknown"
    source_role: str = ""
    jurisdiction: str = ""
    entity_hints: list[dict] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class RawSourceDocument:
    source_record_id: str
    source_system: str
    raw_bytes_or_text: str | bytes
    content_type: str = ""
    retrieved_at: str = ""
    raw_hash: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class NormalizedSourceDocument:
    source_doc_id: str
    source_record_id: str
    source_system: str
    source_authority_level: str = "unknown"
    source_role: str = ""
    jurisdiction: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    source_url: str = ""
    title: str = ""
    document_type: str = ""
    document_subtype: str = ""
    language: str = ""
    text: str = ""
    text_hash: str = ""
    raw_hash: str = ""
    entity_hints: list[dict] = field(default_factory=list)
    temporal_hints: list[dict] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    compatibility: CompatibilityReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
