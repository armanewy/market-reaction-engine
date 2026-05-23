from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .paths import ensure_dir

DEMO_TICKERS = ["ACME", "BETA", "OMEGA", "SPY", "XLK"]


def generate_demo_data(root: str | Path, seed: int = 42) -> dict[str, Path]:
    """Generate deterministic synthetic prices/events for a full offline demo.

    The synthetic data intentionally injects event-related jumps so the pipeline
    can be tested end-to-end without pretending that a real trading edge exists.
    """
    rng = np.random.default_rng(seed)
    root = Path(root)
    prices_dir = ensure_dir(root / "prices")
    events_path = root / "events.csv"
    dates = pd.bdate_range("2021-01-04", "2024-12-31")
    n = len(dates)

    spy_log = rng.normal(loc=0.00025, scale=0.009, size=n)
    xlk_log = 0.00015 + 1.12 * spy_log + rng.normal(loc=0, scale=0.006, size=n)
    logs = {
        "SPY": spy_log,
        "XLK": xlk_log,
        "ACME": 0.00010 + 1.25 * spy_log + 0.35 * xlk_log + rng.normal(0, 0.012, n),
        "BETA": 0.00008 + 0.85 * spy_log + 0.50 * xlk_log + rng.normal(0, 0.014, n),
        "OMEGA": 0.00005 + 1.05 * spy_log + 0.20 * xlk_log + rng.normal(0, 0.016, n),
    }

    event_rows = []
    event_types = ["earnings", "guidance", "regulatory", "product", "security", "filing"]
    directions = ["positive", "negative", "mixed", "neutral"]
    magnitudes = ["low", "medium", "high"]
    tickers = ["ACME", "BETA", "OMEGA"]
    event_dates = pd.bdate_range("2021-09-01", "2024-10-31", freq="22B")

    for i, d in enumerate(event_dates[:45]):
        ticker = tickers[i % len(tickers)]
        event_type = event_types[i % len(event_types)]
        direction = directions[(i * 2 + (i // 7)) % len(directions)]
        magnitude = magnitudes[(i * 2 + 1) % len(magnitudes)]
        session = "after_close" if i % 3 == 0 else ("before_open" if i % 3 == 1 else "intraday")
        materiality = [0.25, 0.45, 0.7, 0.9][i % 4]
        subtype = {
            "earnings": "quarterly_results",
            "guidance": "revenue_guidance",
            "regulatory": "agency_action",
            "product": "launch_or_delay",
            "security": "incident",
            "filing": "8-k",
        }[event_type]
        event_time = pd.Timestamp(d)
        if session == "after_close":
            event_time = event_time + pd.Timedelta(hours=16, minutes=10)
            reaction_date = dates[dates.searchsorted(pd.Timestamp(d), side="right")]
        elif session == "before_open":
            event_time = event_time + pd.Timedelta(hours=8, minutes=5)
            reaction_date = dates[dates.searchsorted(pd.Timestamp(d), side="left")]
        else:
            event_time = event_time + pd.Timedelta(hours=12, minutes=30)
            reaction_date = dates[dates.searchsorted(pd.Timestamp(d), side="left")]

        event_rows.append(
            {
                "event_id": f"demo_{i+1:03d}",
                "ticker": ticker,
                "event_time": event_time.isoformat(),
                "event_type": event_type,
                "summary": f"Synthetic {event_type} event for {ticker}; direction={direction}, magnitude={magnitude}.",
                "event_subtype": subtype,
                "source_type": "synthetic_demo",
                "source_url": "",
                "release_session": session,
                "expectedness": "surprise" if i % 4 != 0 else "partial_surprise",
                "surprise_direction": direction,
                "surprise_magnitude": magnitude,
                "materiality": materiality,
                "sector_benchmark": "XLK",
                "notes": "Synthetic row. Do not use for financial conclusions.",
            }
        )

        # Inject a stylized reaction so tests and demos have non-random behavior.
        idx = dates.get_loc(reaction_date)
        shock_scale = {"low": 0.006, "medium": 0.015, "high": 0.035}[magnitude]
        if direction == "positive":
            shock = shock_scale * materiality
        elif direction == "negative":
            shock = -shock_scale * materiality
        elif direction == "mixed":
            shock = rng.normal(0, shock_scale * 0.35)
        else:
            shock = rng.normal(0, shock_scale * 0.15)
        logs[ticker][idx] += shock
        if idx + 1 < n and abs(shock) > 0.01:
            logs[ticker][idx + 1] += shock * 0.25

    for ticker in DEMO_TICKERS:
        price = 100 * np.exp(np.cumsum(logs[ticker]))
        # Create plausible OHLC around adjusted close.
        close = price
        open_ = close * np.exp(rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, n))
        volume = rng.integers(1_000_000, 8_000_000, n)
        df = pd.DataFrame(
            {
                "date": dates,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adj_close": close,
                "volume": volume,
            }
        )
        df.to_csv(prices_dir / f"{ticker}.csv", index=False)

    events = pd.DataFrame(event_rows)
    events.to_csv(events_path, index=False)
    return {"root": root, "prices_dir": prices_dir, "events": events_path}


def generate_earnings_demo_data(root: str | Path, seed: int = 7) -> dict[str, Path]:
    """Generate a synthetic earnings-only sector corpus with EPS surprises.

    This is for plumbing and testability. It intentionally injects event shocks
    correlated with EPS surprises, but also dampens reactions after large
    pre-event run-ups to mimic the core expectation problem.
    """
    rng = np.random.default_rng(seed)
    root = Path(root)
    prices_dir = ensure_dir(root / "prices")
    events_path = root / "earnings_events.csv"
    dates = pd.bdate_range("2018-01-02", "2024-12-31")
    n = len(dates)
    tickers = ["ACME", "BETA", "OMEGA", "SPY", "XLK"]

    spy_log = rng.normal(loc=0.00025, scale=0.009, size=n)
    xlk_log = 0.00010 + 1.15 * spy_log + rng.normal(loc=0, scale=0.006, size=n)
    logs = {
        "SPY": spy_log,
        "XLK": xlk_log,
        "ACME": 0.00010 + 1.15 * spy_log + 0.45 * xlk_log + rng.normal(0, 0.013, n),
        "BETA": 0.00005 + 0.95 * spy_log + 0.50 * xlk_log + rng.normal(0, 0.014, n),
        "OMEGA": 0.00008 + 1.05 * spy_log + 0.35 * xlk_log + rng.normal(0, 0.016, n),
    }

    rows = []
    company_tickers = ["ACME", "BETA", "OMEGA"]
    fiscal_dates = pd.bdate_range("2018-03-30", "2024-10-31", freq="63B")
    i = 0
    for ticker_idx, ticker in enumerate(company_tickers):
        base_eps = 1.00 + 0.25 * ticker_idx
        for q, fiscal_end in enumerate(fiscal_dates):
            report_date_idx = min(len(dates) - 2, dates.searchsorted(fiscal_end) + 18 + (ticker_idx * 3) % 8)
            report_day = dates[report_date_idx]
            session = "after_close" if (q + ticker_idx) % 2 == 0 else "before_open"
            event_time = pd.Timestamp(report_day) + (pd.Timedelta(hours=16, minutes=5) if session == "after_close" else pd.Timedelta(hours=8, minutes=5))
            reaction_idx = report_date_idx + 1 if session == "after_close" else report_date_idx
            if reaction_idx >= n:
                continue

            estimate = base_eps + 0.035 * q + rng.normal(0, 0.04)
            surprise_pct = rng.normal(0, 9.0)
            # Create occasional large beats/misses.
            if (q + ticker_idx) % 9 == 0:
                surprise_pct += 22.0
            if (q + ticker_idx) % 11 == 0:
                surprise_pct -= 24.0
            surprise = estimate * surprise_pct / 100.0
            reported = estimate + surprise
            abs_surprise_pct = abs(surprise_pct)
            direction = "positive" if surprise_pct > 0.25 else ("negative" if surprise_pct < -0.25 else "neutral")
            if abs_surprise_pct >= 20:
                magnitude = "high"
                expectedness = "surprise"
            elif abs_surprise_pct >= 8:
                magnitude = "medium"
                expectedness = "surprise"
            elif abs_surprise_pct >= 2:
                magnitude = "low"
                expectedness = "partial_surprise"
            else:
                magnitude = "none"
                expectedness = "expected"

            # Shock is partly dampened by a pre-event run-up to mimic "already priced in" behavior.
            pre_20 = float(np.sum(logs[ticker][max(0, reaction_idx - 20): reaction_idx]))
            raw_shock = 0.0018 * surprise_pct
            shock = raw_shock - 0.35 * pre_20 + rng.normal(0, 0.008)
            shock = float(np.clip(shock, -0.09, 0.09))
            logs[ticker][reaction_idx] += shock
            if reaction_idx + 1 < n:
                logs[ticker][reaction_idx + 1] += 0.20 * shock + rng.normal(0, 0.004)

            fiscal_label = pd.Timestamp(fiscal_end).date().isoformat()
            reported_label = pd.Timestamp(report_day).date().isoformat()
            i += 1
            rows.append(
                {
                    "event_id": f"{ticker}_demo_earnings_{i:03d}",
                    "ticker": ticker,
                    "event_time": event_time.isoformat(),
                    "event_type": "earnings",
                    "summary": (
                        f"Synthetic {ticker} EPS {reported:.2f} vs estimate {estimate:.2f}; "
                        f"surprise {surprise_pct:.1f}%."
                    ),
                    "event_subtype": "quarterly_eps",
                    "source_type": "synthetic_earnings_demo",
                    "source_url": "",
                    "release_session": session,
                    "expectedness": expectedness,
                    "surprise_direction": direction,
                    "surprise_magnitude": magnitude,
                    "materiality": 0.5,
                    "sector_benchmark": "XLK",
                    "notes": "Synthetic earnings row. Do not use for financial conclusions.",
                    "fiscal_date_ending": fiscal_label,
                    "reported_date": reported_label,
                    "reported_eps": round(reported, 4),
                    "estimated_eps": round(estimate, 4),
                    "eps_estimate": round(estimate, 4),
                    "actual_eps": round(reported, 4),
                    "consensus_eps": round(estimate, 4),
                    "eps_surprise": round(surprise, 4),
                    "eps_surprise_pct": round(surprise_pct / 100.0, 6),
                    "earnings_surprise_abs_max_pct": round(abs_surprise_pct / 100.0, 6),
                    "eps_abs_surprise_pct": round(abs_surprise_pct, 4),
                    "eps_signal_strength": round(min(abs_surprise_pct / 20.0, 3.0), 4),
                    "expectation_source": "synthetic_consensus",
                    "expectation_quality": "synthetic_demo",
                    "expectation_confidence": 1.0,
                    "earnings_source": "synthetic",
                }
            )

    for ticker in tickers:
        price = 100 * np.exp(np.cumsum(logs[ticker]))
        close = price
        open_ = close * np.exp(rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, n))
        volume = rng.integers(1_000_000, 8_000_000, n)
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

    pd.DataFrame(rows).sort_values(["event_time", "ticker"]).to_csv(events_path, index=False)
    return {"root": root, "prices_dir": prices_dir, "events": events_path}
