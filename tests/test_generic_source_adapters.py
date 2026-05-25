from __future__ import annotations

import json

from mre.generic.compatibility import CompatibilityDimension, CompatibilityReport
from mre.generic.plugins import PluginManifest
from mre.generic.source_adapters import (
    SourceAdapterDiagnostics,
    content_hash,
    make_source_doc_id,
    make_source_record_id,
    normalize_text,
)
from mre.generic.sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord


class ToyOfficialNoticeAdapter:
    name = "toy_official_notice"
    manifest = PluginManifest(
        plugin_name=name,
        plugin_version="0.1",
        plugin_kind="source_adapter",
        supported_source_systems=["toy_notice"],
        supported_event_families=["toy_event"],
        supported_claim_schemas=["toy_claims"],
        required_capabilities=["text"],
        output_contracts=["normalized_source_document"],
    )

    def discover(self, query: SourceQuery):
        record = SourceRecord(
            source_record_id=make_source_record_id(query.source_system, query.query_id, "official"),
            source_system=query.source_system,
            source_url="https://example.invalid/notice",
            title="Official toy notice",
            source_authority_level="official_regulator",
            source_role="canonical",
            entity_hints=[{"namespace": "registry:alpha", "value": "A-1", "confidence": 0.9}],
            metadata={"query": query.params},
        )
        return [record], SourceAdapterDiagnostics(records_discovered=1)

    def fetch(self, record: SourceRecord):
        raw = RawSourceDocument(
            source_record_id=record.source_record_id,
            source_system=record.source_system,
            raw_bytes_or_text="<p>Reportable incident affected operations.</p>",
            raw_hash=content_hash("<p>Reportable incident affected operations.</p>"),
        )
        return raw, SourceAdapterDiagnostics(records_fetched=1)

    def normalize(self, raw: RawSourceDocument, record: SourceRecord | None = None):
        record = record or SourceRecord(source_record_id=raw.source_record_id, source_system=raw.source_system)
        text = normalize_text(raw.raw_bytes_or_text)
        doc = NormalizedSourceDocument(
            source_doc_id=make_source_doc_id(raw.source_system, raw.source_record_id),
            source_record_id=raw.source_record_id,
            source_system=raw.source_system,
            source_authority_level=record.source_authority_level,
            source_role=record.source_role,
            source_url=record.source_url,
            title=record.title,
            text=text,
            text_hash=content_hash(text),
            raw_hash=raw.raw_hash,
            entity_hints=record.entity_hints,
        )
        return doc, SourceAdapterDiagnostics(records_normalized=1)

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "toy_notice"),
            dimensions=[
                CompatibilityDimension(name="document_text_quality", score=0.95, basis="clean text"),
                CompatibilityDimension(name="metadata_completeness", score=0.9, basis="toy metadata"),
            ],
        )


class ToyWeakArticleAdapter(ToyOfficialNoticeAdapter):
    name = "toy_weak_article"

    def discover(self, query: SourceQuery):
        record = SourceRecord(
            source_record_id=make_source_record_id(query.source_system, query.query_id, "weak"),
            source_system=query.source_system,
            title="Weak toy article",
            source_authority_level="unknown",
            source_role="early_signal",
            entity_hints=[{"namespace": "text:alias", "value": "Alpha", "confidence": 0.4}],
        )
        return [record], SourceAdapterDiagnostics(records_discovered=1, warnings=["weak_metadata"])

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "toy_article"),
            dimensions=[
                CompatibilityDimension(name="document_text_quality", score=0.65, basis="short text"),
                CompatibilityDimension(name="metadata_completeness", score=0.25, basis="limited metadata"),
            ],
            known_risks=["unverified_source"],
        )


def test_source_adapter_flow_with_official_toy_adapter():
    adapter = ToyOfficialNoticeAdapter()
    query = SourceQuery(query_id="q1", source_system="toy_notice", params={"topic": "incident"})

    records, discover_diagnostics = adapter.discover(query)
    raw, fetch_diagnostics = adapter.fetch(records[0])
    doc, normalize_diagnostics = adapter.normalize(raw, records[0])
    report = adapter.compatibility(doc)

    assert discover_diagnostics.records_discovered == 1
    assert fetch_diagnostics.records_fetched == 1
    assert normalize_diagnostics.records_normalized == 1
    assert doc.text == "Reportable incident affected operations."
    assert doc.text_hash == content_hash(doc.text)
    assert doc.entity_hints[0]["namespace"] == "registry:alpha"
    assert report.dimensions[0].score == 0.95
    json.dumps(doc.to_dict())


def test_weak_source_is_not_rejected():
    adapter = ToyWeakArticleAdapter()
    query = SourceQuery(query_id="q2", source_system="toy_article")

    records, diagnostics = adapter.discover(query)
    report = adapter.compatibility(records[0])

    assert diagnostics.warnings == ["weak_metadata"]
    assert records[0].source_authority_level == "unknown"
    assert records[0].source_role == "early_signal"
    assert report.known_risks == ["unverified_source"]


def test_normalize_text_and_ids_are_stable():
    assert normalize_text(b"<b>Hello</b>\n world") == "Hello world"
    assert make_source_record_id("toy", "a") == make_source_record_id("toy", "a")
    assert make_source_doc_id("toy", "record1") == make_source_doc_id("toy", "record1")
