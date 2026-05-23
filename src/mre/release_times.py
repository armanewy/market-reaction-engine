from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .events import load_events
from .paths import ensure_parent

RELEASE_TIME_COLUMNS = [
    "event_id",
    "ticker",
    "exact_release_time",
    "release_session",
    "release_time_confidence",
    "release_time_source_type",
    "release_time_source_url",
    "release_time_notes",
]

RELEASE_TIME_ALIASES = {
    "release_time": "exact_release_time",
    "released_at": "exact_release_time",
    "timestamp": "exact_release_time",
    "accepted_at": "exact_release_time",
    "acceptanceDateTime": "exact_release_time",
    "source": "release_time_source_type",
    "source_url": "release_time_source_url",
    "confidence": "release_time_confidence",
    "notes": "release_time_notes",
}

VALID_RELEASE_SESSIONS = {"before_open", "intraday", "after_close", "unknown"}


@dataclass(frozen=True)
class ReleaseSessionThresholds:
    """U.S. equity market thresholds in local exchange time.

    The values are intentionally simple because this project operates on daily
    bars.  They are used to decide which trading day can first reflect a release.
    """

    market_open_hour: int = 9
    market_open_minute: int = 30
    market_close_hour: int = 16
    market_close_minute: int = 0


def _normalize_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    for src, dst in RELEASE_TIME_ALIASES.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def normalize_timestamp(value: object) -> pd.Timestamp:
    """Parse a timestamp and drop timezone info after converting to local-naive.

    Event-study code currently uses timezone-naive pandas timestamps.  If a feed
    provides timezone-aware strings, pandas will parse them; we then remove the
    timezone after conversion so downstream comparisons remain consistent.
    """

    ts = pd.Timestamp(pd.to_datetime(value, errors="coerce"))
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is not None:
        try:
            ts = ts.tz_convert(None)
        except TypeError:
            ts = ts.tz_localize(None)
    return ts


def infer_release_session(value: object, thresholds: ReleaseSessionThresholds | None = None) -> str:
    thresholds = thresholds or ReleaseSessionThresholds()
    ts = normalize_timestamp(value)
    if pd.isna(ts):
        return "unknown"
    minutes = int(ts.hour) * 60 + int(ts.minute)
    open_minutes = thresholds.market_open_hour * 60 + thresholds.market_open_minute
    close_minutes = thresholds.market_close_hour * 60 + thresholds.market_close_minute
    if minutes < open_minutes:
        return "before_open"
    if minutes >= close_minutes:
        return "after_close"
    return "intraday"


def make_release_times_template(events_path: str | Path, out_path: str | Path) -> pd.DataFrame:
    events = load_events(events_path)
    rows: list[dict[str, object]] = []
    for _, row in events.iterrows():
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "exact_release_time": "",
                "release_session": "",
                "release_time_confidence": "manual_review_required",
                "release_time_source_type": "manual_or_vendor",
                "release_time_source_url": "",
                "release_time_notes": "Use primary-source release time when possible; do not infer from post-event price action.",
            }
        )
    df = pd.DataFrame(rows, columns=RELEASE_TIME_COLUMNS)
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def _load_release_times(path: str | Path, key: str) -> pd.DataFrame:
    raw = _normalize_alias_columns(pd.read_csv(path))
    if key not in raw.columns:
        raise ValueError(f"Release-time file must contain merge key {key!r}")
    if "exact_release_time" not in raw.columns:
        raise ValueError("Release-time file must contain exact_release_time or an alias such as release_time")
    raw[key] = raw[key].astype(str)
    if raw[key].duplicated().any():
        dupes = raw.loc[raw[key].duplicated(), key].tolist()
        raise ValueError(f"Duplicate release-time rows for {key}: {dupes[:10]}")
    raw["exact_release_time"] = raw["exact_release_time"].map(normalize_timestamp)
    bad = raw[raw["exact_release_time"].isna()]
    if not bad.empty:
        raise ValueError(f"Could not parse exact_release_time for keys: {bad[key].head(10).tolist()}")
    if "release_session" not in raw.columns:
        raw["release_session"] = ""
    inferred = raw["exact_release_time"].map(infer_release_session)
    raw["release_session"] = raw["release_session"].fillna("").astype(str).str.lower().str.strip()
    raw.loc[raw["release_session"].isin(["", "nan", "none", "unknown"]), "release_session"] = inferred
    invalid = sorted(set(raw["release_session"]) - VALID_RELEASE_SESSIONS)
    if invalid:
        raise ValueError(f"Invalid release_session values in release-time file: {invalid}")
    for col in RELEASE_TIME_COLUMNS:
        if col not in raw.columns:
            raw[col] = ""
    return raw


def merge_release_times(
    events_path: str | Path,
    release_times_path: str | Path,
    out_path: str | Path,
    *,
    key: str = "event_id",
    require_all_events: bool = False,
) -> pd.DataFrame:
    """Merge exact release timestamps into an event CSV.

    This updates event_time and release_session using externally curated release
    times.  It deliberately does not derive labels from market reaction data.
    """

    events = load_events(events_path)
    if key not in events.columns:
        raise ValueError(f"Events file must contain merge key {key!r}")
    releases = _load_release_times(release_times_path, key)
    base = events.copy()
    base[key] = base[key].astype(str)
    merged = base.merge(
        releases[[key] + [c for c in RELEASE_TIME_COLUMNS if c != key]],
        on=key,
        how="left",
        suffixes=("", "_release"),
    )
    matched = merged["exact_release_time"].notna()
    if require_all_events and not matched.all():
        missing = merged.loc[~matched, key].head(10).tolist()
        raise ValueError(f"Missing release-time rows for events: {missing}")

    merged["original_event_time"] = merged["event_time"]
    merged.loc[matched, "event_time"] = merged.loc[matched, "exact_release_time"]
    if "release_session_release" in merged.columns:
        # Defensive branch if source events already contained a suffixed column.
        sess = merged["release_session_release"]
    else:
        sess = merged["release_session"]
    merged.loc[matched, "release_session"] = sess.loc[matched]
    merged["release_time_status"] = "missing"
    merged.loc[matched, "release_time_status"] = "exact"
    for col in ["release_time_confidence", "release_time_source_type", "release_time_source_url", "release_time_notes"]:
        if col not in merged.columns:
            merged[col] = ""
    # Keep event_time human-readable in CSV.
    merged["event_time"] = pd.to_datetime(merged["event_time"], errors="coerce")
    merged["original_event_time"] = pd.to_datetime(merged["original_event_time"], errors="coerce")
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged
