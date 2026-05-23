import pandas as pd

from mre.earnings import alpha_vantage_earnings_to_event_rows


def test_alpha_vantage_rows_convert_eps_surprise_to_fraction():
    raw = pd.DataFrame(
        [
            {
                "fiscalDateEnding": "2024-03-31",
                "reportedDate": "2024-04-25",
                "reportedEPS": "1.10",
                "estimatedEPS": "1.00",
                "surprise": "0.10",
                "surprisePercentage": "10.0",
            }
        ]
    )
    out = alpha_vantage_earnings_to_event_rows("ACME", raw, sector_benchmark="XLK")
    assert len(out) == 1
    assert out.loc[0, "ticker"] == "ACME"
    assert out.loc[0, "event_type"] == "earnings"
    assert out.loc[0, "sector_benchmark"] == "XLK"
    assert round(float(out.loc[0, "eps_surprise_pct"]), 4) == 0.10
    assert out.loc[0, "surprise_direction"] == "positive"
