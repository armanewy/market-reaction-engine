from __future__ import annotations

import pandas as pd

from mre.exhibit99_parser import parse_exhibit99_document
from mre.source_docs import SourceDocument


def _doc(text: str) -> SourceDocument:
    return SourceDocument(
        source_doc_id="doc1",
        ticker="AMAT",
        event_id="AMAT_2020Q3",
        event_time=pd.Timestamp("2020-08-13 16:05:00"),
        event_type="earnings",
        event_subtype="sec_exhibit99",
        release_session="after_close",
        source_type="sec_exhibit99",
        source_url="https://sec.test/ex99.htm",
        title="AMAT earnings release",
        text=text,
    )


def test_plus_minus_revenue_guidance_parses_mid_low_high():
    facts = parse_exhibit99_document(
        _doc("Business Outlook. In the fourth quarter, Applied expects net sales to be approximately $4.60 billion, plus or minus $200 million.")
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["guidance_revenue_mid"].value == 4_600_000_000
    assert by_name["guidance_revenue_low"].value == 4_400_000_000
    assert by_name["guidance_revenue_high"].value == 4_800_000_000
    assert by_name["guidance_revenue_mid"].period_role == "next_quarter_guidance"
    assert by_name["guidance_revenue_mid"].confidence >= 0.9


def test_range_revenue_guidance_parses_midpoint():
    facts = parse_exhibit99_document(_doc("Outlook: Revenue is expected to be in the range of $6.5 billion to $6.8 billion."))
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["guidance_revenue_low"].value == 6_500_000_000
    assert by_name["guidance_revenue_high"].value == 6_800_000_000
    assert by_name["guidance_revenue_mid"].value == 6_650_000_000


def test_range_revenue_guidance_infers_unit_from_high_end():
    facts = parse_exhibit99_document(_doc("Revenue is expected to be in the range of $2.20 to $2.50 billion."))
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["guidance_revenue_low"].value == 2_200_000_000
    assert by_name["guidance_revenue_high"].value == 2_500_000_000
    assert by_name["guidance_revenue_mid"].value == 2_350_000_000


def test_range_revenue_guidance_allows_approximately():
    facts = parse_exhibit99_document(_doc("We expect net sales to be in the range of approximately $1.442 billion to $1.469 billion."))
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["guidance_revenue_low"].value == 1_442_000_000
    assert by_name["guidance_revenue_high"].value == 1_469_000_000
    assert by_name["guidance_revenue_mid"].value == 1_455_500_000


def test_actual_revenue_ignores_guidance_sentence():
    facts = parse_exhibit99_document(
        _doc(
            "Quarterly revenue of $4.40 billion, up 23 percent year over year. "
            "Business Outlook. Applied expects net sales to be approximately $4.60 billion, plus or minus $200 million."
        )
    )
    actuals = [fact for fact in facts if fact.fact_name == "actual_revenue"]
    guidance = [fact for fact in facts if fact.fact_name == "guidance_revenue_mid"]
    assert len(actuals) == 1
    assert actuals[0].value == 4_400_000_000
    assert len(guidance) == 1
    assert guidance[0].value == 4_600_000_000


def test_bullet_line_actual_revenue_parses_when_document_has_guidance_later():
    facts = parse_exhibit99_document(
        _doc(
            "Highlights\n"
            "•Revenue of $3.25 billion with double-digit year-over-year growth\n"
            "Business Outlook\n"
            "For the second quarter of fiscal 2023, we are forecasting revenue of $3.20 billion, +/- $100 million."
        )
    )
    actuals = [fact for fact in facts if fact.fact_name == "actual_revenue"]
    guidance = [fact for fact in facts if fact.fact_name == "guidance_revenue_mid"]
    assert len(actuals) == 1
    assert actuals[0].value == 3_250_000_000
    assert len(guidance) == 1
    assert guidance[0].value == 3_200_000_000


def test_comma_million_actual_revenue_parses():
    facts = parse_exhibit99_document(_doc("•Revenue of $6,778 million for the third quarter, up 16 percent from the prior year period"))
    actuals = [fact for fact in facts if fact.fact_name == "actual_revenue"]
    assert len(actuals) == 1
    assert actuals[0].value == 6_778_000_000


def test_company_boilerplate_revenue_more_than_is_not_actual_revenue():
    facts = parse_exhibit99_document(_doc("ADI is a global semiconductor leader with revenue of more than $12 billion in FY22."))
    assert [fact for fact in facts if fact.fact_name == "actual_revenue"] == []


def test_prior_guidance_comparison_is_not_next_quarter_guidance():
    facts = parse_exhibit99_document(_doc("Total revenues were $2.43 billion, above the midpoint of the guidance range of $2.20 to $2.50 billion."))
    assert [fact for fact in facts if fact.fact_name == "guidance_revenue_mid"] == []


def test_eps_definition_footnote_is_not_actual_eps():
    facts = parse_exhibit99_document(
        _doc(
            "Adjusted diluted EPS is defined as diluted EPS, determined in accordance with GAAP, "
            "excluding: acquisition related expenses1, special charges, net2, and tax related items3, "
            "which are described further below."
        )
    )
    assert [fact for fact in facts if fact.fact_name == "actual_eps"] == []


def test_eps_table_label_footnote_is_not_actual_eps():
    facts = parse_exhibit99_document(_doc("Diluted earnings per share(1)"))
    assert [fact for fact in facts if fact.fact_name == "actual_eps"] == []
