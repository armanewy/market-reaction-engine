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

