from __future__ import annotations

import pandas as pd

from mre.corpus import make_domain_event_template, normalize_domain
from mre.insider_purchase_clusters import (
    build_insider_purchase_duplicate_audit,
    build_insider_purchase_timestamp_audit,
    enrich_insider_purchase_context,
    insider_purchase_readiness_summary,
    parse_insider_purchase_document,
    parse_insider_purchase_manifest,
    validate_insider_purchase_parser,
)
from mre.source_docs import SourceDocument, make_source_docs_template


def _form4_xml(
    *,
    code: str = "P",
    owner: str = "Jane CEO",
    officer_title: str = "Chief Executive Officer",
    is_director: str = "0",
    is_officer: str = "1",
    is_ten_percent: str = "0",
    shares: float = 10000,
    price: float = 12.50,
    acquired_disposed: str = "A",
    derivative: bool = False,
    footnote: str = "",
    document_type: str = "4",
) -> str:
    footnote_id = '<footnoteId id="F1"/>' if footnote else ""
    footnotes = f"<footnotes><footnote id=\"F1\">{footnote}</footnote></footnotes>" if footnote else ""
    table = "derivativeTable" if derivative else "nonDerivativeTable"
    txn = "derivativeTransaction" if derivative else "nonDerivativeTransaction"
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <documentType>{document_type}</documentType>
  <issuer><issuerTradingSymbol>XYZ</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>{is_director}</isDirector>
      <isOfficer>{is_officer}</isOfficer>
      <isTenPercentOwner>{is_ten_percent}</isTenPercentOwner>
      <officerTitle>{officer_title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <{table}>
    <{txn}>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-01</value></transactionDate>
      <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{acquired_disposed}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>50000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
      {footnote_id}
    </{txn}>
  </{table}>
  {footnotes}
</ownershipDocument>"""


def _doc(text: str, *, event_id: str = "XYZ_form4_2024") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-03-04 16:05:00"),
        event_type="insider_transaction",
        event_subtype="sec_form4_xml",
        release_session="after_close",
        source_type="sec_form4_xml",
        source_url="https://sec.test/form4.xml",
        title="XYZ Form 4",
        text=text,
    )


def test_corpus_domain_template_contains_insider_fields(tmp_path):
    assert normalize_domain("form4") == "insider_purchase_clusters"
    df = make_domain_event_template("insider_purchase_clusters", tmp_path / "template.csv", tickers=["XYZ"])
    assert df.loc[0, "event_family"] == "insider_purchase_clusters"
    assert "transaction_value_pct_market_cap" in df.columns
    assert "execution_survivability_class" in df.columns


def test_form4_ceo_open_market_purchase_extracts_primary_fields():
    facts = parse_insider_purchase_document(_doc(_form4_xml()))
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["insider_purchase_event_type"].value == "ceo_purchase"
    assert by_name["transaction_code"].value == "P"
    assert by_name["open_market_purchase_flag"].value is True
    assert by_name["transaction_value"].value == 125000
    assert by_name["10b5_1_language"].value is False


def test_form4_hard_negatives_are_not_primary_purchases():
    cases = [
        (_form4_xml(code="M", derivative=True), "option_exercise"),
        (_form4_xml(code="F", acquired_disposed="D"), "tax_withholding"),
        (_form4_xml(code="P", footnote="Shares purchased pursuant to a Rule 10b5-1 trading plan."), "planned_transaction"),
        (_form4_xml(code="G", price=0), "non_open_market_transaction"),
    ]
    for xml, expected in cases:
        by_name = {fact.fact_name: fact for fact in parse_insider_purchase_document(_doc(xml))}
        assert by_name["insider_purchase_event_type"].value == expected
        assert by_name["open_market_purchase_flag"].value is False
        if expected != "planned_transaction":
            assert by_name["hard_negative_flag"].value is True


def test_parse_manifest_and_context_build_cluster_features(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "ceo_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_ceo",
                "event_time": "2024-03-04T16:05:00",
                "release_session": "after_close",
                "source_type": "sec_form4_xml",
                "source_url": "https://sec.test/ceo.xml",
                "text": _form4_xml(owner="Jane CEO", officer_title="Chief Executive Officer"),
            },
            {
                "source_doc_id": "cfo_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_cfo",
                "event_time": "2024-03-07T16:05:00",
                "release_session": "after_close",
                "source_type": "sec_form4_xml",
                "source_url": "https://sec.test/cfo.xml",
                "text": _form4_xml(owner="John CFO", officer_title="Chief Financial Officer"),
            },
        ],
    )
    _, features, events = parse_insider_purchase_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )
    assert set(features["insider_purchase_event_type"]) == {"ceo_purchase", "cfo_purchase"}
    events["release_session"] = "after_close"
    events.to_csv(tmp_path / "events.csv", index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2023-12-01", periods=90, freq="B")
    xyz = pd.DataFrame(
        {
            "date": dates,
            "open": [10 + i * 0.02 for i in range(90)],
            "high": [10 + i * 0.02 for i in range(90)],
            "low": [10 + i * 0.02 for i in range(90)],
            "close": [10 + i * 0.02 for i in range(90)],
            "adj_close": [10 + i * 0.02 for i in range(90)],
            "volume": [100000] * 90,
        }
    )
    spy = xyz.copy()
    spy["adj_close"] = 10.0
    spy["close"] = 10.0
    xyz.to_csv(prices_dir / "XYZ.csv", index=False)
    spy.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "XYZ", "asof_date": "2024-02-01", "shares_outstanding_before_event": 10_000_000}]).to_csv(tmp_path / "shares.csv", index=False)
    enriched = enrich_insider_purchase_context(
        tmp_path / "events.csv",
        prices_dir,
        tmp_path / "enriched.csv",
        shares_outstanding_path=tmp_path / "shares.csv",
    )
    by_event = enriched.set_index("event_id")
    assert by_event.loc["XYZ_cfo", "cluster_count_10d"] == 2
    assert by_event.loc["XYZ_cfo", "purchase_cluster_flag"] == True
    assert by_event.loc["XYZ_cfo", "execution_survivability_class"] == "slow-burn repricing"
    assert pd.notna(by_event.loc["XYZ_ceo", "transaction_value_pct_market_cap"])


def test_duplicate_and_timestamp_audits_flag_amendments_and_bad_dates():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "event_time": "2024-03-04T16:05:00",
                "release_session": "after_close",
                "reporting_owner_name": "Jane CEO",
                "transaction_date": "2024-03-01",
                "transaction_code": "P",
                "shares": 10000,
                "price": 10.0,
                "amended_filing_flag": False,
            },
            {
                "event_id": "E1A",
                "ticker": "XYZ",
                "event_time": "2024-03-05T16:05:00",
                "release_session": "after_close",
                "reporting_owner_name": "Jane CEO",
                "transaction_date": "2024-03-01",
                "transaction_code": "P",
                "shares": 10000,
                "price": 10.0,
                "amended_filing_flag": True,
            },
            {
                "event_id": "BAD_TS",
                "ticker": "XYZ",
                "event_time": "2024-02-28T16:05:00",
                "release_session": "unknown",
                "transaction_date": "2024-03-01",
                "transaction_code": "P",
                "shares": 1,
                "price": 1,
            },
        ]
    )
    duplicate = build_insider_purchase_duplicate_audit(events)
    assert duplicate.set_index("event_id").loc["E1A", "duplicate_type"] == "amended_form4_duplicate"
    timestamp = build_insider_purchase_timestamp_audit(events)
    assert timestamp.set_index("event_id").loc["BAD_TS", "timestamp_risk_level"] == "high"


def test_validate_parser_and_readiness_requires_execution_gate():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "insider_purchase_event_type", "value": "ceo_purchase", "confidence": 0.9},
            {"event_id": "E1", "fact_name": "transaction_code", "value": "P", "confidence": 0.9},
            {"event_id": "E1", "fact_name": "transaction_value", "value": 125000, "confidence": 0.9},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "insider_purchase_event_type", "expected_value": "ceo_purchase"},
            {"event_id": "E1", "fact_name": "transaction_code", "expected_value": "P"},
            {"event_id": "E1", "fact_name": "transaction_value", "expected_value": 125000},
        ]
    )
    errors, report = validate_insider_purchase_parser(facts, gold)
    assert set(errors["status"]) == {"ok"}
    assert report["correct_rows"] == 3

    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "event_time": "2024-03-04T16:05:00",
                "release_session": "after_close",
                "review_status": "reviewed",
                "open_market_purchase_flag": True,
                "hard_negative_flag": False,
                "officer_or_director_flag": True,
                "ceo_purchase_flag": i < 20,
                "cfo_purchase_flag": 20 <= i < 40,
                "cluster_count_10d": 2 if i < 35 else 1,
                "transaction_value_pct_market_cap": 0.001,
                "pre_event_market_adjusted_return_20d": -0.05,
                "shares_outstanding_before_event": 10_000_000,
                "execution_survivability_gate": "not_evaluated",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    audit = pd.DataFrame({"duplicate_risk_level": ["low"] * 100})
    timestamp = pd.DataFrame({"timestamp_risk_level": ["low"] * 100})
    summary = insider_purchase_readiness_summary(
        pd.DataFrame(rows),
        parser_errors=parser_errors,
        duplicate_audit=audit,
        timestamp_audit=timestamp,
    )
    assert summary["gates"]["execution_survivability_gate_pass"] is False
    assert summary["decision"] != "model-ready"
    for row in rows:
        row["execution_survivability_gate"] = "pass"
    summary = insider_purchase_readiness_summary(
        pd.DataFrame(rows),
        parser_errors=parser_errors,
        duplicate_audit=audit,
        timestamp_audit=timestamp,
    )
    assert summary["decision"] == "model-ready"
