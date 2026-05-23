from pathlib import Path

import pandas as pd
import pytest

from mre.demo import generate_demo_data
from mre.earnings import filter_earnings_filings, filings_to_earnings_events, normalize_sec_items
from mre.events import make_event_template
from mre.expectations import add_price_expectation_features, merge_external_expectations


def test_make_event_template_preserves_extra_columns(tmp_path: Path):
    out = tmp_path / "events.csv"
    make_event_template(
        out,
        [
            {
                "event_id": "e1",
                "ticker": "AAPL",
                "event_time": "2024-01-01T16:10:00",
                "event_type": "earnings",
                "summary": "example",
                "custom_feature": 123,
            }
        ],
    )
    df = pd.read_csv(out)
    assert "custom_feature" in df.columns
    assert int(df.loc[0, "custom_feature"]) == 123


def test_filter_earnings_filings_identifies_item_202():
    filings = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "cik": 320193,
                "form": "8-K",
                "items": "2.02,9.01",
                "filingDate": "2024-02-01",
                "acceptanceDateTime": "2024-02-01T16:31:00",
                "accessionNumber": "0000320193-24-000001",
                "primaryDocument": "aapl-20240201.htm",
            },
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "cik": 320193,
                "form": "8-K",
                "items": "5.02,9.01",
                "filingDate": "2024-02-15",
                "acceptanceDateTime": "2024-02-15T08:00:00",
                "accessionNumber": "0000320193-24-000002",
                "primaryDocument": "aapl-20240215.htm",
            },
        ]
    )
    assert normalize_sec_items("Item 2.02; 9.01") == {"2.02", "9.01"}
    earnings = filter_earnings_filings(filings)
    assert len(earnings) == 1
    events = filings_to_earnings_events(earnings, sector_benchmark="XLK")
    assert events.loc[0, "event_type"] == "earnings"
    assert events.loc[0, "release_session"] == "after_close"
    assert events.loc[0, "sector_benchmark"] == "XLK"


def test_add_price_expectation_features_demo_data(tmp_path: Path):
    paths = generate_demo_data(tmp_path / "demo", seed=123)
    out = tmp_path / "events_with_expectations.csv"
    df, diag = add_price_expectation_features(
        paths["events"],
        paths["prices_dir"],
        out,
        benchmark_ticker="SPY",
        windows=(5, 20, 60),
        horizons=(1, 3),
        min_history=20,
    )
    assert out.exists()
    assert diag.events_with_price_features > 0
    assert "expected_abs_move_h1_realized_vol_20d" in df.columns
    assert "pre_runup_bucket_20d" in df.columns
    ok = df[df["expectation_feature_status"] == "ok"]
    assert ok["expected_abs_move_h1_realized_vol_20d"].notna().any()


def test_external_expectations_leakage_guard(tmp_path: Path):
    events = tmp_path / "events.csv"
    make_event_template(
        events,
        [
            {
                "event_id": "e1",
                "ticker": "AAPL",
                "event_time": "2024-01-01T16:10:00",
                "event_type": "earnings",
                "summary": "example",
            }
        ],
    )
    ext = tmp_path / "ext.csv"
    pd.DataFrame(
        [
            {
                "event_id": "e1",
                "asof_time": "2024-01-02T10:00:00",
                "eps_surprise_pct": 0.12,
            }
        ]
    ).to_csv(ext, index=False)
    with pytest.raises(ValueError):
        merge_external_expectations(events, ext, tmp_path / "merged.csv")
