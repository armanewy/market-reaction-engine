from __future__ import annotations

import pandas as pd

from mre.corpus import make_domain_event_template, normalize_domain
from mre.cybersecurity_incidents import (
    cybersecurity_incident_readiness_summary,
    cybersecurity_timestamp_duplicate_audit,
    enrich_cybersecurity_incident_context,
    parse_cybersecurity_incident_document,
    parse_cybersecurity_incident_manifest,
    validate_cybersecurity_incident_parser,
)
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, event_id: str = "XYZ_cyber_2024", title: str = "Item 1.05 Material Cybersecurity Incident") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-01-02 16:05:00"),
        event_type="cybersecurity",
        event_subtype="sec_8_k_item_1_05",
        release_session="after_close",
        source_type="sec_8k",
        source_url="https://sec.test/xyz-8k.htm",
        title=title,
        text=text,
    )


def test_domain_template_contains_item_105_fields(tmp_path):
    assert normalize_domain("cyber_item_105") == "cybersecurity_material_incidents_8k"
    df = make_domain_event_template("cybersecurity_material_incidents_8k", tmp_path / "template.csv", tickers=["XYZ"])
    assert df.loc[0, "event_family"] == "cybersecurity_material_incidents_8k"
    assert "item_105_flag" in df.columns
    assert "operational_disruption_flag" in df.columns
    assert "pre_event_volatility_20d" in df.columns


def test_item_105_ransomware_operational_disruption_parses_negative_material_event(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "xyz_cyber_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_cyber_2024",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "cybersecurity",
                "event_subtype": "sec_8_k_item_1_05",
                "release_session": "after_close",
                "source_type": "sec_8k",
                "source_url": "https://sec.test/xyz-8k",
                "title": "Item 1.05 Material Cybersecurity Incident",
                "text": (
                    "Item 1.05 Material Cybersecurity Incident. On January 1, 2024, XYZ became aware "
                    "of a ransomware incident that encrypted certain systems. On January 2, 2024, "
                    "XYZ determined the incident was material. The company took systems offline and "
                    "experienced operational disruption and business interruption."
                ),
            }
        ],
    )

    facts, features, events = parse_cybersecurity_incident_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    by_name = facts.set_index("fact_name")
    assert by_name.loc["item_105_flag", "value"] == True
    assert features.loc[0, "cybersecurity_incident_event_type"] == "ransomware"
    assert features.loc[0, "ransomware_flag"] == True
    assert features.loc[0, "operational_disruption_flag"] == True
    assert features.loc[0, "incident_discovery_date"] == "2024-01-01"
    assert features.loc[0, "materiality_determination_date"] == "2024-01-02"
    assert features.loc[0, "event_direction_pre_price"] == "negative"
    assert events.loc[0, "event_family"] == "cybersecurity_material_incidents_8k"


def test_generic_risk_and_vendor_advisory_are_hard_negatives():
    risk_facts = parse_cybersecurity_incident_document(
        _doc(
            "The company describes cybersecurity risk management and risk factors. "
            "No cybersecurity incident has been identified.",
            title="Cybersecurity Risk Management",
        )
    )
    vendor_facts = parse_cybersecurity_incident_document(
        _doc(
            "A third-party vendor published a security advisory for a CVE vulnerability. "
            "The notice does not state that XYZ systems were affected.",
            title="Vendor security advisory",
        )
    )

    risk_by_name = {fact.fact_name: fact for fact in risk_facts}
    vendor_by_name = {fact.fact_name: fact for fact in vendor_facts}
    assert risk_by_name["cybersecurity_incident_event_type"].value == "generic_cyber_risk_control"
    assert risk_by_name["hard_negative_flag"].value is True
    assert "generic_cyber_risk_disclosure" in risk_by_name["hard_negative_reason"].value
    assert vendor_by_name["hard_negative_flag"].value is True
    assert "vendor_vulnerability_not_tied_to_company" in vendor_by_name["hard_negative_reason"].value


def test_no_material_impact_amendment_is_control_update():
    facts = parse_cybersecurity_incident_document(
        _doc(
            "This Form 8-K/A updates the company's prior Item 1.05 disclosure. "
            "The investigation is complete and the company has determined that the incident "
            "did not have a material impact and is not reasonably likely to materially impact "
            "financial condition or results of operations.",
            title="Form 8-K/A Item 1.05 amendment",
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["cybersecurity_incident_event_type"].value == "no_material_impact_update"
    assert by_name["event_direction_pre_price"].value == "neutral_control"
    assert by_name["hard_negative_flag"].value is True


def test_validate_parser_expected_absent_flags_false_positive():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "cybersecurity_incident_event_type", "value": "generic_cyber_risk_control"},
            {"event_id": "E2", "fact_name": "cybersecurity_incident_event_type", "value": "ransomware"},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "cybersecurity_incident_event_type", "expected_value": "unknown", "expected_present": False, "gold_category": "hard_negative_generic"},
            {"event_id": "E2", "fact_name": "cybersecurity_incident_event_type", "expected_value": "unknown", "expected_present": False, "gold_category": "hard_negative_generic"},
        ]
    )
    errors, report = validate_cybersecurity_incident_parser(facts, gold)
    assert errors.set_index("event_id").loc["E1", "status"] == "ok"
    assert errors.set_index("event_id").loc["E2", "status"] == "false_positive"
    assert report["gates"]["no_hard_negative_mistaken_for_material_incident"] is False


def test_context_enrichment_computes_runup_volatility_and_size_bucket(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "event_time": "2024-03-29T16:05:00",
                "release_session": "after_close",
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    xyz = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 70,
            "high": [10.0] * 70,
            "low": [10.0] * 70,
            "close": [10.0 + i * 0.1 for i in range(70)],
            "adj_close": [10.0 + i * 0.1 for i in range(70)],
            "volume": [1000] * 70,
        }
    )
    spy = xyz.copy()
    spy["close"] = 10.0
    spy["adj_close"] = 10.0
    xyz.to_csv(prices_dir / "XYZ.csv", index=False)
    spy.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "XYZ", "asof_date": "2024-03-01", "market_cap_before_event": 1_500_000_000}]).to_csv(tmp_path / "market_caps.csv", index=False)
    pd.DataFrame([{"ticker": "XYZ", "asof_date": "2024-03-01", "sector": "Healthcare", "data_sensitive_sector_flag": True}]).to_csv(tmp_path / "company.csv", index=False)

    enriched = enrich_cybersecurity_incident_context(
        events_path,
        prices_dir,
        tmp_path / "enriched.csv",
        market_caps_path=tmp_path / "market_caps.csv",
        company_context_path=tmp_path / "company.csv",
    )
    assert enriched.loc[0, "company_size_bucket"] == "small_cap"
    assert enriched.loc[0, "data_sensitive_sector_flag"] == True
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])
    assert pd.notna(enriched.loc[0, "pre_event_volatility_20d"])


def test_duplicate_audit_and_readiness_gate_before_modeling():
    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
                "review_status": "reviewed",
                "cybersecurity_incident_event_type": "ransomware" if i < 30 else "customer_data_breach",
                "item_105_flag": True,
                "operational_disruption_flag": i < 25,
                "ransomware_flag": i < 30,
                "customer_data_exposure_flag": i >= 30,
                "hard_negative_flag": False,
                "known_publicly_before_filing_flag": False,
                "market_cap_before_event": 1_000_000_000,
                "pre_event_market_adjusted_return_20d": 0.01,
                "pre_event_volatility_20d": 0.02,
                "source_evidence_text": "Item 1.05 source evidence",
                "sector_benchmark": "XLK",
                "duplicate_status": "primary",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 80})
    summary = cybersecurity_incident_readiness_summary(pd.DataFrame(rows), parser_errors=parser_errors)
    assert summary["decision"] == "model-ready"
    assert summary["execution_survivability_classification"] == "delayed-digestion"

    duplicate_events = pd.DataFrame([rows[0], {**rows[0], "event_id": "E0_DUP"}])
    audited, audit_summary = cybersecurity_timestamp_duplicate_audit(duplicate_events)
    assert audited.loc[1, "duplicate_status"] == "duplicate"
    assert audit_summary["gates"]["no_duplicate_incident_counted_twice"] is False
