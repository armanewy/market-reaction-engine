from __future__ import annotations

import pandas as pd

from mre.biotech_catalysts import (
    build_biotech_catalyst_source_documents,
    biotech_catalyst_readiness_summary,
    parse_biotech_catalyst_document,
    parse_biotech_catalyst_manifest,
    validate_biotech_catalyst_parser,
)
from mre.corpus import make_domain_event_template
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, event_id: str = "XYZ_biotech_1") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-01-02 16:05:00"),
        event_type="regulatory",
        event_subtype="biotech_catalyst",
        release_session="after_close",
        source_type="company_press_release",
        source_url="https://ir.test/biotech.htm",
        title="XYZ biotech catalyst",
        text=text,
    )


def test_fast_track_designation_is_not_lumped_with_approval():
    facts = parse_biotech_catalyst_document(
        _doc(
            "XYZ announced that the FDA granted Fast Track designation to ABC-123 "
            "for the treatment of pulmonary arterial hypertension."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "fast_track_designation"
    assert by_name["fda_action"].value == "fast_track_designation"
    assert "designation_only_weaker_signal" in by_name["parser_quality_flags"].value


def test_corpus_domain_template_contains_biotech_catalyst_fields(tmp_path):
    df = make_domain_event_template("biotech_fda_clinical_catalyst", tmp_path / "template.csv", tickers=["XYZ"])
    assert df.loc[0, "event_family"] == "biotech_fda_clinical_catalyst"
    assert "biotech_catalyst_event_type" in df.columns
    assert "binary_catalyst_flag" in df.columns
    assert "pipeline_concentration_required_flag" in df.columns


def test_phase_3_topline_success_extracts_endpoint_and_stats(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_phase3_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_phase3_2024",
                "event_time": "2024-03-01T06:30:00",
                "event_type": "clinical_trial",
                "event_subtype": "phase_3_readout",
                "release_session": "before_open",
                "source_type": "company_press_release",
                "source_url": "https://ir.test/phase3",
                "title": "XYZ Phase 3 readout",
                "text": (
                    "XYZ reported topline results from the Phase 3 PIVOTAL trial of ABC-123 "
                    "in patients with relapsed lymphoma. The trial met its primary endpoint "
                    "of progression-free survival with p=0.004 and hazard ratio 0.62. "
                    "No new safety signals were observed. ClinicalTrials.gov identifier NCT01234567."
                ),
            }
        ],
    )

    facts, features, events = parse_biotech_catalyst_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    assert "endpoint_met" in set(facts["fact_name"])
    assert features.loc[0, "biotech_catalyst_event_type"] == "pivotal_trial_readout"
    assert features.loc[0, "clinical_trial_readout_flag"] == True
    assert features.loc[0, "binary_catalyst_flag"] == True
    assert features.loc[0, "trial_success_flag"] == True
    assert features.loc[0, "event_direction_pre_price"] == "positive"
    assert features.loc[0, "nct_id"] == "NCT01234567"
    assert round(float(features.loc[0, "hazard_ratio"]), 2) == 0.62
    assert events.loc[0, "event_family"] == "biotech_fda_clinical_catalyst"
    assert events.loc[0, "review_status"] == "unreviewed"


def test_crl_and_trial_halt_are_negative_binary_catalysts(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_crl_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_crl_2024",
                "event_time": "2024-04-01T16:05:00",
                "release_session": "after_close",
                "source_type": "sec_exhibit",
                "source_url": "https://sec.test/crl",
                "text": "XYZ received a Complete Response Letter from the FDA for ABC-123 for the treatment of lymphoma.",
            },
            {
                "source_doc_id": "XYZ_hold_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_hold_2024",
                "event_time": "2024-05-01T16:05:00",
                "release_session": "after_close",
                "source_type": "company_press_release",
                "source_url": "https://ir.test/hold",
                "text": "The FDA placed a clinical hold on the Phase 2 trial of XYZ-789 after serious adverse events were observed.",
            },
        ],
    )
    _, features, _ = parse_biotech_catalyst_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )
    by_event = features.set_index("event_id")
    assert by_event.loc["XYZ_crl_2024", "biotech_catalyst_event_type"] == "fda_complete_response_letter"
    assert by_event.loc["XYZ_crl_2024", "regulatory_decision_flag"] == True
    assert by_event.loc["XYZ_crl_2024", "binary_catalyst_flag"] == True
    assert by_event.loc["XYZ_crl_2024", "event_direction_pre_price"] == "negative"
    assert by_event.loc["XYZ_hold_2024", "biotech_catalyst_event_type"] == "trial_halt"
    assert by_event.loc["XYZ_hold_2024", "safety_negative_flag"] == True
    assert by_event.loc["XYZ_hold_2024", "trial_failure_flag"] == True


def test_enrollment_and_conference_notice_not_mistaken_for_readout():
    facts = parse_biotech_catalyst_document(
        _doc(
            "XYZ completed enrollment in its Phase 3 study of ABC-123 and will present the trial design "
            "at the ASCO annual meeting. No efficacy or safety results were announced."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "unknown"
    assert "enrollment_update_not_binary" in by_name["parser_quality_flags"].value
    assert "publication_or_conference_notice_not_topline" in by_name["parser_quality_flags"].value


def test_approval_pathway_background_not_mistaken_for_accelerated_approval():
    facts = parse_biotech_catalyst_document(
        _doc(
            "FDA granted RMAT designation to ABC-123. Similar to Breakthrough Therapy designation, "
            "RMAT provides opportunities to discuss surrogate endpoints, potential ways to support "
            "accelerated approval and satisfy post-approval requirements, and potential priority review."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "unknown"
    assert "background_approval_language_not_decision" in by_name["parser_quality_flags"].value


def test_about_company_pipeline_boilerplate_not_mistaken_for_readout():
    facts = parse_biotech_catalyst_document(
        _doc(
            "XYZ appoints a new director.\n"
            "About XYZ Therapeutics\n"
            "XYZ is developing oncology candidates. The company's product candidates include ABC-123, "
            "which is currently being evaluated in a Phase 2 clinical trial for lymphoma. "
            "Forward-Looking Statements\n"
            "Actual results could differ materially and negative results may be observed in clinical trials."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "unknown"
    assert "boilerplate_or_risk_factor_not_event" in by_name["parser_quality_flags"].value


def test_previously_announced_pipeline_result_not_new_catalyst():
    facts = parse_biotech_catalyst_document(
        _doc(
            "XYZ reports quarterly business updates.\n"
            "Summary of Business Highlights\n"
            "Pipeline: In September, we announced that our Phase 2 SYCAMORE clinical trial of ABC-123 "
            "met its primary endpoint of safety and demonstrated encouraging exploratory efficacy trends. "
            "We plan to present the Phase 2 data at a medical conference."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "unknown"
    assert "previously_announced_not_new" in by_name["parser_quality_flags"].value


def test_current_phase_2_endpoint_result_is_readout():
    facts = parse_biotech_catalyst_document(
        _doc(
            "XYZ announced topline results from its Phase 2 trial of ABC-123 in lymphoma. "
            "The study met its primary endpoint of objective response rate with p=0.01."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["event_type"].value == "phase_2_readout"
    assert by_name["endpoint_met"].value is True


def test_validate_biotech_parser_against_gold():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "event_type", "value": "phase_3_readout", "unit": "category", "confidence": 0.9, "source_evidence_text": "Phase 3 readout"},
            {"event_id": "E1", "fact_name": "endpoint_met", "value": True, "unit": "boolean", "confidence": 0.9, "source_evidence_text": "met primary endpoint"},
            {"event_id": "E1", "fact_name": "trial_phase", "value": "phase_3", "unit": "category", "confidence": 0.9, "source_evidence_text": "Phase 3"},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "event_type", "expected_value": "phase_3_readout", "unit": "category"},
            {"event_id": "E1", "fact_name": "endpoint_met", "expected_value": True, "unit": "boolean"},
            {"event_id": "E1", "fact_name": "trial_phase", "expected_value": "phase_3", "unit": "category"},
        ]
    )
    errors, report = validate_biotech_catalyst_parser(facts, gold)
    assert set(errors["status"]) == {"ok"}
    assert report["correct_rows"] == 3
    assert report["event_type_precision"] == 1.0


def test_validate_biotech_parser_expected_present_false_allows_unknown_event_type():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "event_type", "value": "unknown", "unit": "category", "confidence": 0.3, "source_evidence_text": "pipeline update"},
            {"event_id": "E2", "fact_name": "event_type", "value": "phase_2_readout", "unit": "category", "confidence": 0.9, "source_evidence_text": "Phase 2 readout"},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "event_type", "expected_value": "unknown", "unit": "category", "expected_present": False, "gold_category": "pipeline_table"},
            {"event_id": "E2", "fact_name": "event_type", "expected_value": "unknown", "unit": "category", "expected_present": False, "gold_category": "pipeline_table"},
        ]
    )
    errors, report = validate_biotech_catalyst_parser(facts, gold)
    by_event = errors.set_index("event_id")
    assert by_event.loc["E1", "status"] == "ok"
    assert by_event.loc["E2", "status"] == "false_positive"
    assert report["gates"]["no_investor_deck_pipeline_table_mistaken_for_new_catalyst"] is False


def test_readiness_summary_requires_reviewed_context_and_audit():
    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": "XYZ",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
                "review_status": "reviewed",
                "biotech_catalyst_event_type": "phase_3_readout" if i < 60 else "fda_complete_response_letter",
                "binary_catalyst_flag": True,
                "regulatory_decision_flag": i >= 60,
                "clinical_trial_readout_flag": i < 60,
                "trial_phase": "phase_3" if i < 60 else "",
                "event_direction_pre_price": "positive" if i < 50 else "negative",
                "market_cap_before_event": 100_000_000,
                "pre_event_market_adjusted_return_20d": 0.05,
                "source_evidence_text": "source-backed",
                "sector_benchmark": "XBI",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    summary = biotech_catalyst_readiness_summary(pd.DataFrame(rows), parser_errors=parser_errors)
    assert summary["reviewed_usable_rows"] == 100
    assert summary["binary_catalyst_rows"] == 100
    assert summary["negative_catalyst_rows"] == 50
    assert summary["positive_catalyst_rows"] == 50
    assert summary["gates"]["reviewed_usable_events_80_min"] is True
    assert summary["gates"]["parser_audit_pass"] is True
    assert summary["decision"] == "model-ready"


def test_source_document_builder_combines_sec_and_manual_manifest(monkeypatch, tmp_path):
    def fake_build_manifest(client, tickers, out_manifest, docs_dir, **kwargs):
        ticker = tickers[0]
        df = pd.DataFrame(
            [
                {
                    "source_doc_id": f"{ticker}_sec_doc",
                    "ticker": ticker,
                    "event_id": f"{ticker}_event",
                    "event_time": "2024-01-01T16:05:00",
                    "event_type": "filing",
                    "event_subtype": "sec_8_k",
                    "release_session": "after_close",
                    "source_type": "sec_exhibit",
                    "source_url": "https://sec.test/doc.htm",
                    "title": "doc",
                    "path": "doc.txt",
                    "text": "",
                    "fiscal_period_end": "",
                    "sector_benchmark": "XBI",
                    "notes": "",
                }
            ]
        )
        df.to_csv(out_manifest, index=False)
        from mre.ingestion import IngestionDiagnostics

        return df, IngestionDiagnostics(rows_total=1, rows_written=1)

    manual = tmp_path / "manual.csv"
    make_source_docs_template(
        manual,
        rows=[
            {
                "source_doc_id": "manual_fda_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_fda",
                "event_time": "2024-01-03T12:00:00",
                "source_type": "fda",
                "source_url": "https://fda.test/approval",
                "text": "FDA approved ABC-123.",
            }
        ],
    )
    monkeypatch.setattr("mre.biotech_catalysts.build_sec_source_document_manifest", fake_build_manifest)
    out, diag = build_biotech_catalyst_source_documents(
        client=object(),
        tickers=["XYZ"],
        out_manifest=tmp_path / "sources.csv",
        docs_dir=tmp_path / "docs",
        source_manifests=[manual],
    )
    assert set(out["source_doc_id"]) == {"XYZ_sec_doc", "manual_fda_doc"}
    assert out.loc[out["source_doc_id"] == "XYZ_sec_doc", "event_subtype"].iloc[0] == "biotech_fda_clinical_candidate"
    assert diag.rows_written == 2
