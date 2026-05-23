from __future__ import annotations

import pandas as pd

from mre.corpus import make_domain_event_template, normalize_domain
from mre.sec_distress_events import (
    enrich_sec_distress_context,
    parse_sec_distress_document,
    parse_sec_distress_manifest,
    sec_distress_readiness_summary,
    validate_sec_distress_parser,
)
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, event_id: str = "XYZ_distress_1") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-01-02 16:05:00"),
        event_type="filing",
        event_subtype="sec_8_k",
        release_session="after_close",
        source_type="sec_primary_filing",
        source_url="https://sec.test/8k.htm",
        title="XYZ 8-K",
        text=text,
    )


def test_corpus_domain_template_contains_sec_distress_and_execution_fields(tmp_path):
    assert normalize_domain("sec-distress") == "sec_distress_events"
    df = make_domain_event_template("sec_distress_events", tmp_path / "template.csv", tickers=["XYZ"])
    assert df.loc[0, "event_family"] == "sec_distress_events"
    assert "sec_distress_event_type" in df.columns
    assert "debt_amount_pct_market_cap" in df.columns
    assert "execution_survivability_class" in df.columns
    assert "next_open_required_flag" in df.columns


def test_bid_price_deficiency_is_distress_not_cure():
    facts = parse_sec_distress_document(
        _doc(
            "Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule. "
            "The Company received a notification letter from Nasdaq stating that the Company "
            "was not in compliance with the minimum bid price requirement."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["sec_8k_item"].value == "3.01"
    assert by_name["sec_distress_event_type"].value == "bid_price_deficiency"
    assert by_name["deficiency_type"].value == "bid_price"
    assert by_name["exchange"].value == "NASDAQ"
    assert by_name["hard_negative_flag"].value is False


def test_compliance_regained_is_hard_negative_control():
    facts = parse_sec_distress_document(
        _doc(
            "Item 3.01. Nasdaq notified the Company that it has regained compliance "
            "with the minimum bid price requirement and the matter is now closed."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["sec_distress_event_type"].value == "compliance_cure"
    assert by_name["compliance_regained_flag"].value is True
    assert by_name["hard_negative_flag"].value is True


def test_debt_acceleration_extracts_amount_and_flags():
    facts = parse_sec_distress_document(
        _doc(
            "Item 2.04 Triggering Events That Accelerate or Increase a Direct Financial Obligation. "
            "The lender delivered a notice of event of default and accelerated all amounts due "
            "under the credit facility. Approximately $42.5 million of principal debt is outstanding."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["sec_distress_event_type"].value == "debt_acceleration"
    assert by_name["acceleration_flag"].value is True
    assert by_name["debt_amount"].value == 42_500_000


def test_parse_manifest_marks_reverse_split_plan_as_rejected_explanation_only(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_reverse_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_reverse_2024",
                "event_time": "2024-03-01T16:05:00",
                "release_session": "after_close",
                "source_type": "sec_primary_filing",
                "source_url": "https://sec.test/reverse",
                "text": "The Company announced a reverse stock split plan intended to help regain compliance with Nasdaq listing rules.",
            }
        ],
    )
    _, features, events = parse_sec_distress_manifest(manifest, tmp_path / "facts.csv", tmp_path / "features.csv", tmp_path / "events.csv")
    assert features.loc[0, "sec_distress_event_type"] in {"reverse_split_plan", "extension_or_appeal"}
    assert features.loc[0, "hard_negative_flag"] == True
    assert features.loc[0, "execution_survivability_class"] == "explanation-only"
    assert events.loc[0, "review_status"] == "rejected"


def test_validate_parser_expected_present_false_catches_cure_mislabeled_negative():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "sec_distress_event_type", "value": "compliance_cure", "unit": "category", "confidence": 0.9},
            {"event_id": "E2", "fact_name": "sec_distress_event_type", "value": "delisting_notice", "unit": "category", "confidence": 0.9},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "sec_distress_event_type", "expected_value": "compliance_cure", "unit": "category", "gold_review_status": "reviewed"},
            {
                "event_id": "E2",
                "fact_name": "sec_distress_event_type",
                "expected_value": "unknown",
                "unit": "category",
                "expected_present": False,
                "gold_category": "compliance_cure",
                "gold_review_status": "reviewed",
            },
        ]
    )
    errors, report = validate_sec_distress_parser(facts, gold)
    assert errors.set_index("event_id").loc["E1", "status"] == "ok"
    assert errors.set_index("event_id").loc["E2", "status"] == "false_positive"
    assert report["parser_audit_pass"] is False


def test_enrich_context_computes_penny_liquidity_runup_and_ratios(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "event_time": "2024-03-29T16:05:00",
                "release_session": "after_close",
                "sec_distress_event_type": "debt_acceleration",
                "debt_amount": 25_000_000,
                "impairment_amount": 10_000_000,
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    xyz_prices = pd.DataFrame(
        {
            "date": dates,
            "open": [2.0] * 70,
            "high": [2.0] * 70,
            "low": [2.0] * 70,
            "close": [2.0 + i * 0.01 for i in range(70)],
            "adj_close": [2.0 + i * 0.01 for i in range(70)],
            "volume": [100_000] * 70,
        }
    )
    spy_prices = xyz_prices.copy()
    spy_prices["close"] = 2.0
    spy_prices["adj_close"] = 2.0
    xyz_prices.to_csv(prices_dir / "XYZ.csv", index=False)
    spy_prices.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "XYZ", "asof_date": "2024-03-01", "market_cap_before_event": 100_000_000}]).to_csv(tmp_path / "market_caps.csv", index=False)

    enriched = enrich_sec_distress_context(events_path, prices_dir, tmp_path / "enriched.csv", market_caps_path=tmp_path / "market_caps.csv")
    assert enriched.loc[0, "penny_stock_flag"] == True
    assert enriched.loc[0, "debt_amount_pct_market_cap"] == 0.25
    assert enriched.loc[0, "impairment_pct_market_cap"] == 0.10
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])
    assert enriched.loc[0, "liquidity_context_status"] == "ok"
    assert enriched.loc[0, "execution_survivability_class"] in {"immediate-gap", "explanation-only"}


def test_readiness_summary_blocks_without_execution_survivability_even_when_counts_pass():
    rows = []
    event_types = ["bid_price_deficiency"] * 35 + ["equity_deficiency"] * 25 + ["bankruptcy_receivership"] * 20 + ["debt_acceleration"] * 20
    for i, event_type in enumerate(event_types):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 12}",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
                "review_status": "reviewed",
                "sec_distress_event_type": event_type,
                "hard_negative_flag": False,
                "market_cap_before_event": 100_000_000,
                "pre_event_market_adjusted_return_20d": -0.20,
                "dollar_volume_before_event": 1_000_000,
                "next_open_return_available_flag": False,
                "close_to_close_explanatory_only_flag": True,
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    summary = sec_distress_readiness_summary(pd.DataFrame(rows), parser_errors=parser_errors)
    assert summary["reviewed_usable_distress_rows"] == 100
    assert summary["gates"]["parser_audit_pass"] is True
    assert summary["gates"]["execution_survivability_next_open_audited"] is False
    assert summary["decision"] == "execution survivability failed"


def test_readiness_summary_can_pass_after_next_open_execution_audit():
    rows = []
    event_types = ["bid_price_deficiency"] * 35 + ["equity_deficiency"] * 25 + ["bankruptcy_receivership"] * 20 + ["debt_acceleration"] * 20
    for i, event_type in enumerate(event_types):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 12}",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
                "review_status": "reviewed",
                "sec_distress_event_type": event_type,
                "hard_negative_flag": False,
                "market_cap_before_event": 100_000_000,
                "pre_event_market_adjusted_return_20d": -0.20,
                "dollar_volume_before_event": 1_000_000,
                "next_open_return_available_flag": True,
                "close_to_close_explanatory_only_flag": False,
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    summary = sec_distress_readiness_summary(pd.DataFrame(rows), parser_errors=parser_errors)
    assert summary["decision"] == "model-ready"
