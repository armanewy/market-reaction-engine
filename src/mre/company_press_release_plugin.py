from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .generic.claims import ExtractionResult
from .generic.compatibility import CompatibilityDimension, CompatibilityReport
from .generic.compatibility_eval import attach_readiness, summarize_compatibility
from .generic.detection import EventDetectorDiagnostics
from .generic.events import EventCandidate
from .generic.extractors import ClaimExtractorDiagnostics, evidence_for_match, make_claim_with_evidence
from .generic.ids import json_friendly, stable_id
from .generic.plugin_runner import PluginRunReport, run_source_to_extraction
from .generic.plugins import PluginManifest
from .generic.publishers import build_generic_digest, build_generic_static_site, export_generic_api
from .generic.quality import build_generic_quality_report
from .generic.review import make_generic_claim_review_queue
from .generic.source_adapters import SourceAdapterDiagnostics, content_hash, make_source_doc_id, make_source_record_id, normalize_text
from .generic.sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord
from .provenance import build_run_manifest, write_run_manifest


COMPANY_PRESS_RELEASE_PLUGIN_MANIFEST = PluginManifest(
    plugin_name="company_press_release_cyber_experiment",
    plugin_version="0.1.0",
    plugin_kind="pipeline",
    supported_source_systems=["official_company_press_release_manifest"],
    supported_event_families=["cybersecurity_incident_disclosure"],
    supported_claim_schemas=["press_release_cyber_claims"],
    required_capabilities=["local_document_text", "source_url_or_identifier"],
    optional_capabilities=["published_at", "company_identity_hint", "web_domain_hint"],
    known_risks=[
        "company_source_may_be_less_temporally_precise_than_regulatory_filing",
        "claim_language_may_be_public_relations_filtered",
    ],
    output_contracts=["normalized_source_document", "event_candidate", "claim", "evidence_span"],
)

COMPANY_PRESS_RELEASE_MANIFEST_COLUMNS = [
    "source_record_id",
    "source_url",
    "title",
    "published_at",
    "retrieved_at",
    "document_type",
    "document_subtype",
    "source_authority_level",
    "source_role",
    "jurisdiction",
    "company_name",
    "domain",
    "path",
    "text",
]


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


def _records(rows: Iterable[object]) -> list[dict[str, Any]]:
    return [row.to_dict() if hasattr(row, "to_dict") else dict(row) for row in rows]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def _event_rows(report: PluginRunReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in report.artifacts.get("event_candidates", []):
        payload = candidate.to_dict()
        payload["event_id"] = payload.get("event_candidate_id", "")
        payload["status"] = payload.get("status", "candidate")
        rows.append(payload)
    return rows


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path).fillna("")
    return [dict(row) for _, row in frame.iterrows()]


def write_company_press_release_manifest_template(out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "source_record_id": "example-company-pr-001",
                "source_url": "https://example.invalid/company/security-update",
                "title": "Example Company security update",
                "published_at": "2026-05-25T12:00:00Z",
                "retrieved_at": "2026-05-25T13:00:00Z",
                "document_type": "press_release",
                "document_subtype": "security_update",
                "source_authority_level": "official_company",
                "source_role": "canonical",
                "jurisdiction": "US",
                "company_name": "Example Company",
                "domain": "example.invalid",
                "path": "docs/example_security_update.txt",
                "text": "",
            }
        ],
        columns=COMPANY_PRESS_RELEASE_MANIFEST_COLUMNS,
    ).to_csv(path, index=False)
    return path


class CompanyPressReleaseSourceAdapter:
    name = "company_press_release_source_adapter"
    manifest = COMPANY_PRESS_RELEASE_PLUGIN_MANIFEST

    def __init__(self, documents_manifest: str | Path):
        self.documents_manifest = Path(documents_manifest)
        self._manifest_dir = self.documents_manifest.parent
        self._rows_by_record: dict[str, dict[str, Any]] = {}

    def discover(self, query: SourceQuery):
        rows = _read_manifest(self.documents_manifest)
        records: list[SourceRecord] = []
        for index, row in enumerate(rows):
            record_id = _norm(row.get("source_record_id")) or make_source_record_id(
                query.source_system,
                self.documents_manifest.name,
                index,
                row.get("source_url", ""),
                row.get("title", ""),
            )
            company_name = _norm(row.get("company_name"))
            domain = _norm(row.get("domain"))
            entity_hints = []
            if company_name:
                entity_hints.append({"namespace": "company_name", "value": company_name, "label": company_name, "confidence": 0.7})
            if domain:
                entity_hints.append({"namespace": "domain", "value": domain, "label": domain, "confidence": 0.55})
            record = SourceRecord(
                source_record_id=record_id,
                source_system=query.source_system,
                source_url=_norm(row.get("source_url")),
                title=_norm(row.get("title")),
                published_at=_norm(row.get("published_at")),
                retrieved_at=_norm(row.get("retrieved_at")),
                document_type=_norm(row.get("document_type"), default="press_release"),
                document_subtype=_norm(row.get("document_subtype")),
                source_authority_level=_norm(row.get("source_authority_level"), default="official_company"),
                source_role=_norm(row.get("source_role"), default="canonical"),
                jurisdiction=_norm(row.get("jurisdiction")),
                entity_hints=entity_hints,
                metadata={
                    "manifest_row": row,
                    "path": _norm(row.get("path")),
                    "company_name": company_name,
                    "domain": domain,
                },
            )
            self._rows_by_record[record_id] = row
            records.append(record)
        return records, SourceAdapterDiagnostics(records_discovered=len(records))

    def fetch(self, record: SourceRecord):
        row = self._rows_by_record.get(record.source_record_id, {})
        text = _norm(row.get("text"))
        path_text = _norm(row.get("path"))
        if not text and path_text:
            text_path = Path(path_text)
            if not text_path.is_absolute():
                text_path = self._manifest_dir / text_path
            text = text_path.read_text(encoding="utf-8")
        return (
            RawSourceDocument(
                source_record_id=record.source_record_id,
                source_system=record.source_system,
                raw_bytes_or_text=text,
                content_type="text/plain",
                retrieved_at=record.retrieved_at,
                raw_hash=content_hash(text),
                metadata=record.metadata,
            ),
            SourceAdapterDiagnostics(records_fetched=1),
        )

    def normalize(self, raw: RawSourceDocument, record: SourceRecord | None = None):
        record = record or SourceRecord(source_record_id=raw.source_record_id, source_system=raw.source_system)
        text = normalize_text(raw.raw_bytes_or_text)
        temporal_hints = []
        if record.published_at:
            temporal_hints.append(
                {
                    "kind": "published_at",
                    "value": record.published_at,
                    "confidence": 0.45,
                    "basis": "company press release publication metadata",
                }
            )
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
            temporal_hints=temporal_hints,
            metadata={**record.metadata, "source_system": raw.source_system},
            compatibility=self.compatibility(record),
        )
        return doc, SourceAdapterDiagnostics(records_normalized=1)

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "official_company_press_release_manifest"),
            event_family="cybersecurity_incident_disclosure",
            claim_schema="press_release_cyber_claims",
            dimensions=[
                CompatibilityDimension(name="source_authority_confidence", score=0.75, basis="official company source"),
                CompatibilityDimension(name="document_text_quality", score=0.85, basis="plain text press release"),
                CompatibilityDimension(name="evidence_addressability", score=0.9, basis="local text offsets"),
                CompatibilityDimension(name="metadata_completeness", score=0.55, basis="press release manifest metadata"),
                CompatibilityDimension(name="temporal_resolution_confidence", score=0.45, basis="publication time, not regulatory acceptance time"),
                CompatibilityDimension(name="entity_hint_quality", score=0.6, basis="company name and domain hints"),
                CompatibilityDimension(name="provenance_completeness", score=0.65, basis="local manifest and source URL"),
                CompatibilityDimension(name="language_support", score=0.85, basis="English press release text"),
            ],
            known_risks=["company_controlled_source", "weaker_event_timestamp"],
        )


class CompanyCyberEventDetector:
    name = "company_press_release_cyber_event_detector"
    event_family = "cybersecurity_incident_disclosure"

    def detect(self, doc: NormalizedSourceDocument):
        match = re.search(r"\b(cybersecurity incident|ransomware|unauthorized access|data exposure|security incident)\b", doc.text, flags=re.I)
        if not match:
            return [], EventDetectorDiagnostics(documents_total=1, skipped_reasons={"no_cyber_incident_signal": 1})
        evidence_text, start, end = evidence_for_match(doc.text, match)
        candidate = EventCandidate(
            event_candidate_id=stable_id("event_candidate", doc.source_doc_id, evidence_text),
            event_family=self.event_family,
            event_type="cybersecurity_incident",
            event_subtype="official_company_press_release",
            source_doc_id=doc.source_doc_id,
            entity_candidates=doc.entity_hints,
            temporal_hints=doc.temporal_hints,
            detection_confidence=0.78 if doc.source_role == "canonical" else 0.62,
            detection_method=self.name,
            evidence_span_id=stable_id("evidence_span", doc.source_doc_id, start, end),
            source_role=doc.source_role,
            metadata={"source_system": doc.source_system},
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family=self.event_family,
            claim_schema="press_release_cyber_claims",
            dimensions=[
                CompatibilityDimension(name="event_detection_confidence", score=0.75, basis="press release incident phrasing"),
                CompatibilityDimension(name="entity_hint_quality", score=0.6 if doc.entity_hints else 0.2, basis="company identity hints"),
                CompatibilityDimension(name="temporal_resolution_confidence", score=0.45 if doc.temporal_hints else 0.15, basis="publication metadata"),
            ],
        )


def _negative_customer_context(evidence_text: str) -> bool:
    lowered = evidence_text.lower()
    return any(phrase in lowered for phrase in ["no evidence", "not identified", "has not identified", "no indication"])


_VENDOR_INVOLVEMENT_RE = re.compile(
    r"\b("
    r"vendor(?:[- ]originated)?|"
    r"supplier|"
    r"service provider|"
    r"third[- ]party (?:vendor|supplier|service provider|platform|system|data processor|processor)|"
    r"external system|"
    r"data processor|"
    r"vendor system"
    r")\b",
    flags=re.I,
)
_RESPONSE_PROVIDER_RE = re.compile(
    r"\b("
    r"forensic (?:firm|expert|experts|consultant|consultants)|"
    r"cybersecurity (?:expert|experts|advisor|advisors|consultant|consultants)|"
    r"response (?:team|firm|provider|consultant|consultants)|"
    r"outside counsel|"
    r"investigator|investigators|"
    r"advisor|advisors|"
    r"consultant|consultants"
    r")\b",
    flags=re.I,
)
_INCIDENT_INVOLVEMENT_RE = re.compile(
    r"\b("
    r"involved|originated|accessed|compromised|affected|breached|exposed|"
    r"platform|system|data processor|processor|vendor|supplier|service provider"
    r")\b",
    flags=re.I,
)


def _is_third_party_vendor_evidence(evidence_text: str) -> bool:
    if not _VENDOR_INVOLVEMENT_RE.search(evidence_text):
        return False
    if _RESPONSE_PROVIDER_RE.search(evidence_text) and not _INCIDENT_INVOLVEMENT_RE.search(evidence_text):
        return False
    return True


class CompanyCyberClaimExtractor:
    name = "company_press_release_cyber_claim_extractor"
    claim_schema = "press_release_cyber_claims"

    field_patterns: dict[str, tuple[str, str, object, float]] = {
        "ransomware_mentioned": (r"\bransomware\b", "boolean", True, 0.88),
        "operational_disruption_mentioned": (
            r"\b(disrupted|disruption|operations? (?:were )?affected|operational impact|service outage)\b",
            "boolean",
            True,
            0.8,
        ),
        "third_party_vendor_mentioned": (
            _VENDOR_INVOLVEMENT_RE.pattern,
            "boolean",
            True,
            0.72,
        ),
        "customer_data_exposure_mentioned": (
            r"\b(customer|client|consumer|patient|member|personal information|PHI|PII)\b.{0,80}\b(accessed|exposed|exposure|stolen|affected)\b",
            "boolean",
            True,
            0.76,
        ),
        "impact_unknown_or_not_determined": (
            r"\b(not yet determined|has not yet determined|unable to determine|continues to assess)\b.{0,80}\b(impact|financial impact|scope)\b",
            "boolean",
            True,
            0.74,
        ),
        "no_material_impact_language": (
            r"\b(no material impact|has not had a material impact|not expected to have a material impact|does not currently expect[^.]{0,80}material impact|not reasonably likely to have a material impact)\b",
            "boolean",
            True,
            0.78,
        ),
        "financial_impact_language": (
            r"\b(financial impact|costs? associated with|expenses? associated with|material impact)\b",
            "string",
            "evidence",
            0.68,
        ),
    }

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        claims = []
        spans = []
        counts_by_field: dict[str, int] = {}
        for field_name, (pattern, value_type, value, confidence) in self.field_patterns.items():
            match = re.search(pattern, doc.text, flags=re.I)
            if not match:
                continue
            evidence_text, start, end = evidence_for_match(doc.text, match)
            if field_name == "customer_data_exposure_mentioned" and _negative_customer_context(evidence_text):
                continue
            if field_name == "third_party_vendor_mentioned" and not _is_third_party_vendor_evidence(evidence_text):
                continue
            claim_value = evidence_text if value == "evidence" else value
            claim, span = make_claim_with_evidence(
                source_doc_id=doc.source_doc_id,
                event_candidate_id=event_candidate.event_candidate_id if event_candidate else "",
                field_name=field_name,
                value=claim_value,
                value_type=value_type,
                method=self.name,
                confidence=confidence,
                evidence_text=evidence_text,
                start_char=start,
                end_char=end,
                source_url=doc.source_url,
                source_authority_level=doc.source_authority_level,
                source_role=doc.source_role,
                metadata={"source_system": doc.source_system, "generic_plugin": self.name},
            )
            claims.append(claim)
            spans.append(span)
            counts_by_field[field_name] = counts_by_field.get(field_name, 0) + 1
        diagnostics = ClaimExtractorDiagnostics(
            documents_total=1,
            claims_total=len(claims),
            evidence_spans_total=len(spans),
            event_candidates_total=1 if event_candidate else 0,
            counts_by_field=counts_by_field,
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
            event_family="cybersecurity_incident_disclosure",
            claim_schema=self.claim_schema,
            dimensions=[
                CompatibilityDimension(name="claim_schema_alignment", score=0.72, basis="press release cyber claim fields"),
                CompatibilityDimension(name="claim_extraction_confidence", score=0.65, basis="deterministic press release patterns"),
                CompatibilityDimension(name="reviewability", score=0.9, basis="evidence-backed text offsets"),
            ],
            known_risks=["public_relations_language", "field_precision_requires_review"],
        )


def run_company_press_release_experiment(
    documents_manifest,
    *,
    out_dir,
    auto_accept_min_confidence: float | None = 0.8,
    build_quality_report: bool = True,
    build_static_site: bool = True,
    build_api_export: bool = True,
    build_digest: bool = True,
    write_manifest: bool = True,
) -> dict[str, Any]:
    manifest_path = Path(documents_manifest)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    adapter = CompanyPressReleaseSourceAdapter(manifest_path)
    query = SourceQuery(query_id=manifest_path.stem, source_system="official_company_press_release_manifest", params={"manifest": str(manifest_path)})
    run_report = run_source_to_extraction(
        source_adapter=adapter,
        query=query,
        event_detector=CompanyCyberEventDetector(),
        claim_extractor=CompanyCyberClaimExtractor(),
    )
    compatibility_reports = [attach_readiness(report) for report in run_report.compatibility_reports]
    doc_rows = _records(run_report.artifacts.get("normalized_documents", []))
    event_rows = _event_rows(run_report)
    claim_rows = _records(run_report.artifacts.get("claims", []))
    evidence_rows = _records(run_report.artifacts.get("evidence_spans", []))
    for claim in claim_rows:
        claim.setdefault("source_system", "official_company_press_release_manifest")

    paths: dict[str, str] = {
        "documents": _write_csv(output_dir / "press_release_documents.csv", doc_rows),
        "events": _write_csv(output_dir / "press_release_events.csv", event_rows),
        "claims": _write_csv(output_dir / "press_release_claims.csv", claim_rows),
        "evidence_spans": _write_csv(output_dir / "press_release_evidence_spans.csv", evidence_rows),
    }

    review_queue, review_diagnostics = make_generic_claim_review_queue(
        pd.DataFrame(claim_rows),
        pd.DataFrame(evidence_rows),
        out_path=output_dir / "press_release_claim_review_queue.csv",
        auto_accept_min_confidence=auto_accept_min_confidence,
        require_evidence=True,
    )
    paths["review_queue"] = str(output_dir / "press_release_claim_review_queue.csv")

    quality = None
    if build_quality_report:
        quality = build_generic_quality_report(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            compatibility_reports=compatibility_reports,
            out_json=output_dir / "press_release_quality_report.json",
            out_md=output_dir / "press_release_quality_report.md",
        )
        paths["quality_json"] = str(output_dir / "press_release_quality_report.json")
        paths["quality_md"] = str(output_dir / "press_release_quality_report.md")

    if build_api_export:
        api_paths = export_generic_api(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            out_dir=output_dir / "api",
        )
        paths["api_dir"] = str(output_dir / "api")
        paths.update({f"api_{key}": value for key, value in api_paths.items()})

    if build_static_site:
        source_texts = {row["source_doc_id"]: row.get("text", "") for row in doc_rows if row.get("source_doc_id")}
        site_paths = build_generic_static_site(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            source_texts=source_texts,
            out_dir=output_dir / "site",
            title="Official Company Press Release Cyber Experiment",
        )
        paths["site_dir"] = str(output_dir / "site")
        paths.update({f"site_{key}": value for key, value in site_paths.items()})

    if build_digest:
        digest_path = output_dir / "press_release_digest.md"
        build_generic_digest(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            title="Official Company Press Release Cyber Digest",
            out_path=digest_path,
        )
        paths["digest"] = str(digest_path)

    if write_manifest:
        manifest = build_run_manifest(
            {
                "source_system": "official_company_press_release_manifest",
                "documents_manifest": str(manifest_path),
                "auto_accept_min_confidence": auto_accept_min_confidence,
            },
            [manifest_path],
            extra={"pipeline": "company_press_release_experiment"},
        )
        manifest_output = write_run_manifest(output_dir / "run_manifest.json", manifest)
        paths["run_manifest"] = str(manifest_output)

    report = {
        "status": run_report.status,
        "out_dir": str(output_dir),
        "outputs": paths,
        "diagnostics": run_report.diagnostics,
        "review_diagnostics": review_diagnostics,
        "quality_warnings": [] if quality is None else quality.get("warnings", []),
        "compatibility": [summarize_compatibility(report) for report in compatibility_reports],
        "warnings": run_report.warnings,
    }
    report = json_friendly(report)
    (output_dir / "pipeline_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
