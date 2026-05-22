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
