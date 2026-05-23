from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .expectations import apply_expectations_to_events
from .paths import ensure_dir

DEMO_EARNINGS_TICKERS = ["ACME", "BETA", "OMEGA", "ZETA"]
DEMO_BENCHMARKS = ["SPY", "XLK"]


def generate_earnings_demo_data(root: str | Path, seed: int = 7) -> dict[str, Path]:
    """Generate a synthetic earnings/guidance dataset with expectation features.

    The purpose is plumbing, not alpha. Price shocks are deliberately correlated
    with point-in-time surprise features so the pipeline can be verified.
    """
    rng = np.random.default_rng(seed)
    root = Path(root)
    prices_dir = ensure_dir(root / "prices")
    events_path = root / "earnings_events_raw.csv"
    expectations_path = root / "earnings_expectations.csv"
    enriched_events_path = root / "earnings_events_enriched.csv"
    dates = pd.bdate_range("2018-01-02", "2024-12-31")
    n = len(dates)

    spy_log = rng.normal(loc=0.0002, scale=0.009, size=n)
    xlk_log = 0.0001 + 1.10 * spy_log + rng.normal(loc=0, scale=0.006, size=n)
    logs = {"SPY": spy_log, "XLK": xlk_log}
    for i, ticker in enumerate(DEMO_EARNINGS_TICKERS):
        logs[ticker] = (
            0.00008
            + (0.85 + 0.10 * i) * spy_log
            + (0.25 + 0.05 * i) * xlk_log
            + rng.normal(0, 0.012 + 0.001 * i, n)
        )

    event_rows = []
    expectation_rows = []
    event_num = 0
    event_dates = pd.bdate_range("2018-04-15", "2024-10-31", freq="63B")
    for ticker_idx, ticker in enumerate(DEMO_EARNINGS_TICKERS):
        base_revenue = 1500 + 500 * ticker_idx
        base_eps = 0.75 + 0.2 * ticker_idx
        for q, d in enumerate(event_dates):
            event_num += 1
            session = "after_close" if q % 2 == 0 else "before_open"
            event_time = pd.Timestamp(d) + (pd.Timedelta(hours=16, minutes=10) if session == "after_close" else pd.Timedelta(hours=8, minutes=5))
            reaction_date = dates[dates.searchsorted(pd.Timestamp(d), side="right" if session == "after_close" else "left")]
            event_id = f"earn_demo_{ticker}_{q+1:03d}"

            consensus_revenue = base_revenue * (1 + 0.018 * q) * rng.normal(1.0, 0.015)
            rev_surprise_pct = rng.normal(0.0, 0.035)
            actual_revenue = consensus_revenue * (1 + rev_surprise_pct)

            consensus_eps = base_eps * (1 + 0.01 * q) * rng.normal(1.0, 0.03)
            eps_surprise_pct = rng.normal(0.0, 0.06)
            actual_eps = consensus_eps * (1 + eps_surprise_pct)

            consensus_forward_revenue = consensus_revenue * rng.normal(1.03, 0.015)
            guidance_surprise_pct = rng.normal(0.0, 0.04)
            guidance_mid = consensus_forward_revenue * (1 + guidance_surprise_pct)
            guidance_low = guidance_mid * 0.985
            guidance_high = guidance_mid * 1.015
            implied_move_pct = float(np.clip(rng.normal(0.055, 0.018), 0.015, 0.13))
            analyst_count = int(rng.integers(6, 28))

            score = np.mean([
                np.tanh(eps_surprise_pct / 0.05),
                np.tanh(rev_surprise_pct / 0.05),
                np.tanh(guidance_surprise_pct / 0.05),
            ])
            materiality = float(np.clip(0.45 + abs(score) * 0.4 + rng.normal(0, 0.08), 0.05, 1.0))
            shock = score * implied_move_pct * materiality * rng.normal(0.90, 0.20)
            # Add some non-fundamental noise so the demo is not perfectly separable.
            shock += rng.normal(0, 0.008)
            idx = dates.get_loc(reaction_date)
            logs[ticker][idx] += shock
            if idx + 1 < n:
                logs[ticker][idx + 1] += 0.20 * shock + rng.normal(0, 0.003)

            event_rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "event_time": event_time.isoformat(),
                    "event_type": "earnings",
                    "summary": f"Synthetic quarterly earnings event for {ticker}; expectations are in separate CSV.",
                    "event_subtype": "quarterly_results",
                    "source_type": "synthetic_demo",
                    "source_url": "",
                    "release_session": session,
                    "expectedness": "unknown",
                    "surprise_direction": "unknown",
                    "surprise_magnitude": "unknown",
                    "materiality": materiality,
                    "sector_benchmark": "XLK",
                    "notes": "Synthetic earnings event. Do not use for financial conclusions.",
                    "event_family": "earnings_guidance",
                    "fiscal_period_end": (pd.Timestamp(d) - pd.Timedelta(days=30)).date().isoformat(),
                }
            )
            expectation_rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "event_time": event_time.isoformat(),
                    "event_type": "earnings",
                    "event_subtype": "quarterly_results",
                    "summary": f"Synthetic expectations for {ticker} earnings.",
                    "consensus_eps": consensus_eps,
                    "actual_eps": actual_eps,
                    "consensus_revenue": consensus_revenue,
                    "actual_revenue": actual_revenue,
                    "consensus_forward_revenue": consensus_forward_revenue,
                    "guidance_revenue_low": guidance_low,
                    "guidance_revenue_high": guidance_high,
                    "guidance_revenue_mid": guidance_mid,
                    "implied_move_pct": implied_move_pct,
                    "analyst_count": analyst_count,
                    "expectations_timestamp": (event_time - pd.Timedelta(hours=1)).isoformat(),
                    "expectation_source_type": "synthetic_demo",
                    "expectation_source_url": "",
                    "expectation_notes": "Synthetic point-in-time expectation fields.",
                }
            )

    for ticker in DEMO_BENCHMARKS + DEMO_EARNINGS_TICKERS:
        price = 100 * np.exp(np.cumsum(logs[ticker]))
        close = price
        open_ = close * np.exp(rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, n))
        volume = rng.integers(1_000_000, 12_000_000, n)
        pd.DataFrame(
            {
                "date": dates,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adj_close": close,
                "volume": volume,
            }
        ).to_csv(prices_dir / f"{ticker}.csv", index=False)

    pd.DataFrame(event_rows).to_csv(events_path, index=False)
    pd.DataFrame(expectation_rows).to_csv(expectations_path, index=False)
    apply_expectations_to_events(events_path, expectations_path, enriched_events_path, fill_labels=True)
    return {
        "root": root,
        "prices_dir": prices_dir,
        "events_raw": events_path,
        "expectations": expectations_path,
        "events_enriched": enriched_events_path,
    }
