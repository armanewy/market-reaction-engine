from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .cyber_8k_parser import parse_cyber_8k_document
from .generic.claims import Claim as GenericClaim
from .generic.claims import EvidenceSpan as GenericEvidenceSpan
from .generic.claims import ExtractionResult
from .generic.compatibility import CompatibilityDimension, CompatibilityReport
from .generic.detection import EventDetectorDiagnostics
from .generic.events import EventCandidate
from .generic.extractors import ClaimExtractorDiagnostics
from .generic.ids import stable_id
from .generic.plugin_runner import run_source_to_extraction
from .generic.plugins import PluginManifest
from .generic.source_adapters import SourceAdapterDiagnostics, content_hash, make_source_doc_id, make_source_record_id
from .generic.sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord
from .paths import ensure_parent
from .source_docs import SourceDocument, load_source_documents


CYBER_8K_PLUGIN_MANIFEST = PluginManifest(
    plugin_name="cyber_8k_watch",
    plugin_version="0.1.0",
    plugin_kind="pipeline",
    supported_source_systems=["sec_edgar_source_manifest"],
    supported_event_families=["cybersecurity_material_incidents_8k"],
    supported_claim_schemas=["cyber_8k_watch_claims"],
    required_capabilities=["source_document_text", "evidence_offsets"],
    optional_capabilities=["filing_metadata", "source_urls"],
    known_risks=["deterministic_parser_baseline", "requires_review_for_user_facing_data"],
    output_contracts=["normalized_source_document", "event_candidate", "claim", "evidence_span"],
)


def _norm(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _notes(doc: SourceDocument) -> dict[str, Any]:
    try:
        parsed = json.loads(doc.notes) if doc.notes else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_authority(doc: SourceDocument) -> str:
    source_type = doc.source_type.lower()
    if "sec" in source_type or "edgar" in doc.source_url.lower():
        return "official_regulator"
    return "unknown"


def _source_role(doc: SourceDocument) -> str:
    source_type = doc.source_type.lower()
    if "exhibit" in source_type:
        return "corroborating"
    return "canonical"


def _source_doc_payload(doc: SourceDocument) -> dict[str, Any]:
    notes = _notes(doc)
    return {
        "source_doc_id": doc.source_doc_id,
        "ticker": doc.ticker,
        "event_id": doc.event_id,
        "event_time": doc.event_time.isoformat(),
        "event_type": doc.event_type,
        "event_subtype": doc.event_subtype,
        "release_session": doc.release_session,
        "source_type": doc.source_type,
        "source_url": doc.source_url,
        "title": doc.title,
        "path": doc.path,
        "text": doc.text,
        "fiscal_period_end": doc.fiscal_period_end,
        "sector_benchmark": doc.sector_benchmark,
        "notes": doc.notes,
        "form": _norm(notes.get("form")),
        "accession": _norm(notes.get("accession")),
        "cik": _norm(notes.get("cik")),
        "company_name": _norm(notes.get("company_name")),
        "filing_date": _norm(notes.get("filing_date")),
        "accepted_at": _norm(notes.get("accepted_at")),
        "item_numbers": _norm(notes.get("item_numbers")),
    }


class Cyber8KManifestSourceAdapter:
    name = "cyber_8k_manifest_source_adapter"
    manifest = CYBER_8K_PLUGIN_MANIFEST

    def __init__(self, documents_manifest: str | Path):
        self.documents_manifest = Path(documents_manifest)
        self._docs_by_record: dict[str, SourceDocument] = {}

    def discover(self, query: SourceQuery):
        docs = load_source_documents(self.documents_manifest)
        records: list[SourceRecord] = []
        for doc in docs:
            notes = _notes(doc)
            record_id = make_source_record_id(query.source_system, doc.source_doc_id, doc.event_id)
            self._docs_by_record[record_id] = doc
            records.append(
                SourceRecord(
                    source_record_id=record_id,
                    source_system=query.source_system,
                    source_url=doc.source_url,
                    title=doc.title,
                    published_at=doc.event_time.isoformat(),
                    retrieved_at="",
                    document_type=_norm(notes.get("form"), default=doc.source_type),
                    document_subtype=_norm(notes.get("item_numbers"), default=doc.event_subtype),
                    source_authority_level=_source_authority(doc),
                    source_role=_source_role(doc),
                    jurisdiction="US",
                    entity_hints=[
                        {"namespace": "ticker", "value": doc.ticker, "confidence": 0.85},
                        {"namespace": "cik", "value": _norm(notes.get("cik")), "confidence": 0.9},
                    ],
                    metadata={"source_document": _source_doc_payload(doc)},
                )
            )
        return records, SourceAdapterDiagnostics(records_discovered=len(records))

    def fetch(self, record: SourceRecord):
        doc = self._docs_by_record.get(record.source_record_id)
        if doc is None:
            payload = record.metadata.get("source_document", {})
            text = _norm(payload.get("text")) if isinstance(payload, dict) else ""
        else:
            text = doc.text
        return (
            RawSourceDocument(
                source_record_id=record.source_record_id,
                source_system=record.source_system,
                raw_bytes_or_text=text,
                content_type="text/plain",
                raw_hash=content_hash(text),
                metadata=record.metadata,
            ),
            SourceAdapterDiagnostics(records_fetched=1),
        )

    def normalize(self, raw: RawSourceDocument, record: SourceRecord | None = None):
        record = record or SourceRecord(source_record_id=raw.source_record_id, source_system=raw.source_system)
        text = raw.raw_bytes_or_text.decode("utf-8", errors="replace") if isinstance(raw.raw_bytes_or_text, bytes) else str(raw.raw_bytes_or_text)
        payload = record.metadata.get("source_document", {})
        doc = NormalizedSourceDocument(
            source_doc_id=make_source_doc_id(raw.source_system, raw.source_record_id),
            source_record_id=raw.source_record_id,
            source_system=raw.source_system,
            source_authority_level=record.source_authority_level,
            source_role=record.source_role,
            jurisdiction=record.jurisdiction,
            published_at=record.published_at,
            retrieved_at=record.retrieved_at,
            source_url=record.source_url,
            title=record.title,
            document_type=record.document_type,
            document_subtype=record.document_subtype,
            language="en",
            text=text,
            text_hash=content_hash(text),
            raw_hash=raw.raw_hash,
            entity_hints=record.entity_hints,
            temporal_hints=[{"kind": "event_time", "value": str(payload.get("event_time", "")), "confidence": 0.75}] if isinstance(payload, dict) else [],
            metadata={**record.metadata, "legacy_source_doc_id": str(payload.get("source_doc_id", "")) if isinstance(payload, dict) else ""},
            compatibility=self.compatibility(record),
        )
        return doc, SourceAdapterDiagnostics(records_normalized=1)

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "sec_edgar_source_manifest"),
            event_family="cybersecurity_material_incidents_8k",
            claim_schema="cyber_8k_watch_claims",
            dimensions=[
                CompatibilityDimension(name="source_authority_confidence", score=0.9, basis="regulatory source manifest"),
                CompatibilityDimension(name="document_text_quality", score=0.9, basis="normalized filing text"),
                CompatibilityDimension(name="evidence_addressability", score=0.95, basis="character offsets"),
                CompatibilityDimension(name="metadata_completeness", score=0.85, basis="filing manifest fields"),
                CompatibilityDimension(name="provenance_completeness", score=0.9, basis="source document ids"),
                CompatibilityDimension(name="language_support", score=0.9, basis="English filing text"),
            ],
        )


class Cyber8KEventDetector:
    name = "cyber_8k_event_detector"
    event_family = "cybersecurity_material_incidents_8k"

    def detect(self, doc: NormalizedSourceDocument):
        payload = doc.metadata.get("source_document", {})
        legacy_event_id = _norm(payload.get("event_id")) if isinstance(payload, dict) else ""
        item_numbers = _norm(payload.get("item_numbers")) if isinstance(payload, dict) else ""
        is_item_105 = "1.05" in item_numbers or "item 1.05" in doc.text.lower()
        if not is_item_105:
            return [], EventDetectorDiagnostics(documents_total=1, skipped_reasons={"not_item_105": 1})
        candidate = EventCandidate(
            event_candidate_id=legacy_event_id or stable_id("cyber_8k_event_candidate", doc.source_doc_id),
            event_family=self.event_family,
            event_type="cybersecurity",
            event_subtype="sec_8_k_item_1_05",
            source_doc_id=doc.source_doc_id,
            entity_candidates=doc.entity_hints,
            temporal_hints=doc.temporal_hints,
            detection_confidence=0.92,
            detection_method=self.name,
            evidence_span_id=stable_id("evidence_span", doc.source_doc_id, "item_105"),
            source_role=doc.source_role,
            metadata={"legacy_event_id": legacy_event_id, "legacy_source_doc_id": doc.metadata.get("legacy_source_doc_id", "")},
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        score = 0.9 if "item 1.05" in doc.text.lower() else 0.5
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family=self.event_family,
            claim_schema="cyber_8k_watch_claims",
            dimensions=[
                CompatibilityDimension(name="event_detection_confidence", score=score, basis="Item 1.05 signal"),
                CompatibilityDimension(name="entity_hint_quality", score=0.8 if doc.entity_hints else 0.2, basis="filing entity hints"),
                CompatibilityDimension(name="temporal_resolution_confidence", score=0.75 if doc.temporal_hints else 0.2, basis="filing accepted time"),
            ],
        )


class Cyber8KClaimExtractor:
    name = "cyber_8k_claim_extractor"
    claim_schema = "cyber_8k_watch_claims"

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        payload = dict(doc.metadata.get("source_document", {}))
        payload["text"] = doc.text
        legacy_claims, legacy_spans = parse_cyber_8k_document(payload)
        spans_by_id = {span.evidence_span_id: span for span in legacy_spans}
        claims: list[GenericClaim] = []
        spans: list[GenericEvidenceSpan] = []
        for legacy_claim in legacy_claims:
            claims.append(
                GenericClaim(
                    claim_id=legacy_claim.claim_id,
                    event_candidate_id=event_candidate.event_candidate_id if event_candidate else "",
                    event_id=legacy_claim.event_id,
                    source_doc_id=legacy_claim.source_doc_id,
                    field_name=legacy_claim.field_name,
                    value=legacy_claim.value,
                    value_type=legacy_claim.value_type,
                    confidence=legacy_claim.confidence,
                    method=legacy_claim.method,
                    evidence_span_id=legacy_claim.evidence_span_id,
                    review_status="needs_review",
                    claim_kind="source_assertion",
                    claim_truth_status="asserted_by_source",
                    source_authority_level=doc.source_authority_level,
                    source_role=doc.source_role,
                    compatibility_confidence=0.85,
                    metadata={"source_system": doc.source_system, "generic_plugin": self.name},
                )
            )
            legacy_span = spans_by_id.get(legacy_claim.evidence_span_id)
            if legacy_span is not None:
                spans.append(
                    GenericEvidenceSpan(
                        evidence_span_id=legacy_span.evidence_span_id,
                        source_doc_id=legacy_span.source_doc_id,
                        claim_id=legacy_span.claim_id,
                        evidence_text=legacy_span.evidence_text,
                        start_char=legacy_span.start_char,
                        end_char=legacy_span.end_char,
                        source_url=legacy_span.source_url,
                        source_role=doc.source_role,
                        metadata={"source_system": doc.source_system, "generic_plugin": self.name},
                    )
                )
        diagnostics = ClaimExtractorDiagnostics(
            documents_total=1,
            claims_total=len(claims),
            evidence_spans_total=len(spans),
            event_candidates_total=1 if event_candidate else 0,
            counts_by_field={claim.field_name: sum(1 for row in claims if row.field_name == claim.field_name) for claim in claims},
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
            event_family="cybersecurity_material_incidents_8k",
            claim_schema=self.claim_schema,
            dimensions=[
                CompatibilityDimension(name="claim_schema_alignment", score=0.9, basis="Cyber 8-K claim schema"),
                CompatibilityDimension(name="claim_extraction_confidence", score=0.75, basis="deterministic parser baseline"),
                CompatibilityDimension(name="reviewability", score=0.9, basis="evidence-backed spans"),
            ],
            known_risks=["field_precision_varies_by_claim"],
        )


def _frame_from_dataclasses(rows: Iterable[object]) -> pd.DataFrame:
    return pd.DataFrame([row.to_dict() if hasattr(row, "to_dict") else dict(row) for row in rows])


def run_cyber_8k_plugin_manifest(
    documents_manifest,
    *,
    claims_out=None,
    evidence_out=None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    adapter = Cyber8KManifestSourceAdapter(documents_manifest)
    query = SourceQuery(query_id=Path(documents_manifest).stem, source_system="sec_edgar_source_manifest")
    report = run_source_to_extraction(
        source_adapter=adapter,
        query=query,
        event_detector=Cyber8KEventDetector(),
        claim_extractor=Cyber8KClaimExtractor(),
    )
    claims_df = _frame_from_dataclasses(report.artifacts.get("claims", []))
    evidence_df = _frame_from_dataclasses(report.artifacts.get("evidence_spans", []))
    if not claims_df.empty and "metadata" in claims_df.columns:
        claims_df["source_system"] = "sec_edgar_source_manifest"
    if claims_out is not None:
        ensure_parent(claims_out)
        claims_df.to_csv(claims_out, index=False)
    if evidence_out is not None:
        ensure_parent(evidence_out)
        evidence_df.to_csv(evidence_out, index=False)

    counts_by_field = claims_df["field_name"].value_counts().sort_index().to_dict() if "field_name" in claims_df.columns else {}
    diagnostics = {
        "extraction_path": "generic_plugin",
        "documents_total": int(report.diagnostics.get("documents", 0)),
        "event_candidates_total": int(report.diagnostics.get("event_candidates", 0)),
        "claims_total": int(len(claims_df)),
        "evidence_spans_total": int(len(evidence_df)),
        "counts_by_field": {str(k): int(v) for k, v in counts_by_field.items()},
        "plugin_status": report.status,
        "warnings": list(report.warnings),
    }
    return claims_df, evidence_df, diagnostics
