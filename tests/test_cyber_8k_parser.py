from __future__ import annotations

import pandas as pd

from mre.cyber_8k_parser import parse_cyber_8k_document, run_cyber_8k_parse_manifest
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, title: str = "Form 8-K Item 1.05") -> SourceDocument:
    return SourceDocument(
        source_doc_id="doc1",
        ticker="ACME",
        event_id="event1",
        event_time=pd.Timestamp("2024-01-02T16:05:00"),
        event_type="cybersecurity",
        event_subtype="sec_8_k_item_1_05",
        release_session="after_close",
        source_type="sec_primary_filing",
        source_url="https://sec.test/acme",
        title=title,
        text=text,
    )


def test_cyber_8k_parser_extracts_claims_and_valid_offsets():
    text = (
        "Item 1.05 Material Cybersecurity Incident. "
        "On January 1, 2024, ACME became aware of a ransomware incident involving a third-party vendor. "
        "The incident caused operational disruption and exposed customer data. "
        "On January 2, 2024, ACME determined the incident was material. "
        "The financial impact has not yet been determined."
    )

    claims, spans = parse_cyber_8k_document(_doc(text))
    fields = {claim.field_name for claim in claims}

    assert {
        "item_105_flag",
        "ransomware_mentioned",
        "third_party_vendor_mentioned",
        "customer_data_exposure_mentioned",
        "operational_disruption_mentioned",
        "materiality_determination_date",
        "impact_unknown_or_not_determined",
    }.issubset(fields)
    by_field = {claim.field_name: claim for claim in claims}
    assert by_field["materiality_determination_date"].value == "2024-01-02"
    for span in spans:
        assert text[span.start_char : span.end_char] == span.evidence_text


def test_cyber_8k_parser_detects_amendment_and_no_material_impact():
    claims, _ = parse_cyber_8k_document(
        _doc(
            "This Form 8-K/A amendment updates the prior Item 1.05 disclosure. "
            "The incident did not have a material impact and is not reasonably likely to materially impact results of operations."
        )
    )

    fields = {claim.field_name for claim in claims}
    assert "amendment_flag" in fields
    assert "no_material_impact_language" in fields
    assert "reasonably_likely_material_impact_language" not in fields


def test_cyber_8k_parser_treats_not_reasonably_likely_as_no_material_impact():
    claims, _ = parse_cyber_8k_document(
        _doc(
            "Item 1.05 Material Cybersecurity Incident. "
            "The incident is not reasonably likely to materially impact the Company's financial condition or results of operations."
        )
    )

    fields = {claim.field_name for claim in claims}
    assert "no_material_impact_language" in fields
    assert "reasonably_likely_material_impact_language" not in fields


def test_cyber_8k_parser_detects_has_not_had_material_impact():
    claims, _ = parse_cyber_8k_document(
        _doc(
            "Item 1.05 Material Cybersecurity Incident. "
            "As of the date of this filing, the incident has not had a material impact on the Company's operations."
        )
    )

    fields = {claim.field_name for claim in claims}
    assert "no_material_impact_language" in fields


def test_cyber_8k_parser_suppresses_heading_only_materiality_language():
    claims, _ = parse_cyber_8k_document(_doc("Item 1.05 Material Cybersecurity Incident."))

    fields = {claim.field_name for claim in claims}
    assert "item_105_flag" in fields
    assert "materiality_language" not in fields


def test_cyber_8k_parser_uses_amendment_metadata_not_generic_update_text():
    generic_update_claims, _ = parse_cyber_8k_document(
        _doc(
            "Item 1.05 Material Cybersecurity Incident. "
            "The Company is providing updates on the incident status page."
        )
    )
    fields = {claim.field_name for claim in generic_update_claims}
    assert "amendment_flag" not in fields

    metadata_claims, _ = parse_cyber_8k_document(
        {
            "source_doc_id": "doc-8ka",
            "ticker": "ACME",
            "event_id": "event1",
            "event_time": "2024-01-02T16:05:00",
            "event_type": "cybersecurity",
            "event_subtype": "sec_8_k_item_1_05",
            "release_session": "after_close",
            "source_type": "sec_primary_filing",
            "source_url": "https://sec.test/acme",
            "title": "ACME Form 8-K/A",
            "form": "8-K/A",
            "text": "Item 1.05 Material Cybersecurity Incident.",
        }
    )
    fields = {claim.field_name for claim in metadata_claims}
    assert "amendment_flag" in fields


def test_cyber_8k_parser_keeps_customer_data_conservative():
    employee_claims, _ = parse_cyber_8k_document(
        _doc(
            "Item 1.05 Material Cybersecurity Incident. "
            "The threat actor exfiltrated information from employee email accounts and attached documents."
        )
    )
    assert "customer_data_exposure_mentioned" not in {claim.field_name for claim in employee_claims}

    customer_claims, _ = parse_cyber_8k_document(
        _doc(
            "Item 1.05 Material Cybersecurity Incident. "
            "The company found files containing protected health information (PHI) and personally identifiable information (PII)."
        )
    )
    assert "customer_data_exposure_mentioned" in {claim.field_name for claim in customer_claims}


def test_cyber_8k_parser_emits_no_claim_without_evidence():
    claims, spans = parse_cyber_8k_document(_doc("The company filed a routine current report."))

    assert claims == []
    assert spans == []


def test_run_cyber_8k_parse_manifest_writes_outputs(tmp_path):
    manifest = tmp_path / "source_documents.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "doc1",
                "ticker": "ACME",
                "event_id": "event1",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "cybersecurity",
                "event_subtype": "sec_8_k_item_1_05",
                "release_session": "after_close",
                "source_type": "sec_primary_filing",
                "source_url": "https://sec.test/acme",
                "text": "Item 1.05 Material Cybersecurity Incident. ACME experienced operational disruption.",
            }
        ],
    )

    claims, evidence, diagnostics = run_cyber_8k_parse_manifest(
        manifest,
        claims_out=tmp_path / "claims.csv",
        evidence_out=tmp_path / "evidence.csv",
    )

    assert not claims.empty
    assert not evidence.empty
    assert diagnostics["documents_with_claims"] == 1
    assert (tmp_path / "claims.csv").exists()
    assert (tmp_path / "evidence.csv").exists()
