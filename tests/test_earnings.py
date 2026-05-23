import pandas as pd

from mre.earnings import classify_earnings_filing, filing_to_earnings_event_row


def test_classify_8k_item_202_as_earnings():
    row = pd.Series(
        {
            "form": "8-K",
            "items": "2.02,9.01",
            "primaryDocDescription": "Results of Operations and Financial Condition",
        }
    )
    ok, event_type, subtype, _ = classify_earnings_filing(row)
    assert ok
    assert event_type == "earnings"
    assert subtype == "8k_item_2_02_results"


def test_filing_to_earnings_event_row_preserves_sec_metadata():
    row = pd.Series(
        {
            "ticker": "ACME",
            "company_name": "Acme Inc",
            "cik": 123456,
            "form": "8-K",
            "items": "2.02,9.01",
            "filingDate": "2024-01-31",
            "acceptanceDateTime": "2024-01-31T16:15:00.000Z",
            "accessionNumber": "0000123456-24-000001",
            "primaryDocument": "acme-20240131.htm",
            "primaryDocDescription": "Results of Operations",
            "reportDate": "2023-12-31",
        }
    )
    out = filing_to_earnings_event_row(row, sector_benchmark="XLK")
    assert out is not None
    assert out["ticker"] == "ACME"
    assert out["event_type"] == "earnings"
    assert out["sector_benchmark"] == "XLK"
    assert out["release_session"] == "after_close"
    assert out["accession_number"] == "0000123456-24-000001"
