from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Protocol

from .compatibility import CompatibilityReport
from .ids import stable_id, to_dict
from .plugins import PluginManifest
from .sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord


@dataclass(frozen=True)
class SourceAdapterDiagnostics:
    records_discovered: int = 0
    records_fetched: int = 0
    records_normalized: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return to_dict(self)


class SourceAdapter(Protocol):
    name: str
    manifest: PluginManifest

    def discover(self, query: SourceQuery) -> tuple[list[SourceRecord], SourceAdapterDiagnostics]: ...

    def fetch(self, record: SourceRecord) -> tuple[RawSourceDocument, SourceAdapterDiagnostics]: ...

    def normalize(
        self,
        raw: RawSourceDocument,
        record: SourceRecord | None = None,
    ) -> tuple[NormalizedSourceDocument, SourceAdapterDiagnostics]: ...

    def compatibility(self, value: object) -> CompatibilityReport: ...


def normalize_text(raw: str | bytes) -> str:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def content_hash(raw: str | bytes) -> str:
    data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def make_source_record_id(source_system: str, *parts: object) -> str:
    return stable_id("source_record", source_system, *parts)


def make_source_doc_id(source_system: str, source_record_id: str, *parts: object) -> str:
    return stable_id("source_doc", source_system, source_record_id, *parts)
