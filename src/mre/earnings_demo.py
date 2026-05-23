from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .analyst_revisions import merge_analyst_revisions
from .expectations import apply_expectations_to_events
from .options import merge_options_implied_moves
from .paths import ensure_dir
from .release_times import merge_release_times

DEMO_EARNINGS_TICKERS = ["ACME", "BETA", "OMEGA"]
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
    release_times_path = root / "earnings_release_times.csv"
    options_path = root / "earnings_option_snapshots.csv"
    analyst_revisions_path = root / "earnings_analyst_revisions.csv"
    release_enriched_path = root / "earnings_events_release_times.csv"
    expectations_enriched_path = root / "earnings_events_expectations.csv"
    options_enriched_path = root / "earnings_events_options.csv"
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
    release_time_rows = []
    option_rows = []
    analyst_revision_rows = []
    event_num = 0
    event_dates = pd.bdate_range("2018-04-15", "2024-10-31", freq="84B")
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

            consensus_forward_eps = consensus_eps * rng.normal(1.04, 0.02)
            guidance_eps_surprise_pct = rng.normal(0.0, 0.045)
            guidance_eps_mid = consensus_forward_eps * (1 + guidance_eps_surprise_pct)
            guidance_eps_low = guidance_eps_mid * 0.97
            guidance_eps_high = guidance_eps_mid * 1.03

            consensus_forward_revenue = consensus_revenue * rng.normal(1.03, 0.015)
            guidance_surprise_pct = rng.normal(0.0, 0.04)
            guidance_mid = consensus_forward_revenue * (1 + guidance_surprise_pct)
            guidance_low = guidance_mid * 0.985
            guidance_high = guidance_mid * 1.015

            consensus_gross_margin = float(np.clip(rng.normal(0.58 + 0.02 * ticker_idx, 0.025), 0.35, 0.85))
            gross_margin_surprise_pct = rng.normal(0.0, 0.035)
            actual_gross_margin = float(np.clip(consensus_gross_margin * (1 + gross_margin_surprise_pct), 0.25, 0.90))
            consensus_forward_gross_margin = float(np.clip(consensus_gross_margin + rng.normal(0.01, 0.01), 0.25, 0.90))
            guidance_gm_surprise_pct = rng.normal(0.0, 0.035)
            guidance_gm_mid = float(np.clip(consensus_forward_gross_margin * (1 + guidance_gm_surprise_pct), 0.25, 0.90))
            guidance_gm_low = guidance_gm_mid - 0.01
            guidance_gm_high = guidance_gm_mid + 0.01

            implied_move_pct = float(np.clip(rng.normal(0.055, 0.018), 0.015, 0.13))
            analyst_count = int(rng.integers(6, 28))

            score = np.mean([
                np.tanh(eps_surprise_pct / 0.05),
                np.tanh(guidance_eps_surprise_pct / 0.05),
                np.tanh(rev_surprise_pct / 0.05),
                np.tanh(guidance_surprise_pct / 0.05),
                np.tanh(gross_margin_surprise_pct / 0.05),
                np.tanh(guidance_gm_surprise_pct / 0.05),
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
                    "consensus_forward_eps": consensus_forward_eps,
                    "guidance_eps_low": guidance_eps_low,
                    "guidance_eps_high": guidance_eps_high,
                    "guidance_eps_mid": guidance_eps_mid,
                    "consensus_revenue": consensus_revenue,
                    "actual_revenue": actual_revenue,
                    "consensus_forward_revenue": consensus_forward_revenue,
                    "guidance_revenue_low": guidance_low,
                    "guidance_revenue_high": guidance_high,
                    "guidance_revenue_mid": guidance_mid,
                    "consensus_gross_margin": consensus_gross_margin,
                    "actual_gross_margin": actual_gross_margin,
                    "consensus_forward_gross_margin": consensus_forward_gross_margin,
                    "guidance_gross_margin_low": guidance_gm_low,
                    "guidance_gross_margin_high": guidance_gm_high,
                    "guidance_gross_margin_mid": guidance_gm_mid,
                    "implied_move_pct": implied_move_pct,
                    "analyst_count": analyst_count,
                    "expectations_timestamp": (event_time - pd.Timedelta(hours=1)).isoformat(),
                    "expectation_source_type": "synthetic_demo",
                    "expectation_source_url": "",
                    "expectation_notes": "Synthetic point-in-time expectation fields.",
                }
            )
            release_time_rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "exact_release_time": event_time.isoformat(),
                    "release_session": session,
                    "release_time_confidence": "synthetic_exact",
                    "release_time_source_type": "synthetic_demo",
                    "release_time_source_url": "",
                    "release_time_notes": "Synthetic exact release timestamp.",
                }
            )
            underlying = 100.0 + 2.0 * ticker_idx + 0.35 * q
            atm_strike = round(underlying / 5.0) * 5.0
            call_mid = implied_move_pct * underlying * rng.uniform(0.45, 0.55)
            put_mid = implied_move_pct * underlying - call_mid
            option_rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "quote_time": (event_time - pd.Timedelta(minutes=20)).isoformat(),
                    "expiration": (pd.Timestamp(d) + pd.Timedelta(days=3)).date().isoformat(),
                    "underlying_price": underlying,
                    "strike": atm_strike,
                    "call_mid": call_mid,
                    "put_mid": put_mid,
                    "option_source_type": "synthetic_demo",
                    "option_source_url": "",
                    "option_notes": "Synthetic ATM straddle row.",
                }
            )
            analyst_ids = [f"analyst_{i}" for i in range(1, 5)]
            metric_targets = {
                "eps": consensus_eps,
                "revenue": consensus_revenue,
                "gross_margin": consensus_gross_margin,
                "forward_revenue": consensus_forward_revenue,
            }
            for metric, target in metric_targets.items():
                for analyst in analyst_ids:
                    old_est = target * rng.normal(0.985, 0.025)
                    new_est = target * rng.normal(1.0, 0.012)
                    analyst_revision_rows.append(
                        {
                            "event_id": event_id,
                            "ticker": ticker,
                            "estimate_time": (event_time - pd.Timedelta(days=30)).isoformat(),
                            "analyst_id": analyst,
                            "metric": metric,
                            "fiscal_period": (pd.Timestamp(d) - pd.Timedelta(days=30)).date().isoformat(),
                            "estimate_value": old_est,
                            "estimate_source_type": "synthetic_demo",
                        }
                    )
                    analyst_revision_rows.append(
                        {
                            "event_id": event_id,
                            "ticker": ticker,
                            "estimate_time": (event_time - pd.Timedelta(hours=2)).isoformat(),
                            "analyst_id": analyst,
                            "metric": metric,
                            "fiscal_period": (pd.Timestamp(d) - pd.Timedelta(days=30)).date().isoformat(),
                            "estimate_value": new_est,
                            "estimate_source_type": "synthetic_demo",
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
    pd.DataFrame(release_time_rows).to_csv(release_times_path, index=False)
    pd.DataFrame(option_rows).to_csv(options_path, index=False)
    pd.DataFrame(analyst_revision_rows).to_csv(analyst_revisions_path, index=False)

    merge_release_times(events_path, release_times_path, release_enriched_path)
    apply_expectations_to_events(release_enriched_path, expectations_path, expectations_enriched_path, fill_labels=True)
    merge_options_implied_moves(expectations_enriched_path, options_path, options_enriched_path)

    # The demo still writes analyst-revision rows, but avoids running the full
    # revision-feature pass by default so offline tests stay lightweight in
    # constrained environments. Use `mre merge-analyst-revisions` on the written
    # CSVs to exercise the full point-in-time revision feature builder.
    enriched = pd.read_csv(options_enriched_path)
    enriched["analyst_revision_status"] = "synthetic_feed_written_not_merged"
    enriched["analyst_revision_reason"] = "Run merge-analyst-revisions to add full revision features."
    enriched.to_csv(enriched_events_path, index=False)
    return {
        "root": root,
        "prices_dir": prices_dir,
        "events_raw": events_path,
        "expectations": expectations_path,
        "release_times": release_times_path,
        "option_snapshots": options_path,
        "analyst_revisions": analyst_revisions_path,
        "events_release_times": release_enriched_path,
        "events_expectations": expectations_enriched_path,
        "events_options": options_enriched_path,
        "events_enriched": enriched_events_path,
    }
