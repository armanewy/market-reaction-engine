from __future__ import annotations

from pathlib import Path

from mre.cyber_8k_parser import run_cyber_8k_parse_manifest
from mre.cyber_8k_plugin import (
    Cyber8KClaimExtractor,
    Cyber8KEventDetector,
    Cyber8KManifestSourceAdapter,
    run_cyber_8k_plugin_manifest,
)
from mre.generic.sources import SourceQuery


FIXTURE = Path("tests/fixtures/cyber_8k/source_documents.csv")


def test_cyber_8k_plugin_manifest_matches_parser_field_surface():
    direct_claims, direct_evidence, _ = run_cyber_8k_parse_manifest(FIXTURE)
    plugin_claims, plugin_evidence, diagnostics = run_cyber_8k_plugin_manifest(FIXTURE)

    assert diagnostics["extraction_path"] == "generic_plugin"
    assert diagnostics["plugin_status"] == "ok"
    assert diagnostics["claims_total"] == len(plugin_claims)
    assert set(plugin_claims["field_name"]) == set(direct_claims["field_name"])
    assert len(plugin_evidence) == len(direct_evidence)
    assert "source_authority_level" in plugin_claims.columns
    assert "source_role" in plugin_claims.columns


def test_cyber_8k_plugin_adapter_detector_and_extractor_contracts():
    adapter = Cyber8KManifestSourceAdapter(FIXTURE)
    records, discover_diag = adapter.discover(SourceQuery(query_id="fixture", source_system="sec_edgar_source_manifest"))
    raw, fetch_diag = adapter.fetch(records[0])
    doc, normalize_diag = adapter.normalize(raw, records[0])
    candidates, detect_diag = Cyber8KEventDetector().detect(doc)
    result = Cyber8KClaimExtractor().extract(doc, candidates[0])

    assert discover_diag.records_discovered == 2
    assert fetch_diag.records_fetched == 1
    assert normalize_diag.records_normalized == 1
    assert records[0].entity_hints[0]["namespace"] == "ticker"
    assert doc.metadata["legacy_source_doc_id"] == "acme_item_105"
    assert detect_diag.candidates_total == 1
    assert candidates[0].event_family == "cybersecurity_material_incidents_8k"
    assert result.claims
    assert result.evidence_spans
    assert result.claims[0].metadata["generic_plugin"] == "cyber_8k_claim_extractor"


def test_cyber_8k_plugin_writes_claim_and_evidence_outputs(tmp_path):
    claims_out = tmp_path / "claims.csv"
    evidence_out = tmp_path / "evidence.csv"

    claims, evidence, diagnostics = run_cyber_8k_plugin_manifest(FIXTURE, claims_out=claims_out, evidence_out=evidence_out)

    assert claims_out.exists()
    assert evidence_out.exists()
    assert diagnostics["evidence_spans_total"] == len(evidence)
    assert len(claims) > 0
