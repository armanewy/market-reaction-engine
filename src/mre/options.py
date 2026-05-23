from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .events import load_events
from .paths import ensure_parent
from .release_times import normalize_timestamp

OPTION_COLUMNS = [
    "event_id",
    "ticker",
    "quote_time",
    "expiration",
    "underlying_price",
    "strike",
    "call_bid",
    "call_ask",
    "call_mid",
    "put_bid",
    "put_ask",
    "put_mid",
    "option_source_type",
    "option_source_url",
    "option_notes",
]

OPTION_ALIASES = {
    "asof_time": "quote_time",
    "timestamp": "quote_time",
    "expiry": "expiration",
    "option_expiration": "expiration",
    "underlying": "underlying_price",
    "spot": "underlying_price",
    "underlyingPrice": "underlying_price",
    "callBid": "call_bid",
    "callAsk": "call_ask",
    "putBid": "put_bid",
    "putAsk": "put_ask",
    "source": "option_source_type",
    "source_url": "option_source_url",
}

MERGED_OPTION_COLUMNS = [
    "implied_move_pct",
    "implied_move_source",
    "implied_move_asof_time",
    "implied_move_expiration",
    "implied_move_days_to_expiration",
    "implied_move_strike",
    "implied_move_underlying_price",
    "implied_move_call_mid",
    "implied_move_put_mid",
    "implied_move_option_source_type",
    "implied_move_option_source_url",
    "implied_move_notes",
]


@dataclass
class ImpliedMoveDiagnostics:
    events_total: int = 0
    events_with_implied_move: int = 0
    events_skipped: int = 0
    skipped_reasons: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.skipped_reasons is None:
            self.skipped_reasons = {}

    def add_skip(self, reason: str) -> None:
        self.events_skipped += 1
        assert self.skipped_reasons is not None
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return {
            "events_total": self.events_total,
            "events_with_implied_move": self.events_with_implied_move,
            "events_skipped": self.events_skipped,
            "skipped_reasons": self.skipped_reasons or {},
        }


def _normalize_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    for src, dst in OPTION_ALIASES.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.replace("$", "", regex=False), errors="coerce")


def make_options_template(events_path: str | Path, out_path: str | Path) -> pd.DataFrame:
    events = load_events(events_path)
    rows = []
    for _, event in events.iterrows():
        rows.append(
            {
                "event_id": event["event_id"],
                "ticker": event["ticker"],
                "quote_time": "",
                "expiration": "",
                "underlying_price": "",
                "strike": "",
                "call_bid": "",
                "call_ask": "",
                "call_mid": "",
                "put_bid": "",
                "put_ask": "",
                "put_mid": "",
                "option_source_type": "manual_or_vendor",
                "option_source_url": "",
                "option_notes": "Use a quote known before event_time; ATM straddle premium estimates expected move.",
            }
        )
    df = pd.DataFrame(rows, columns=OPTION_COLUMNS)
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def load_option_snapshots(path: str | Path) -> pd.DataFrame:
    df = _normalize_alias_columns(pd.read_csv(path))
    required = ["ticker", "quote_time", "expiration", "underlying_price", "strike"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Option snapshot file is missing required columns: {missing}")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["quote_time"] = df["quote_time"].map(normalize_timestamp)
    df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce")
    for col in ["underlying_price", "strike", "call_bid", "call_ask", "call_mid", "put_bid", "put_ask", "put_mid"]:
        if col in df.columns:
            df[col] = _clean_numeric(df[col])
        else:
            df[col] = np.nan
    df["call_mid"] = df["call_mid"].where(df["call_mid"].notna(), (df["call_bid"] + df["call_ask"]) / 2.0)
    df["put_mid"] = df["put_mid"].where(df["put_mid"].notna(), (df["put_bid"] + df["put_ask"]) / 2.0)
    bad = df[df[["quote_time", "expiration", "underlying_price", "strike", "call_mid", "put_mid"]].isna().any(axis=1)]
    if len(bad) == len(df):
        raise ValueError("No usable option rows after parsing timestamps/prices/mids")
    return df


def _select_atm_straddle(event: pd.Series, options: pd.DataFrame, max_quote_age_days: int | None) -> tuple[pd.Series | None, str]:
    ticker = str(event["ticker"]).upper()
    event_time = normalize_timestamp(event["event_time"])
    candidates = options[options["ticker"] == ticker].copy()
    if "event_id" in candidates.columns:
        exact = candidates[candidates["event_id"].astype(str) == str(event["event_id"])]
        if not exact.empty:
            candidates = exact.copy()
    candidates = candidates[candidates["quote_time"] <= event_time]
    candidates = candidates[candidates["expiration"] >= event_time.normalize()]
    if max_quote_age_days is not None:
        min_quote = event_time - pd.Timedelta(days=max_quote_age_days)
        candidates = candidates[candidates["quote_time"] >= min_quote]
    candidates = candidates.dropna(subset=["underlying_price", "strike", "call_mid", "put_mid", "expiration"])
    candidates = candidates[(candidates["underlying_price"] > 0) & (candidates["call_mid"] >= 0) & (candidates["put_mid"] >= 0)]
    if candidates.empty:
        return None, "no pre-event option quote"
    candidates["quote_age_seconds"] = (event_time - candidates["quote_time"]).dt.total_seconds()
    candidates["days_to_expiration"] = (candidates["expiration"] - event_time.normalize()).dt.days.astype(float)
    candidates["atm_distance"] = (candidates["strike"] - candidates["underlying_price"]).abs() / candidates["underlying_price"]
    candidates = candidates.sort_values(["days_to_expiration", "atm_distance", "quote_age_seconds"])
    return candidates.iloc[0], "ok"


def compute_implied_moves(
    events_path: str | Path,
    option_snapshots_path: str | Path,
    *,
    max_quote_age_days: int | None = 14,
) -> tuple[pd.DataFrame, ImpliedMoveDiagnostics]:
    events = load_events(events_path)
    options = load_option_snapshots(option_snapshots_path)
    diag = ImpliedMoveDiagnostics(events_total=len(events))
    rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        selected, reason = _select_atm_straddle(event, options, max_quote_age_days=max_quote_age_days)
        row = {"event_id": event["event_id"], "ticker": event["ticker"]}
        if selected is None:
            row["implied_move_status"] = "skipped"
            row["implied_move_reason"] = reason
            diag.add_skip(reason)
        else:
            move = float((selected["call_mid"] + selected["put_mid"]) / selected["underlying_price"])
            diag.events_with_implied_move += 1
            row.update(
                {
                    "implied_move_status": "ok",
                    "implied_move_reason": "",
                    "implied_move_pct": move,
                    "implied_move_source": "atm_straddle_mid",
                    "implied_move_asof_time": selected["quote_time"],
                    "implied_move_expiration": selected["expiration"],
                    "implied_move_days_to_expiration": selected.get("days_to_expiration", np.nan),
                    "implied_move_strike": selected["strike"],
                    "implied_move_underlying_price": selected["underlying_price"],
                    "implied_move_call_mid": selected["call_mid"],
                    "implied_move_put_mid": selected["put_mid"],
                    "implied_move_option_source_type": selected.get("option_source_type", ""),
                    "implied_move_option_source_url": selected.get("option_source_url", ""),
                    "implied_move_notes": "Estimated from nearest pre-event ATM call+put mid premium divided by underlying price.",
                }
            )
        rows.append(row)
    return pd.DataFrame(rows), diag


def merge_options_implied_moves(
    events_path: str | Path,
    option_snapshots_path: str | Path,
    out_path: str | Path,
    *,
    max_quote_age_days: int | None = 14,
) -> tuple[pd.DataFrame, ImpliedMoveDiagnostics]:
    events = load_events(events_path)
    moves, diag = compute_implied_moves(events_path, option_snapshots_path, max_quote_age_days=max_quote_age_days)
    merged = events.merge(moves, on=["event_id", "ticker"], how="left", suffixes=("", "_options"))
    if "implied_move_pct_options" in merged.columns:
        existing = pd.to_numeric(merged.get("implied_move_pct"), errors="coerce") if "implied_move_pct" in merged.columns else pd.Series(np.nan, index=merged.index)
        merged["implied_move_pct"] = existing.where(existing.notna(), merged["implied_move_pct_options"])
        merged = merged.drop(columns=["implied_move_pct_options"])
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged, diag
