from __future__ import annotations

import re

from .claims import ExtractionResult
from .compatibility import CompatibilityDimension, CompatibilityReport
from .detection import EventDetectorDiagnostics
from .events import EventCandidate
from .extractors import ClaimExtractorDiagnostics, evidence_for_match, make_claim_with_evidence
from .ids import stable_id
from .plugins import PluginManifest
from .source_adapters import SourceAdapterDiagnostics, content_hash, make_source_doc_id, make_source_record_id, normalize_text
from .sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord


class ToyOfficialAdapter:
    name = "toy_official_adapter"
    manifest = PluginManifest(
        plugin_name=name,
        plugin_version="0.1.0",
        plugin_kind="source_adapter",
        supported_source_systems=["toy_official"],
        supported_event_families=["toy_event"],
        supported_claim_schemas=["toy_claims"],
        required_capabilities=["text"],
        output_contracts=["normalized_source_document"],
    )

    def discover(self, query: SourceQuery):
        rows = [
            SourceRecord(
                source_record_id=make_source_record_id(query.source_system, query.query_id, "one"),
                source_system=query.source_system,
                source_url="https://example.invalid/toy-one",
                title="Toy official notice one",
                source_authority_level="official_regulator",
                source_role="canonical",
                entity_hints=[{"namespace": "registry:alpha", "value": "A-1", "confidence": 0.9}],
                metadata={"text": "Reportable event affected operations."},
            ),
            SourceRecord(
                source_record_id=make_source_record_id(query.source_system, query.query_id, "two"),
                source_system=query.source_system,
                source_url="https://example.invalid/toy-two",
                title="Toy official notice two",
                source_authority_level="official_regulator",
                source_role="canonical",
                entity_hints=[{"namespace": "domain:name", "value": "Beta", "confidence": 0.8}],
                metadata={"text": "Reportable event created measurable impact."},
            ),
        ]
        return rows, SourceAdapterDiagnostics(records_discovered=len(rows))

    def fetch(self, record: SourceRecord):
        text = str(record.metadata.get("text") or "Reportable event affected operations.")
        return (
            RawSourceDocument(
                source_record_id=record.source_record_id,
                source_system=record.source_system,
                raw_bytes_or_text=text,
                content_type="text/plain",
                raw_hash=content_hash(text),
            ),
            SourceAdapterDiagnostics(records_fetched=1),
        )

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
            document_type=record.document_type,
            document_subtype=record.document_subtype,
            text=text,
            text_hash=content_hash(text),
            raw_hash=raw.raw_hash,
            entity_hints=record.entity_hints,
            temporal_hints=[],
            metadata=record.metadata,
            compatibility=self.compatibility(record),
        )
        return doc, SourceAdapterDiagnostics(records_normalized=1)

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "toy_official"),
            event_family="toy_event",
            claim_schema="toy_claims",
            dimensions=[
                CompatibilityDimension(name="source_authority_confidence", score=0.9, basis="toy official role"),
                CompatibilityDimension(name="document_text_quality", score=0.9, basis="plain text"),
                CompatibilityDimension(name="evidence_addressability", score=0.9, basis="offset text"),
                CompatibilityDimension(name="metadata_completeness", score=0.8, basis="toy metadata"),
                CompatibilityDimension(name="provenance_completeness", score=0.8, basis="toy record id"),
            ],
        )


class ToyWeakAdapter(ToyOfficialAdapter):
    name = "toy_weak_adapter"
    manifest = PluginManifest(
        plugin_name=name,
        plugin_version="0.1.0",
        plugin_kind="source_adapter",
        supported_source_systems=["toy_weak"],
        supported_event_families=["toy_event"],
        supported_claim_schemas=["toy_claims"],
        required_capabilities=["text"],
        output_contracts=["normalized_source_document"],
        known_risks=["low_authority"],
    )

    def discover(self, query: SourceQuery):
        rows = [
            SourceRecord(
                source_record_id=make_source_record_id(query.source_system, query.query_id, "weak-one"),
                source_system=query.source_system,
                source_url="https://example.invalid/toy-weak-one",
                title="Toy weak report one",
                source_authority_level="unknown",
                source_role="early_signal",
                entity_hints=[{"namespace": "text:alias", "value": "Alpha", "confidence": 0.4}],
                metadata={"text": "An observer says a possible event affected operations."},
            )
        ]
        return rows, SourceAdapterDiagnostics(records_discovered=len(rows), warnings=["low_authority"])

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "toy_weak"),
            event_family="toy_event",
            claim_schema="toy_claims",
            dimensions=[
                CompatibilityDimension(name="source_authority_confidence", score=0.25, basis="toy weak role"),
                CompatibilityDimension(name="document_text_quality", score=0.7, basis="plain text"),
                CompatibilityDimension(name="evidence_addressability", score=0.7, basis="offset text"),
                CompatibilityDimension(name="metadata_completeness", score=0.3, basis="limited toy metadata"),
                CompatibilityDimension(name="provenance_completeness", score=0.3, basis="toy record id"),
            ],
            known_risks=["low_authority"],
        )


class ToyEventDetector:
    name = "toy_event_detector"
    event_family = "toy_event"

    def detect(self, doc: NormalizedSourceDocument):
        match = re.search(r"\b(reportable event|possible event)\b", doc.text, flags=re.I)
        if not match:
            return [], EventDetectorDiagnostics(documents_total=1, skipped_reasons={"no_match": 1})
        candidate = EventCandidate(
            event_candidate_id=stable_id("event_candidate", doc.source_doc_id, match.group(0).lower()),
            event_family=self.event_family,
            event_type="reported_event" if "reportable" in match.group(0).lower() else "possible_event",
            event_subtype="",
            source_doc_id=doc.source_doc_id,
            entity_candidates=doc.entity_hints,
            temporal_hints=doc.temporal_hints,
            detection_confidence=0.85 if doc.source_role == "canonical" else 0.5,
            detection_method=self.name,
            evidence_span_id=stable_id("evidence_span", doc.source_doc_id, match.start(), match.end()),
            source_role=doc.source_role,
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        score = 0.85 if "event" in doc.text.lower() else 0.2
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family=self.event_family,
            dimensions=[
                CompatibilityDimension(name="event_detection_confidence", score=score, basis="toy phrase"),
                CompatibilityDimension(name="entity_hint_quality", score=0.7 if doc.entity_hints else 0.0, basis="toy hints"),
            ],
        )


class ToyClaimExtractor:
    name = "toy_claim_extractor"
    claim_schema = "toy_claims"

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        claims = []
        spans = []
        field_patterns = {
            "event_mentioned": r"\b(reportable event|possible event)\b",
            "impact_language": r"\b(affected operations|measurable impact)\b",
        }
        for field_name, pattern in field_patterns.items():
            match = re.search(pattern, doc.text, flags=re.I)
            if not match:
                continue
            evidence_text, start, end = evidence_for_match(doc.text, match)
            claim, span = make_claim_with_evidence(
                source_doc_id=doc.source_doc_id,
                event_candidate_id=event_candidate.event_candidate_id if event_candidate else "",
                field_name=field_name,
                value=True if field_name == "event_mentioned" else evidence_text,
                value_type="boolean" if field_name == "event_mentioned" else "string",
                method=self.name,
                confidence=0.85 if doc.source_role == "canonical" else 0.55,
                evidence_text=evidence_text,
                start_char=start,
                end_char=end,
                source_url=doc.source_url,
                source_role=doc.source_role,
                source_authority_level=doc.source_authority_level,
                metadata={"source_system": doc.source_system},
            )
            claims.append(claim)
            spans.append(span)
        diagnostics = ClaimExtractorDiagnostics(
            documents_total=1,
            claims_total=len(claims),
            evidence_spans_total=len(spans),
            event_candidates_total=1 if event_candidate else 0,
            counts_by_field={claim.field_name: 1 for claim in claims},
            skipped_reasons={} if claims else {"no_claims": 1},
        )
        return ExtractionResult(
            source_doc_id=doc.source_doc_id,
            extractor_name=self.name,
            claim_schema=self.claim_schema,
            claims=claims,
            evidence_spans=spans,
            compatibility=self.compatibility(doc),
            diagnostics=diagnostics.to_dict(),
        )

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family="toy_event",
            claim_schema=self.claim_schema,
            dimensions=[
                CompatibilityDimension(name="claim_schema_alignment", score=0.8, basis="toy fields"),
                CompatibilityDimension(name="claim_extraction_confidence", score=0.8 if "event" in doc.text.lower() else 0.2, basis="toy phrases"),
                CompatibilityDimension(name="reviewability", score=0.9, basis="short evidence"),
            ],
        )
