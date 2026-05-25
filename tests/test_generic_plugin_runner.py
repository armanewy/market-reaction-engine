from __future__ import annotations

import json
import re

import pytest

from mre.generic.claims import ExtractionResult
from mre.generic.compatibility import CompatibilityDimension, CompatibilityReport
from mre.generic.detection import EventDetectorDiagnostics
from mre.generic.events import EventCandidate
from mre.generic.extractors import evidence_for_match, make_claim_with_evidence
from mre.generic.ids import stable_id
from mre.generic.plugin_runner import run_source_to_extraction
from mre.generic.plugins import PluginManifest
from mre.generic.source_adapters import SourceAdapterDiagnostics, content_hash, make_source_doc_id, make_source_record_id
from mre.generic.sources import NormalizedSourceDocument, RawSourceDocument, SourceQuery, SourceRecord


class ToyOfficialAdapter:
    name = "toy_official_adapter"
    manifest = PluginManifest(plugin_name=name, plugin_version="0.1", plugin_kind="source_adapter")

    def __init__(self, *, fail_second_fetch: bool = False, role: str = "canonical"):
        self.fail_second_fetch = fail_second_fetch
        self.role = role

    def discover(self, query: SourceQuery):
        records = [
            SourceRecord(
                source_record_id=make_source_record_id(query.source_system, "one"),
                source_system=query.source_system,
                source_authority_level="official_regulator" if self.role == "canonical" else "unknown",
                source_role=self.role,
            ),
            SourceRecord(
                source_record_id=make_source_record_id(query.source_system, "two"),
                source_system=query.source_system,
                source_authority_level="unknown",
                source_role=self.role,
            ),
        ]
        return records, SourceAdapterDiagnostics(records_discovered=len(records))

    def fetch(self, record: SourceRecord):
        if self.fail_second_fetch and record.source_record_id.endswith(make_source_record_id(record.source_system, "two").split("_", 1)[1]):
            raise RuntimeError("fetch failed")
        text = "Reportable incident affected operations."
        return RawSourceDocument(
            source_record_id=record.source_record_id,
            source_system=record.source_system,
            raw_bytes_or_text=text,
            raw_hash=content_hash(text),
        ), SourceAdapterDiagnostics(records_fetched=1)

    def normalize(self, raw: RawSourceDocument, record: SourceRecord | None = None):
        record = record or SourceRecord(source_record_id=raw.source_record_id, source_system=raw.source_system)
        text = str(raw.raw_bytes_or_text)
        return NormalizedSourceDocument(
            source_doc_id=make_source_doc_id(raw.source_system, raw.source_record_id),
            source_record_id=raw.source_record_id,
            source_system=raw.source_system,
            source_authority_level=record.source_authority_level,
            source_role=record.source_role,
            text=text,
            text_hash=content_hash(text),
            raw_hash=raw.raw_hash,
        ), SourceAdapterDiagnostics(records_normalized=1)

    def compatibility(self, value: object):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=getattr(value, "source_system", "toy"),
            readiness={"exploration": 0.8 if self.role == "canonical" else 0.45},
            dimensions=[CompatibilityDimension(name="document_text_quality", score=0.8 if self.role == "canonical" else 0.45, basis="toy")],
        )


class ToyDetector:
    name = "toy_detector"
    event_family = "toy_incident"

    def detect(self, doc: NormalizedSourceDocument):
        match = re.search("Reportable incident", doc.text)
        if not match:
            return [], EventDetectorDiagnostics(documents_total=1)
        candidate = EventCandidate(
            event_candidate_id=stable_id("event_candidate", doc.source_doc_id),
            event_family=self.event_family,
            event_type="incident",
            event_subtype="",
            source_doc_id=doc.source_doc_id,
            detection_confidence=0.8,
            detection_method=self.name,
            source_role=doc.source_role,
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(plugin_name=self.name, dimensions=[CompatibilityDimension(name="event_detection_confidence", score=0.8, basis="toy")])


class ToyExtractor:
    name = "toy_extractor"
    claim_schema = "toy_claims"

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        match = re.search("affected operations", doc.text)
        claims = []
        spans = []
        if match:
            evidence_text, start, end = evidence_for_match(doc.text, match)
            claim, span = make_claim_with_evidence(
                source_doc_id=doc.source_doc_id,
                event_candidate_id=event_candidate.event_candidate_id if event_candidate else "",
                field_name="impact_language",
                value=evidence_text,
                value_type="string",
                method=self.name,
                confidence=0.8,
                evidence_text=evidence_text,
                start_char=start,
                end_char=end,
                source_role=doc.source_role,
                source_authority_level=doc.source_authority_level,
            )
            claims.append(claim)
            spans.append(span)
        return ExtractionResult(source_doc_id=doc.source_doc_id, extractor_name=self.name, claim_schema=self.claim_schema, claims=claims, evidence_spans=spans)

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(plugin_name=self.name, dimensions=[CompatibilityDimension(name="claim_extraction_confidence", score=0.8, basis="toy")])


def test_plugin_runner_official_flow_produces_artifacts():
    report = run_source_to_extraction(
        source_adapter=ToyOfficialAdapter(),
        query=SourceQuery(query_id="q1", source_system="toy_source"),
        event_detector=ToyDetector(),
        claim_extractor=ToyExtractor(),
    )

    assert report.status == "ok"
    assert report.diagnostics["documents"] == 2
    assert report.diagnostics["event_candidates"] == 2
    assert report.diagnostics["claims"] == 2
    assert report.artifacts["claims"][0].source_role == "canonical"
    json.dumps(report.to_dict())


def test_plugin_runner_weak_flow_still_runs_with_lower_readiness():
    report = run_source_to_extraction(
        source_adapter=ToyOfficialAdapter(role="early_signal"),
        query=SourceQuery(query_id="q2", source_system="toy_source"),
        claim_extractor=ToyExtractor(),
    )

    assert report.status == "ok"
    assert report.diagnostics["claims"] == 2
    assert report.compatibility_reports[0].readiness["exploration"] == 0.45
    assert report.artifacts["claims"][0].source_role == "early_signal"


def test_plugin_runner_continues_after_record_failure():
    report = run_source_to_extraction(
        source_adapter=ToyOfficialAdapter(fail_second_fetch=True),
        query=SourceQuery(query_id="q3", source_system="toy_source"),
        event_detector=ToyDetector(),
        claim_extractor=ToyExtractor(),
    )

    assert report.status == "partial"
    assert report.diagnostics["documents"] == 1
    assert any("fetch_failed" in warning for warning in report.warnings)


def test_make_claim_with_evidence_requires_source_doc_id():
    with pytest.raises(ValueError):
        make_claim_with_evidence(
            source_doc_id="",
            field_name="field",
            value=True,
            value_type="boolean",
            method="toy",
            confidence=0.5,
            evidence_text="text",
            start_char=0,
            end_char=4,
        )
