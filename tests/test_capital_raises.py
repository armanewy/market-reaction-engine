from __future__ import annotations

import pandas as pd

from mre.capital_raises import (
    capital_raise_readiness_summary,
    enrich_capital_raise_context,
    parse_capital_raise_document,
    parse_capital_raise_manifest,
    validate_capital_raise_parser,
)
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, event_id: str = "XYZ_offer_1") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-01-02 16:05:00"),
        event_type="financing",
        event_subtype="capital_raise",
        release_session="after_close",
        source_type="sec_filing",
        source_url="https://sec.test/offering.htm",
        title="XYZ offering document",
        text=text,
    )


def test_parse_common_stock_offering_terms():
    facts = parse_capital_raise_document(
        _doc(
            "XYZ announced a public offering of 10,000,000 shares of common stock "
            "at a public offering price of $2.50 per share. Gross proceeds are expected "
            "to be approximately $25.0 million before expenses. The company intends to use the net proceeds for working capital."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["financing_event_type"].value == "completed_equity_offering"
    assert by_name["security_type"].value == "common_stock"
    assert by_name["shares_offered"].value == 10_000_000
    assert by_name["price_per_share"].value == 2.50
    assert by_name["gross_proceeds"].value == 25_000_000
    assert "working capital" in str(by_name["use_of_proceeds"].value)


def test_parse_atm_program_capacity():
    facts = parse_capital_raise_document(
        _doc(
            "The company entered into an at-the-market offering program under which it may sell "
            "shares of common stock having an aggregate offering price of up to $150 million from time to time."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["financing_event_type"].value == "atm_program_created"
    assert by_name["atm_capacity"].value == 150_000_000


def test_parse_convertible_debt_terms():
    facts = parse_capital_raise_document(
        _doc(
            "XYZ priced $300 million aggregate principal amount of 3.00% convertible senior notes due 2030. "
            "The initial conversion price is approximately $12.50 per share."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["financing_event_type"].value == "convertible_note_offering"
    assert by_name["security_type"].value == "convertible_notes"
    assert by_name["convertible_principal"].value == 300_000_000
    assert by_name["conversion_price"].value == 12.50


def test_parse_capital_raise_manifest_writes_review_queue(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_offer_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_offer_2024",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "financing",
                "event_subtype": "equity_offering",
                "release_session": "after_close",
                "source_type": "sec_filing",
                "source_url": "https://sec.test/offering.htm",
                "title": "XYZ offering",
                "text": "XYZ announced a registered direct offering of 2 million shares of common stock at $5.00 per share. Gross proceeds will be approximately $10 million.",
            }
        ],
    )

    facts, features, events = parse_capital_raise_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    assert len(facts) >= 4
    assert features.loc[0, "financing_event_type"] == "registered_direct_offering"
    assert features.loc[0, "gross_proceeds"] == 10_000_000
    assert features.loc[0, "completed_financing_flag"] == True
    assert features.loc[0, "capacity_only_flag"] == False
    assert features.loc[0, "financing_amount_best"] == 10_000_000
    assert events.loc[0, "event_family"] == "capital_raise_dilution"
    assert events.loc[0, "review_status"] == "unreviewed"


def test_capacity_only_shelf_not_marked_completed(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_shelf_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_shelf_2024",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "financing",
                "event_subtype": "shelf_registration",
                "release_session": "after_close",
                "source_type": "sec_filing",
                "source_url": "https://sec.test/shelf.htm",
                "title": "XYZ shelf",
                "text": "The company filed a shelf registration statement on Form S-3 under which it may offer up to $200 million of securities from time to time.",
            }
        ],
    )
    _, features, events = parse_capital_raise_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )
    assert features.loc[0, "financing_event_type"] == "shelf_registration"
    assert features.loc[0, "capacity_only_flag"] == True
    assert features.loc[0, "completed_financing_flag"] == False
    assert events.loc[0, "surprise_direction"] == "unknown"


def test_validate_capital_raise_parser_against_gold():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "gross_proceeds", "value": 25_000_000, "unit": "usd", "confidence": 0.9, "evidence_text": "gross proceeds"},
            {"event_id": "E1", "fact_name": "financing_event_type", "value": "completed_equity_offering", "unit": "category", "confidence": 0.9, "evidence_text": "public offering"},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "gross_proceeds", "expected_value": 25_000_000, "unit": "usd"},
            {"event_id": "E1", "fact_name": "financing_event_type", "expected_value": "completed_equity_offering", "unit": "category"},
        ]
    )
    errors, report = validate_capital_raise_parser(facts, gold)
    assert report["correct_rows"] == 2
    assert set(errors["status"]) == {"ok"}


def test_enrich_capital_raise_context_computes_discount_and_dilution(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "event_time": "2024-01-05T16:05:00",
                "release_session": "after_close",
                "price_per_share": 8.0,
                "offering_price": 8.0,
                "shares_offered": 1_000_000,
                "shares_outstanding_before_event": 10_000_000,
                "financing_amount_best": 8_000_000,
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    price_rows = pd.DataFrame(
        {
            "date": pd.date_range("2023-11-01", periods=50, freq="B"),
            "open": range(50),
            "high": range(50),
            "low": range(50),
            "close": [10.0] * 50,
            "adj_close": [10.0] * 50,
            "volume": [1000] * 50,
        }
    )
    price_rows.to_csv(prices_dir / "XYZ.csv", index=False)
    price_rows.to_csv(prices_dir / "SPY.csv", index=False)

    enriched = enrich_capital_raise_context(events_path, prices_dir, tmp_path / "enriched.csv", benchmark_ticker="SPY")
    assert enriched.loc[0, "last_close_before_event"] == 10.0
    assert round(enriched.loc[0, "discount_to_last_close_pct"], 4) == -0.2
    assert round(enriched.loc[0, "estimated_dilution_pct"], 4) == 0.1
    assert round(enriched.loc[0, "market_cap_before_event"], 4) == 100_000_000
    assert round(enriched.loc[0, "financing_amount_pct_market_cap"], 4) == 0.08


def test_capital_raise_readiness_summary_enforces_gates():
    rows = []
    for i in range(85):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": "XYZ",
                "review_status": "reviewed",
                "completed_financing_flag": i < 61,
                "capacity_only_flag": i >= 61,
                "financing_amount_best": 10_000_000,
                "discount_to_last_close_pct": -0.1 if i < 41 else pd.NA,
                "financing_amount_pct_market_cap": 0.1 if i < 41 else pd.NA,
            }
        )
    summary = capital_raise_readiness_summary(pd.DataFrame(rows), min_train=40)
    assert summary["reviewed_usable_rows"] == 85
    assert summary["completed_financing_rows"] == 61
    assert summary["likely_oos_predictions_min_train"] == 45
    assert summary["gates"]["reviewed_usable_events_80_min"] is True
    assert summary["gates"]["reviewed_usable_events_100_preferred"] is False
    assert summary["decision"] == "continue corpus buildout"
