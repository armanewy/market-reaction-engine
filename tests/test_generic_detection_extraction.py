from __future__ import annotations

import json
import re

from mre.generic.claims import ExtractionResult
from mre.generic.compatibility import CompatibilityDimension, CompatibilityReport
from mre.generic.detection import EventDetectorDiagnostics
from mre.generic.events import EventCandidate
from mre.generic.extractors import ClaimExtractorDiagnostics, evidence_for_match, make_claim_with_evidence
from mre.generic.ids import stable_id
from mre.generic.sources import NormalizedSourceDocument


class ToyOfficialIncidentDetector:
    name = "toy_official_incident_detector"
    event_family = "toy_incident"

    def detect(self, doc: NormalizedSourceDocument):
        match = re.search(r"Reportable incident", doc.text, flags=re.I)
        if not match:
            return [], EventDetectorDiagnostics(documents_total=1, skipped_reasons={"no_match": 1})
        candidate = EventCandidate(
            event_candidate_id=stable_id("event_candidate", doc.source_doc_id, match.group(0)),
            event_family=self.event_family,
            event_type="reportable_incident",
            event_subtype="",
            source_doc_id=doc.source_doc_id,
            detection_confidence=0.9,
            detection_method=self.name,
            evidence_span_id=stable_id("evidence_span", doc.source_doc_id, match.start(), match.end()),
            source_role=doc.source_role,
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family=self.event_family,
            dimensions=[CompatibilityDimension(name="event_detection_confidence", score=0.9, basis="toy phrase")],
        )


class ToyEarlySignalDetector(ToyOfficialIncidentDetector):
    name = "toy_early_signal_detector"

    def detect(self, doc: NormalizedSourceDocument):
        match = re.search(r"possible incident", doc.text, flags=re.I)
        if not match:
            return [], EventDetectorDiagnostics(documents_total=1, skipped_reasons={"no_match": 1})
        candidate = EventCandidate(
            event_candidate_id=stable_id("event_candidate", doc.source_doc_id, match.group(0)),
            event_family=self.event_family,
            event_type="possible_incident",
            event_subtype="",
            source_doc_id=doc.source_doc_id,
            detection_confidence=0.45,
            detection_method=self.name,
            source_role=doc.source_role,
        )
        return [candidate], EventDetectorDiagnostics(documents_total=1, candidates_total=1)

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            event_family=self.event_family,
            dimensions=[CompatibilityDimension(name="event_detection_confidence", score=0.45, basis="early phrase")],
        )


class ToyClaimExtractor:
    name = "toy_claim_extractor"
    claim_schema = "toy_claims"

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        claims = []
        spans = []
        for field_name, pattern in {
            "incident_mentioned": r"Reportable incident|possible incident",
            "impact_language": r"affected operations",
        }.items():
            match = re.search(pattern, doc.text, flags=re.I)
            if not match:
                continue
            evidence_text, start, end = evidence_for_match(doc.text, match)
            claim, span = make_claim_with_evidence(
                source_doc_id=doc.source_doc_id,
                event_candidate_id=event_candidate.event_candidate_id if event_candidate else "",
                field_name=field_name,
                value=True if field_name == "incident_mentioned" else evidence_text,
                value_type="boolean" if field_name == "incident_mentioned" else "string",
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
        return ExtractionResult(
            source_doc_id=doc.source_doc_id,
            extractor_name=self.name,
            claim_schema=self.claim_schema,
            claims=claims,
            evidence_spans=spans,
            diagnostics=ClaimExtractorDiagnostics(
                documents_total=1,
                claims_total=len(claims),
                evidence_spans_total=len(spans),
                counts_by_field={claim.field_name: 1 for claim in claims},
            ).to_dict(),
        )

    def compatibility(self, doc: NormalizedSourceDocument):
        return CompatibilityReport(
            plugin_name=self.name,
            source_system=doc.source_system,
            claim_schema=self.claim_schema,
            dimensions=[CompatibilityDimension(name="claim_extraction_confidence", score=0.8, basis="toy rules")],
        )


class ToyAllegationExtractor(ToyClaimExtractor):
    name = "toy_allegation_extractor"

    def extract(self, doc: NormalizedSourceDocument, event_candidate: EventCandidate | None = None):
        match = re.search(r"alleges misconduct", doc.text, flags=re.I)
        if not match:
            return ExtractionResult(source_doc_id=doc.source_doc_id, extractor_name=self.name, claim_schema=self.claim_schema)
        evidence_text, start, end = evidence_for_match(doc.text, match)
        claim, span = make_claim_with_evidence(
            source_doc_id=doc.source_doc_id,
            field_name="allegation_mentioned",
            value=True,
            value_type="boolean",
            method=self.name,
            confidence=0.7,
            evidence_text=evidence_text,
            start_char=start,
            end_char=end,
            claim_kind="allegation",
            claim_truth_status="asserted_by_source",
            source_role=doc.source_role,
            source_authority_level=doc.source_authority_level,
        )
        return ExtractionResult(source_doc_id=doc.source_doc_id, extractor_name=self.name, claim_schema=self.claim_schema, claims=[claim], evidence_spans=[span])


def _doc(text: str, *, role: str = "canonical") -> NormalizedSourceDocument:
    return NormalizedSourceDocument(
        source_doc_id=stable_id("source_doc", text),
        source_record_id="record1",
        source_system="toy_source",
        source_authority_level="official_regulator" if role == "canonical" else "unknown",
        source_role=role,
        text=text,
    )


def test_detector_and_extractor_emit_evidence_backed_objects():
    doc = _doc("Reportable incident affected operations.")
    detector = ToyOfficialIncidentDetector()
    candidates, detector_diagnostics = detector.detect(doc)
    result = ToyClaimExtractor().extract(doc, candidates[0])

    assert detector_diagnostics.candidates_total == 1
    assert len(result.claims) == 2
    assert result.evidence_spans[0].evidence_text in doc.text
    assert doc.text[result.evidence_spans[0].start_char : result.evidence_spans[0].end_char] == result.evidence_spans[0].evidence_text
    json.dumps(result.to_dict())


def test_allegation_claim_does_not_masquerade_as_confirmed_truth():
    result = ToyAllegationExtractor().extract(_doc("A source alleges misconduct.", role="early_signal"))

    assert result.claims[0].claim_kind == "allegation"
    assert result.claims[0].claim_truth_status == "asserted_by_source"


def test_weak_source_remains_extractable_with_lower_compatibility():
    doc = _doc("A source reports possible incident.", role="early_signal")
    detector = ToyEarlySignalDetector()
    candidates, _ = detector.detect(doc)
    compatibility = detector.compatibility(doc)

    assert candidates[0].source_role == "early_signal"
    assert compatibility.dimensions[0].score == 0.45


def test_empty_document_produces_diagnostics_not_crash():
    doc = _doc("No matching text.")
    candidates, diagnostics = ToyOfficialIncidentDetector().detect(doc)
    result = ToyClaimExtractor().extract(doc)

    assert candidates == []
    assert diagnostics.skipped_reasons == {"no_match": 1}
    assert result.claims == []
