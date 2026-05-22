from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

REQUIRED_EVENT_COLUMNS = [
    "event_id",
    "ticker",
    "event_time",
    "event_type",
    "summary",
]

OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS = {
    "event_subtype": "unknown",
    "source_type": "unknown",
    "source_url": "",
    "release_session": "unknown",  # before_open, intraday, after_close, unknown
    "expectedness": "unknown",  # expected, partial_surprise, surprise, unknown
    "surprise_direction": "unknown",  # positive, negative, mixed, neutral, unknown
    "surprise_magnitude": "unknown",  # low, medium, high, unknown
    "materiality": 0.5,  # user-provided 0..1 score; do not infer this from price reaction
    "sector_benchmark": "",
    "notes": "",
}

VALID_RELEASE_SESSIONS = {"before_open", "intraday", "after_close", "unknown"}


def load_events(path: str | Path) -> pd.DataFrame:
    """Load and validate an event CSV.

    The event file must be point-in-time: event labels/features should only use
    information known at or before event_time, not the subsequent price move.
    """
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_EVENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required event columns: {missing}")

    for col, default in OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default

    df["event_id"] = df["event_id"].astype(str)
    if df["event_id"].duplicated().any():
        dupes = df.loc[df["event_id"].duplicated(), "event_id"].tolist()
        raise ValueError(f"Duplicate event_id values found: {dupes[:10]}")

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    if df["event_time"].isna().any():
        bad = df.loc[df["event_time"].isna(), "event_id"].tolist()
        raise ValueError(f"Could not parse event_time for events: {bad[:10]}")

    df["release_session"] = (
        df["release_session"].fillna("unknown").astype(str).str.lower().str.strip()
    )
    invalid_sessions = sorted(set(df["release_session"]) - VALID_RELEASE_SESSIONS)
    if invalid_sessions:
        raise ValueError(
            "Invalid release_session values. Use before_open, intraday, after_close, or unknown. "
            f"Found: {invalid_sessions}"
        )

    df["materiality"] = pd.to_numeric(df["materiality"], errors="coerce").fillna(0.5)
    df["materiality"] = df["materiality"].clip(0.0, 1.0)

    for col in [
        "event_type",
        "event_subtype",
        "source_type",
        "expectedness",
        "surprise_direction",
        "surprise_magnitude",
        "sector_benchmark",
    ]:
        df[col] = df[col].fillna("unknown").astype(str).str.lower().str.strip()

    df["sector_benchmark"] = df["sector_benchmark"].replace({"unknown": "", "nan": ""}).str.upper()
    df = df.sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    return df


def event_tickers(events: pd.DataFrame, benchmark: str | None = None) -> list[str]:
    tickers = set(events["ticker"].dropna().astype(str).str.upper())
    sectors = set(events["sector_benchmark"].dropna().astype(str).str.upper())
    sectors.discard("")
    sectors.discard("UNKNOWN")
    if benchmark:
        tickers.add(benchmark.upper())
    tickers |= sectors
    return sorted(tickers)


def make_event_template(path: str | Path, rows: Iterable[dict] | None = None) -> None:
    columns = REQUIRED_EVENT_COLUMNS + list(OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS.keys())
    df = pd.DataFrame(list(rows or []), columns=columns)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
