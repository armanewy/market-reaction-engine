from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mre.company_press_release_plugin import (
    CompanyCyberClaimExtractor,
    CompanyCyberEventDetector,
    CompanyPressReleaseSourceAdapter,
    run_company_press_release_experiment,
)
from mre.cyber_8k_plugin import Cyber8KEventDetector, Cyber8KManifestSourceAdapter
from mre.generic.compatibility_eval import attach_readiness, dimension_score
from mre.generic.sources import NormalizedSourceDocument, SourceQuery
from mre.generic.toy_plugins import ToyWeakAdapter


FIXTURE = Path("tests/fixtures/company_press_releases/source_documents.csv")
CYBER_FIXTURE = Path("tests/fixtures/cyber_8k/source_documents.csv")


def _first_press_release_doc():
    adapter = CompanyPressReleaseSourceAdapter(FIXTURE)
    records, _ = adapter.discover(SourceQuery(query_id="fixture", source_system="official_company_press_release_manifest"))
    raw, _ = adapter.fetch(records[0])
    doc, _ = adapter.normalize(raw, records[0])
    return adapter, records[0], doc


def _extract_fields(text: str) -> set[str]:
    doc = NormalizedSourceDocument(
        source_doc_id="doc",
        source_record_id="record",
        source_system="official_company_press_release_manifest",
        source_authority_level="official_company",
        source_role="canonical",
        source_url="https://example.invalid",
        text=text,
    )
    result = CompanyCyberClaimExtractor().extract(doc)
    return {claim.field_name for claim in result.claims}


def test_press_release_adapter_normalizes_source_with_generic_hints():
    adapter, record, doc = _first_press_release_doc()

    assert record.source_authority_level == "official_company"
    assert record.source_role == "canonical"
    assert {hint["namespace"] for hint in record.entity_hints} == {"company_name", "domain"}
    assert doc.source_system == "official_company_press_release_manifest"
    assert doc.temporal_hints[0]["kind"] == "published_at"
    assert doc.temporal_hints[0]["confidence"] == 0.45
    assert doc.text_hash
    assert dimension_score(adapter.compatibility(record), "metadata_completeness") == 0.55


def test_press_release_detector_and_extractor_emit_evidence_backed_claims():
    _, _, doc = _first_press_release_doc()
    candidates, detect_diag = CompanyCyberEventDetector().detect(doc)
    result = CompanyCyberClaimExtractor().extract(doc, candidates[0])

    fields = {claim.field_name for claim in result.claims}
    assert detect_diag.candidates_total == 1
    assert "ransomware_mentioned" in fields
    assert "operational_disruption_mentioned" in fields
    assert "third_party_vendor_mentioned" in fields
    assert "customer_data_exposure_mentioned" in fields
    assert result.evidence_spans
    for span in result.evidence_spans:
        assert span.evidence_text in doc.text
        assert doc.text[span.start_char : span.end_char].strip()
    assert all(claim.source_authority_level == "official_company" for claim in result.claims)


def test_third_party_vendor_suppresses_response_provider_false_positives():
    assert "third_party_vendor_mentioned" not in _extract_fields(
        "The company engaged a third-party forensic firm to assist with the investigation."
    )
    assert "third_party_vendor_mentioned" not in _extract_fields(
        "The company is working with third-party cybersecurity experts to restore affected systems."
    )


def test_third_party_vendor_detects_vendor_involvement():
    assert "third_party_vendor_mentioned" in _extract_fields(
        "A third-party service provider was involved in the incident."
    )
    assert "third_party_vendor_mentioned" in _extract_fields(
        "The vendor system was accessed during the security incident."
    )


def test_customer_data_suppresses_customer_support_false_positives():
    assert "customer_data_exposure_mentioned" not in _extract_fields(
        "The dedicated customer inquiry form for the security incident remained available for affected customers."
    )
    assert "customer_data_exposure_mentioned" not in _extract_fields(
        "Customers may contact a dedicated call center for additional information about the incident."
    )
    assert "customer_data_exposure_mentioned" not in _extract_fields(
        "The company had not yet determined that any personal customer data was involved."
    )


def test_customer_data_detects_actual_data_exposure():
    assert "customer_data_exposure_mentioned" in _extract_fields(
        "Customer personal information may have been accessed during the incident."
    )
    assert "customer_data_exposure_mentioned" in _extract_fields(
        "The files contained PHI and PII related to affected patients."
    )


def test_press_release_experiment_writes_generic_artifacts(tmp_path):
    report = run_company_press_release_experiment(FIXTURE, out_dir=tmp_path / "press_release", auto_accept_min_confidence=0.8)
    out_dir = Path(report["out_dir"])

    assert report["status"] == "ok"
    assert report["diagnostics"]["documents"] == 2
    assert report["diagnostics"]["claims"] >= 5
    assert (out_dir / "press_release_documents.csv").exists()
    assert (out_dir / "press_release_events.csv").exists()
    assert (out_dir / "press_release_claims.csv").exists()
    assert (out_dir / "press_release_evidence_spans.csv").exists()
    assert (out_dir / "press_release_claim_review_queue.csv").exists()
    assert (out_dir / "press_release_quality_report.json").exists()
    assert (out_dir / "press_release_quality_report.md").exists()
    assert (out_dir / "api" / "events.json").exists()
    assert (out_dir / "site" / "index.html").exists()
    assert (out_dir / "press_release_digest.md").exists()
    assert (out_dir / "run_manifest.json").exists()
    assert (out_dir / "pipeline_report.json").exists()

    review_queue = pd.read_csv(out_dir / "press_release_claim_review_queue.csv")
    assert "machine_high_confidence" in set(review_queue["review_status"])
    quality = json.loads((out_dir / "press_release_quality_report.json").read_text(encoding="utf-8"))
    assert quality["source_authority_level_counts"]["official_company"] == len(review_queue)
    assert quality["source_system_counts"]["official_company_press_release_manifest"] == len(review_queue)


def test_press_release_compatibility_sits_between_weak_toy_and_cyber_patterns():
    press_adapter, press_record, _ = _first_press_release_doc()
    press_report = press_adapter.compatibility(press_record)

    weak_report = ToyWeakAdapter().compatibility(SourceQuery(query_id="weak", source_system="toy_weak"))
    cyber_adapter = Cyber8KManifestSourceAdapter(CYBER_FIXTURE)
    cyber_records, _ = cyber_adapter.discover(SourceQuery(query_id="cyber", source_system="sec_edgar_source_manifest"))
    cyber_raw, _ = cyber_adapter.fetch(cyber_records[0])
    cyber_doc, _ = cyber_adapter.normalize(cyber_raw, cyber_records[0])
    cyber_source_report = cyber_adapter.compatibility(cyber_records[0])
    cyber_detector_report = Cyber8KEventDetector().compatibility(cyber_doc)

    assert dimension_score(weak_report, "source_authority_confidence") < dimension_score(press_report, "source_authority_confidence")
    assert dimension_score(press_report, "source_authority_confidence") < dimension_score(cyber_source_report, "source_authority_confidence")
    assert dimension_score(press_report, "metadata_completeness") < dimension_score(cyber_source_report, "metadata_completeness")
    assert dimension_score(press_report, "temporal_resolution_confidence") < dimension_score(
        cyber_detector_report,
        "temporal_resolution_confidence",
    )

    press_ready = attach_readiness(press_report).readiness
    weak_ready = attach_readiness(weak_report).readiness
    assert press_ready["user_facing_draft"] > weak_ready["user_facing_draft"]
