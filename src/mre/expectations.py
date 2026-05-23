from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import exp, sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import event_tickers, load_events
from .event_study import sum_log_returns
from .paths import ensure_parent
from .prices import load_log_returns, load_price_csv

EXPECTATION_COLUMNS = [
    "event_id",
    "ticker",
    "asof_time",
    "consensus_eps",
    "actual_eps",
    "consensus_forward_eps",
    "guidance_eps_low",
    "guidance_eps_high",
    "guidance_eps_mid",
    "consensus_revenue",
    "actual_revenue",
    "consensus_forward_revenue",
    "guidance_revenue_low",
    "guidance_revenue_high",
    "guidance_revenue_mid",
    "consensus_gross_margin",
    "actual_gross_margin",
    "consensus_forward_gross_margin",
    "guidance_gross_margin_low",
    "guidance_gross_margin_high",
    "guidance_gross_margin_mid",
    "implied_move_pct",
    "analyst_count",
    "expectation_source_type",
    "expectation_source_url",
    "expectation_notes",
]

NUMERIC_EXPECTATION_COLUMNS = [
    "consensus_eps",
    "actual_eps",
    "consensus_forward_eps",
    "guidance_eps_low",
    "guidance_eps_high",
    "guidance_eps_mid",
    "consensus_revenue",
    "actual_revenue",
    "consensus_forward_revenue",
    "guidance_revenue_low",
    "guidance_revenue_high",
    "guidance_revenue_mid",
    "consensus_gross_margin",
    "actual_gross_margin",
    "consensus_forward_gross_margin",
    "guidance_gross_margin_low",
    "guidance_gross_margin_high",
    "guidance_gross_margin_mid",
    "implied_move_pct",
    "analyst_count",
]

DERIVED_EXPECTATION_COLUMNS = [
    "eps_surprise",
    "eps_surprise_pct",
    "guidance_eps_surprise",
    "guidance_eps_surprise_pct",
    "revenue_surprise",
    "revenue_surprise_pct",
    "guidance_revenue_surprise",
    "guidance_revenue_surprise_pct",
    "gross_margin_surprise",
    "gross_margin_surprise_pct",
    "guidance_gross_margin_surprise",
    "guidance_gross_margin_surprise_pct",
    "fundamental_surprise_score",
    "surprise_signal_count",
    "surprise_direction_inferred",
    "surprise_magnitude_inferred",
    "has_expectation_data",
    "earnings_surprise_abs_max_pct",
]

PRICE_EXPECTATION_NUMERIC_COLUMNS = [
    "pre_return_5d",
    "pre_return_20d",
    "pre_return_60d",
    "benchmark_pre_return_5d",
    "benchmark_pre_return_20d",
    "benchmark_pre_return_60d",
    "market_adjusted_pre_return_5d",
    "market_adjusted_pre_return_20d",
    "market_adjusted_pre_return_60d",
    "sector_adjusted_pre_return_5d",
    "sector_adjusted_pre_return_20d",
    "sector_adjusted_pre_return_60d",
    "pre_vol_20d",
    "pre_vol_60d",
    "benchmark_pre_vol_20d",
    "rolling_beta_60d",
    "idiosyncratic_vol_60d",
    "expected_abs_move_h1_realized_vol_20d",
    "expected_abs_move_h3_realized_vol_20d",
    "expected_abs_move_h10_realized_vol_20d",
    "volume_zscore_20d",
    "surprise_vs_runup_score",
]

ALIAS_COLUMNS = {
    "estimated_eps": "consensus_eps",
    "eps_estimate": "consensus_eps",
    "reported_eps": "actual_eps",
    "reportedEPS": "actual_eps",
    "estimatedEPS": "consensus_eps",
    "surprisePercentage": "eps_surprise_pct",
    "surprise_pct": "eps_surprise_pct",
    "eps_surprise_percent": "eps_surprise_pct",
    "reported_revenue": "actual_revenue",
    "estimated_revenue": "consensus_revenue",
    "revenue_estimate": "consensus_revenue",
    "sales_estimate": "consensus_revenue",
    "reported_gross_margin": "actual_gross_margin",
    "estimated_gross_margin": "consensus_gross_margin",
    "gross_margin_estimate": "consensus_gross_margin",
    "forward_revenue_estimate": "consensus_forward_revenue",
    "forward_eps_estimate": "consensus_forward_eps",
    "forward_gross_margin_estimate": "consensus_forward_gross_margin",
    "expectations_timestamp": "asof_time",
}


@dataclass
class PriceExpectationDiagnostics:
    events_total: int = 0
    events_with_price_features: int = 0
    events_skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_skip(self, reason: str) -> None:
        self.events_skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_numeric(value: object) -> float:
    if value is None:
        return np.nan
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null", "-", "--", "n/a", "na"}:
        return np.nan
    percent = text.endswith("%")
    text = text.replace("%", "").replace(",", "").replace("$", "")
    try:
        val = float(text)
    except ValueError:
        return np.nan
    return val / 100.0 if percent else val


def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~pd.Index(df.columns).duplicated()].copy()


def _normalize_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = _dedupe_columns(df)
    for src, dst in ALIAS_COLUMNS.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def coerce_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    pct_like = {
        "implied_move_pct",
        "eps_surprise_pct",
        "guidance_eps_surprise_pct",
        "revenue_surprise_pct",
        "guidance_revenue_surprise_pct",
        "gross_margin_surprise_pct",
        "guidance_gross_margin_surprise_pct",
        "consensus_gross_margin",
        "actual_gross_margin",
        "consensus_forward_gross_margin",
        "guidance_gross_margin_low",
        "guidance_gross_margin_high",
        "guidance_gross_margin_mid",
    }
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(_clean_numeric)
            if col in pct_like:
                mask = out[col].abs() > 1.0
                out.loc[mask, col] = out.loc[mask, col] / 100.0
    return out


def safe_pct_delta(actual: pd.Series, expected: pd.Series) -> pd.Series:
    denom = pd.to_numeric(expected, errors="coerce").abs().replace({0.0: np.nan})
    return (pd.to_numeric(actual, errors="coerce") - pd.to_numeric(expected, errors="coerce")) / denom


def _mid_from_low_high(df: pd.DataFrame, mid_col: str, low_col: str, high_col: str) -> pd.Series:
    existing = pd.to_numeric(df.get(mid_col, np.nan), errors="coerce")
    low = pd.to_numeric(df.get(low_col, np.nan), errors="coerce")
    high = pd.to_numeric(df.get(high_col, np.nan), errors="coerce")
    computed = (low + high) / 2.0
    return existing.where(existing.notna(), computed)


def _guidance_mid(df: pd.DataFrame) -> pd.Series:
    return _mid_from_low_high(df, "guidance_revenue_mid", "guidance_revenue_low", "guidance_revenue_high")


def _infer_direction(row: pd.Series) -> str:
    vals = []
    for col in [
        "eps_surprise_pct",
        "guidance_eps_surprise_pct",
        "revenue_surprise_pct",
        "guidance_revenue_surprise_pct",
        "gross_margin_surprise_pct",
        "guidance_gross_margin_surprise_pct",
    ]:
        val = row.get(col)
        if val is not None and not pd.isna(val):
            vals.append(float(val))
    if not vals:
        return "unknown"
    score = float(np.nanmean(vals))
    if score > 0.005:
        return "positive"
    if score < -0.005:
        return "negative"
    return "neutral"


def _infer_magnitude(score: object) -> str:
    if score is None or pd.isna(score):
        return "unknown"
    av = abs(float(score))
    if av >= 0.65:
        return "high"
    if av >= 0.25:
        return "medium"
    if av > 0:
        return "low"
    return "neutral"


def compute_expectation_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute EPS/revenue/guidance surprise features without using prices."""
    out = _normalize_alias_columns(df)
    for col in EXPECTATION_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    out = coerce_numeric_columns(
        out,
        NUMERIC_EXPECTATION_COLUMNS
        + [
            "eps_surprise_pct",
            "guidance_eps_surprise_pct",
            "revenue_surprise_pct",
            "guidance_revenue_surprise_pct",
            "gross_margin_surprise_pct",
            "guidance_gross_margin_surprise_pct",
        ],
    )

    out["eps_surprise"] = pd.to_numeric(out["actual_eps"], errors="coerce") - pd.to_numeric(out["consensus_eps"], errors="coerce")
    computed_eps_pct = safe_pct_delta(out["actual_eps"], out["consensus_eps"])
    if "eps_surprise_pct" in out.columns:
        out["eps_surprise_pct"] = pd.to_numeric(out["eps_surprise_pct"], errors="coerce").where(pd.to_numeric(out["eps_surprise_pct"], errors="coerce").notna(), computed_eps_pct)
    else:
        out["eps_surprise_pct"] = computed_eps_pct

    out["guidance_eps_mid"] = _mid_from_low_high(out, "guidance_eps_mid", "guidance_eps_low", "guidance_eps_high")
    out["guidance_eps_surprise"] = out["guidance_eps_mid"] - pd.to_numeric(out["consensus_forward_eps"], errors="coerce")
    out["guidance_eps_surprise_pct"] = safe_pct_delta(out["guidance_eps_mid"], out["consensus_forward_eps"])

    out["revenue_surprise"] = pd.to_numeric(out["actual_revenue"], errors="coerce") - pd.to_numeric(out["consensus_revenue"], errors="coerce")
    out["revenue_surprise_pct"] = safe_pct_delta(out["actual_revenue"], out["consensus_revenue"])
    out["guidance_revenue_mid"] = _guidance_mid(out)
    out["guidance_revenue_surprise"] = out["guidance_revenue_mid"] - pd.to_numeric(out["consensus_forward_revenue"], errors="coerce")
    out["guidance_revenue_surprise_pct"] = safe_pct_delta(out["guidance_revenue_mid"], out["consensus_forward_revenue"])

    out["gross_margin_surprise"] = pd.to_numeric(out["actual_gross_margin"], errors="coerce") - pd.to_numeric(out["consensus_gross_margin"], errors="coerce")
    out["gross_margin_surprise_pct"] = safe_pct_delta(out["actual_gross_margin"], out["consensus_gross_margin"])
    out["guidance_gross_margin_mid"] = _mid_from_low_high(out, "guidance_gross_margin_mid", "guidance_gross_margin_low", "guidance_gross_margin_high")
    out["guidance_gross_margin_surprise"] = out["guidance_gross_margin_mid"] - pd.to_numeric(out["consensus_forward_gross_margin"], errors="coerce")
    out["guidance_gross_margin_surprise_pct"] = safe_pct_delta(out["guidance_gross_margin_mid"], out["consensus_forward_gross_margin"])

    components = [
        "eps_surprise_pct",
        "guidance_eps_surprise_pct",
        "revenue_surprise_pct",
        "guidance_revenue_surprise_pct",
        "gross_margin_surprise_pct",
        "guidance_gross_margin_surprise_pct",
    ]
    score_frame = pd.concat([np.tanh(pd.to_numeric(out[c], errors="coerce") / 0.05) for c in components], axis=1)
    out["fundamental_surprise_score"] = score_frame.mean(axis=1, skipna=True)
    out["surprise_signal_count"] = score_frame.notna().sum(axis=1).astype(float)
    out["surprise_direction_inferred"] = out.apply(_infer_direction, axis=1)
    out["surprise_magnitude_inferred"] = out["fundamental_surprise_score"].map(_infer_magnitude)
    out["has_expectation_data"] = out["surprise_signal_count"].fillna(0).astype(float) > 0
    out["earnings_surprise_abs_max_pct"] = pd.concat(
        [
            pd.to_numeric(out["eps_surprise_pct"], errors="coerce").abs(),
            pd.to_numeric(out["guidance_eps_surprise_pct"], errors="coerce").abs(),
            pd.to_numeric(out["revenue_surprise_pct"], errors="coerce").abs(),
            pd.to_numeric(out["guidance_revenue_surprise_pct"], errors="coerce").abs(),
            pd.to_numeric(out["gross_margin_surprise_pct"], errors="coerce").abs(),
            pd.to_numeric(out["guidance_gross_margin_surprise_pct"], errors="coerce").abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    return out


def make_expectations_template(events_path: str | Path, out_path: str | Path) -> pd.DataFrame:
    events = load_events(events_path)
    rows = []
    for _, r in events.iterrows():
        rows.append(
            {
                "event_id": r["event_id"],
                "ticker": r["ticker"],
                "asof_time": "",
                "expectation_source_type": "manual_or_vendor",
                "expectation_notes": "Fill with point-in-time consensus/options data known before event_time.",
            }
        )
    df = pd.DataFrame(rows)
    for col in EXPECTATION_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan if col in NUMERIC_EXPECTATION_COLUMNS else ""
    df = df[EXPECTATION_COLUMNS]
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def load_expectations(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _normalize_alias_columns(df)
    if "event_id" not in df.columns:
        raise ValueError("Expectations file must contain event_id")
    df["event_id"] = df["event_id"].astype(str)
    if df["event_id"].duplicated().any():
        dupes = df.loc[df["event_id"].duplicated(), "event_id"].tolist()
        raise ValueError(f"Duplicate expectation event_id values found: {dupes[:10]}")
    return compute_expectation_features(df)


def _fill_event_labels(merged: pd.DataFrame) -> pd.DataFrame:
    out = merged.copy()
    if "surprise_direction" in out.columns and "surprise_direction_inferred" in out.columns:
        mask = out["surprise_direction"].fillna("unknown").astype(str).str.lower().isin(["", "unknown", "nan"])
        out.loc[mask, "surprise_direction"] = out.loc[mask, "surprise_direction_inferred"]
    if "surprise_magnitude" in out.columns and "surprise_magnitude_inferred" in out.columns:
        mask = out["surprise_magnitude"].fillna("unknown").astype(str).str.lower().isin(["", "unknown", "nan"])
        out.loc[mask, "surprise_magnitude"] = out.loc[mask, "surprise_magnitude_inferred"]
    if "expectedness" in out.columns and "has_expectation_data" in out.columns:
        mask = out["expectedness"].fillna("unknown").astype(str).str.lower().isin(["", "unknown", "nan"])
        out.loc[mask & out["has_expectation_data"].fillna(False).astype(bool), "expectedness"] = "point_in_time_expectation_available"
    return out


def _merge_expectation_features(base: pd.DataFrame, expectations: pd.DataFrame, *, key: str = "event_id", fill_labels: bool = False) -> pd.DataFrame:
    if key not in base.columns or key not in expectations.columns:
        raise ValueError(f"Merge key {key!r} must exist in both frames")
    base = _dedupe_columns(base).copy()
    exp = _dedupe_columns(expectations).copy()
    base[key] = base[key].astype(str)
    exp[key] = exp[key].astype(str)

    passthrough_exclude = {key, "ticker", "event_time", "event_type", "event_subtype", "summary"}
    exp_cols = [c for c in exp.columns if c not in passthrough_exclude]
    merged = base.merge(exp[[key] + exp_cols], on=key, how="left", suffixes=("", "_expectation"))
    for col in exp_cols:
        suff = f"{col}_expectation"
        if suff in merged.columns:
            merged[col] = merged[suff].where(merged[suff].notna(), merged[col])
            merged = merged.drop(columns=[suff])
    merged["expectation_rows_matched"] = merged[[c for c in DERIVED_EXPECTATION_COLUMNS + EXPECTATION_COLUMNS if c in merged.columns and c != key]].notna().any(axis=1)
    if fill_labels:
        merged = _fill_event_labels(merged)
    return _dedupe_columns(merged)


def apply_expectations_to_events(
    events_path: str | Path,
    expectations_path: str | Path,
    out_path: str | Path,
    fill_labels: bool = False,
) -> pd.DataFrame:
    events = load_events(events_path)
    expectations = load_expectations(expectations_path)
    merged = _merge_expectation_features(events, expectations, fill_labels=fill_labels)
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged


def _check_expectation_leakage(events: pd.DataFrame, raw: pd.DataFrame, key: str, fail_on_leakage: bool) -> None:
    if not fail_on_leakage:
        return
    time_col = "asof_time" if "asof_time" in raw.columns else "expectations_timestamp" if "expectations_timestamp" in raw.columns else None
    if time_col is None:
        return
    check = events[[key, "event_time"]].copy()
    check[key] = check[key].astype(str)
    check = check.merge(raw[[key, time_col]], on=key, how="inner")
    check[time_col] = pd.to_datetime(check[time_col], errors="coerce")
    check["event_time"] = pd.to_datetime(check["event_time"], errors="coerce")
    leaked = check[check[time_col].notna() & check["event_time"].notna() & (check[time_col] > check["event_time"])]
    if not leaked.empty:
        raise ValueError(
            "Potential lookahead leakage: some expectation asof_time values are after event_time. "
            f"Example keys: {leaked[key].head(5).tolist()}"
        )


def merge_external_expectations(
    events_path: str | Path,
    external_expectations_path: str | Path,
    out_path: str | Path,
    *,
    key: str = "event_id",
    fail_on_leakage: bool = True,
    fill_labels: bool = False,
) -> pd.DataFrame:
    events = load_events(events_path)
    raw = _normalize_alias_columns(pd.read_csv(external_expectations_path))
    if key not in raw.columns or key not in events.columns:
        raise ValueError(f"Merge key {key!r} must exist in both events and external expectations")
    raw[key] = raw[key].astype(str)
    if raw[key].duplicated().any():
        dupes = raw.loc[raw[key].duplicated(), key].tolist()
        raise ValueError(f"Duplicate expectation rows for key {key}: {dupes[:10]}")
    _check_expectation_leakage(events, raw, key, fail_on_leakage)
    computed = compute_expectation_features(raw)
    merged = _merge_expectation_features(events, computed, key=key, fill_labels=fill_labels)
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged


def enrich_event_study_with_expectations(
    event_study_path: str | Path,
    expectations_path: str | Path,
    out_path: str | Path,
    fill_labels: bool = False,
) -> pd.DataFrame:
    base = _dedupe_columns(pd.read_csv(event_study_path))
    expectations = load_expectations(expectations_path)
    merged = _merge_expectation_features(base, expectations, fill_labels=fill_labels)
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged


def _simple_from_log(log_return: float) -> float:
    if pd.isna(log_return):
        return np.nan
    return float(exp(float(log_return)) - 1.0)


def _bucket_runup(z: float) -> str:
    if pd.isna(z):
        return "unknown"
    if z >= 1.0:
        return "strong_positive"
    if z >= 0.35:
        return "positive"
    if z <= -1.0:
        return "strong_negative"
    if z <= -0.35:
        return "negative"
    return "neutral"


def _normalize_ts(ts: object) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is not None:
        out = out.tz_convert(None) if getattr(out, "tz", None) is not None else out.tz_localize(None)
    return out


def _last_pre_event_day(index: pd.DatetimeIndex, event_time: pd.Timestamp, release_session: str) -> pd.Timestamp | None:
    event_date = _normalize_ts(event_time).normalize()
    side = "right" if str(release_session).lower() == "after_close" else "left"
    pos = index.searchsorted(event_date, side=side) - 1
    if pos < 0:
        return None
    return pd.Timestamp(index[pos])


def _tail_log_sum(series: pd.Series, n: int) -> float:
    s = series.dropna().tail(n)
    if len(s) < n:
        return np.nan
    return sum_log_returns(s)


def _tail_vol(series: pd.Series, n: int, min_history: int) -> float:
    s = series.dropna().tail(n)
    if len(s) < min(min_history, n):
        return np.nan
    return float(s.std(ddof=1))


def _rolling_beta_and_resid(ticker_returns: pd.Series, benchmark_returns: pd.Series, n: int, min_history: int) -> tuple[float, float]:
    data = pd.concat([ticker_returns, benchmark_returns], axis=1).dropna().tail(n)
    if len(data) < min(min_history, n):
        return np.nan, np.nan
    y = data.iloc[:, 0].to_numpy(dtype=float)
    x = data.iloc[:, 1].to_numpy(dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    alpha, beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - (alpha + beta * x)
    resid_std = float(np.std(resid, ddof=2)) if len(resid) > 2 else float(np.std(resid))
    return float(beta), resid_std


def _volume_zscore(prices_dir: str | Path, ticker: str, pre_day: pd.Timestamp, window: int = 20) -> float:
    try:
        px = load_price_csv(prices_dir, ticker)
    except Exception:
        return np.nan
    px = px[px["date"] <= pre_day].copy()
    if len(px) < window + 1 or "volume" not in px.columns:
        return np.nan
    vols = pd.to_numeric(px["volume"], errors="coerce").dropna().tail(window + 1)
    if len(vols) < window + 1:
        return np.nan
    current = float(vols.iloc[-1])
    hist = vols.iloc[:-1]
    sd = float(hist.std(ddof=1))
    if sd <= 0 or pd.isna(sd):
        return np.nan
    return float((current - float(hist.mean())) / sd)


def add_price_expectation_features(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    windows: tuple[int, ...] = (5, 20, 60),
    horizons: tuple[int, ...] = (1, 3, 10),
    min_history: int = 20,
) -> tuple[pd.DataFrame, PriceExpectationDiagnostics]:
    """Add pre-event price proxies without peeking at the post-event reaction."""
    events = load_events(events_path)
    benchmark = benchmark_ticker.upper()
    tickers = event_tickers(events, benchmark=benchmark)
    returns = load_log_returns(prices_dir, tickers)
    returns.columns = [str(c).upper() for c in returns.columns]
    returns = returns.sort_index()
    diag = PriceExpectationDiagnostics(events_total=len(events))
    rows: list[dict] = []

    for _, event in events.iterrows():
        row = event.to_dict()
        ticker = str(event["ticker"]).upper()
        if ticker not in returns.columns:
            reason = f"missing ticker returns: {ticker}"
            row["expectation_feature_status"] = "skipped"
            row["expectation_feature_reason"] = reason
            diag.add_skip(reason)
            rows.append(row)
            continue

        pre_day = _last_pre_event_day(returns.index, event["event_time"], event.get("release_session", "unknown"))
        if pre_day is None:
            reason = "no pre-event trading day"
            row["expectation_feature_status"] = "skipped"
            row["expectation_feature_reason"] = reason
            diag.add_skip(reason)
            rows.append(row)
            continue

        hist = returns.loc[:pre_day]
        if len(hist) < min_history:
            reason = "not enough pre-event history"
            row["expectation_feature_status"] = "skipped"
            row["expectation_feature_reason"] = reason
            diag.add_skip(reason)
            rows.append(row)
            continue

        for w in windows:
            ticker_log = _tail_log_sum(hist[ticker], w)
            row[f"pre_return_{w}d"] = _simple_from_log(ticker_log)
            if benchmark in hist.columns:
                bench_log = _tail_log_sum(hist[benchmark], w)
                row[f"benchmark_pre_return_{w}d"] = _simple_from_log(bench_log)
                row[f"market_adjusted_pre_return_{w}d"] = _simple_from_log(ticker_log - bench_log) if not pd.isna(ticker_log) and not pd.isna(bench_log) else np.nan
            sector = str(event.get("sector_benchmark", "")).upper().strip()
            if sector and sector in hist.columns:
                sector_log = _tail_log_sum(hist[sector], w)
                row[f"sector_adjusted_pre_return_{w}d"] = _simple_from_log(ticker_log - sector_log) if not pd.isna(ticker_log) and not pd.isna(sector_log) else np.nan

        row["pre_vol_20d"] = _tail_vol(hist[ticker], 20, min_history)
        row["pre_vol_60d"] = _tail_vol(hist[ticker], 60, min_history)
        if benchmark in hist.columns:
            row["benchmark_pre_vol_20d"] = _tail_vol(hist[benchmark], 20, min_history)
            beta, resid_vol = _rolling_beta_and_resid(hist[ticker], hist[benchmark], 60, min_history)
            row["rolling_beta_60d"] = beta
            row["idiosyncratic_vol_60d"] = resid_vol
        for h in horizons:
            row[f"expected_abs_move_h{h}_realized_vol_20d"] = float(row["pre_vol_20d"] * sqrt(h)) if not pd.isna(row.get("pre_vol_20d")) else np.nan
        row["volume_zscore_20d"] = _volume_zscore(prices_dir, ticker, pre_day, window=20)

        mar20 = row.get("market_adjusted_pre_return_20d")
        vol20 = row.get("pre_vol_20d")
        denom = float(vol20) * sqrt(20) if vol20 is not None and not pd.isna(vol20) else np.nan
        z = float(mar20) / denom if not pd.isna(mar20) and not pd.isna(denom) and denom != 0 else np.nan
        row["pre_runup_z_20d"] = z
        row["pre_runup_bucket_20d"] = _bucket_runup(z)
        fs = row.get("fundamental_surprise_score")
        row["surprise_vs_runup_score"] = float(fs) - z if fs is not None and not pd.isna(fs) and not pd.isna(z) else np.nan
        row["expectation_feature_status"] = "ok"
        row["expectation_feature_reason"] = ""
        diag.events_with_price_features += 1
        rows.append(row)

    out = compute_expectation_features(pd.DataFrame(rows))
    p = ensure_parent(out_path)
    out.to_csv(p, index=False)
    return out, diag


def add_expectation_features(*args, **kwargs) -> tuple[pd.DataFrame, PriceExpectationDiagnostics]:
    return add_price_expectation_features(*args, **kwargs)


def enrich_expectations(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
) -> pd.DataFrame:
    df, _ = add_price_expectation_features(events_path, prices_dir, out_path, benchmark_ticker=benchmark_ticker)
    return df
