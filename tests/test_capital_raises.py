from __future__ import annotations

import pandas as pd

from mre.capital_raises import parse_capital_raise_document, parse_capital_raise_manifest
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
    assert by_name["financing_event_type"].value == "equity_offering"
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
    assert by_name["financing_event_type"].value == "atm_program"
    assert by_name["atm_capacity"].value == 150_000_000


def test_parse_convertible_debt_terms():
    facts = parse_capital_raise_document(
        _doc(
            "XYZ priced $300 million aggregate principal amount of 3.00% convertible senior notes due 2030. "
            "The initial conversion price is approximately $12.50 per share."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["financing_event_type"].value == "convertible_debt"
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
    assert events.loc[0, "event_family"] == "capital_raise_dilution"
    assert events.loc[0, "review_status"] == "unreviewed"
