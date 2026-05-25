from __future__ import annotations

from dataclasses import dataclass, field
from math import erf, exp, sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import event_tickers, load_events
from .prices import load_log_returns


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


@dataclass(frozen=True)
class EventStudyConfig:
    benchmark_ticker: str = "SPY"
    horizons: tuple[int, ...] = (1, 3, 10)
    estimation_window: int = 120
    estimation_gap: int = 5
    min_estimation_observations: int = 60
    flat_threshold: float = 0.002  # 20 bps log-abnormal-return threshold
    include_sector_adjustment: bool = True


@dataclass
class EventStudyDiagnostics:
    events_total: int = 0
    events_ok: int = 0
    events_skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_skip(self, reason: str) -> None:
        self.events_skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


def first_trading_day_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    date = pd.Timestamp(date).tz_localize(None).normalize()
    pos = index.searchsorted(date, side="left")
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def first_trading_day_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    date = pd.Timestamp(date).tz_localize(None).normalize()
    pos = index.searchsorted(date, side="right")
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def reaction_start_date(
    returns_index: pd.DatetimeIndex,
    event_time: pd.Timestamp,
    release_session: str,
) -> pd.Timestamp | None:
    """Choose the first trading day whose close can reflect the event.

    For after_close releases, the first possible daily reaction is the next
    trading day. For before_open/intraday/unknown, use the same trading day if
    available, otherwise the next trading day.
    """
    session = str(release_session or "unknown").lower().strip()
    event_date = pd.Timestamp(event_time).tz_localize(None).normalize()
    if session == "after_close":
        return first_trading_day_after(returns_index, event_date)
    return first_trading_day_on_or_after(returns_index, event_date)


def fit_market_model(estimation: pd.DataFrame, ticker: str, benchmark: str) -> tuple[float, float, float, int]:
    data = estimation[[ticker, benchmark]].dropna()
    n = int(len(data))
    if n < 2:
        raise ValueError("not enough estimation observations")
    y = data[ticker].to_numpy(dtype=float)
    x = data[benchmark].to_numpy(dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    alpha, beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - (alpha + beta * x)
    # ddof=2 because intercept and beta are fitted. Clamp to avoid division by zero.
    resid_std = float(np.std(resid, ddof=2)) if n > 2 else float(np.std(resid))
    resid_std = max(resid_std, 1e-9)
    return float(alpha), float(beta), resid_std, n


def sum_log_returns(returns: pd.Series) -> float:
    return float(returns.dropna().sum())


def log_to_simple(log_return: float) -> float:
    return float(exp(log_return) - 1.0)


def signed_direction(value: float, flat_threshold: float) -> str:
    if pd.isna(value):
        return "unknown"
    if value > flat_threshold:
        return "up"
    if value < -flat_threshold:
        return "down"
    return "flat"


def _base_output_row(event: pd.Series, status: str, reason: str = "") -> dict:
    row = event.to_dict()
    row["event_status"] = status
    row["skip_reason"] = reason
    row["reaction_start"] = ""
    return row


def compute_event_study_frame(
    events: pd.DataFrame,
    returns: pd.DataFrame,
    config: EventStudyConfig,
) -> tuple[pd.DataFrame, EventStudyDiagnostics]:
    """Compute abnormal returns around all events."""
    benchmark = config.benchmark_ticker.upper()
    returns = returns.copy()
    returns.columns = [str(c).upper() for c in returns.columns]
    if benchmark not in returns.columns:
        raise ValueError(f"Benchmark ticker {benchmark} not found in returns data")

    returns = returns.sort_index()
    diag = EventStudyDiagnostics(events_total=len(events))
    rows: list[dict] = []

    for _, event in events.iterrows():
        ticker = str(event["ticker"]).upper()
        if ticker not in returns.columns:
            reason = f"missing ticker returns: {ticker}"
            diag.add_skip(reason)
            rows.append(_base_output_row(event, "skipped", reason))
            continue

        start = reaction_start_date(returns.index, event["event_time"], event["release_session"])
        if start is None or start not in returns.index:
            reason = "no trading day after event_time"
            diag.add_skip(reason)
            rows.append(_base_output_row(event, "skipped", reason))
            continue

        event_idx = int(returns.index.get_loc(start))
        est_end = event_idx - config.estimation_gap
        est_start = est_end - config.estimation_window
        if est_end <= 0 or est_start < 0:
            reason = "not enough pre-event history"
            diag.add_skip(reason)
            rows.append(_base_output_row(event, "skipped", reason))
            continue

        estimation = returns.iloc[est_start:est_end]
        estimation_n_available = int(estimation[[ticker, benchmark]].dropna().shape[0])
        if estimation_n_available < config.min_estimation_observations:
            reason = f"not enough clean estimation observations: {estimation_n_available}"
            diag.add_skip(reason)
            rows.append(_base_output_row(event, "skipped", reason))
            continue

        try:
            alpha, beta, residual_vol, estimation_n = fit_market_model(estimation, ticker, benchmark)
        except Exception as exc:
            reason = f"market model failed: {exc}"
            diag.add_skip(reason)
            rows.append(_base_output_row(event, "skipped", reason))
            continue

        row = event.to_dict()
        row.update(
            {
                "event_status": "ok",
                "skip_reason": "",
                "reaction_start": start.date().isoformat(),
                "benchmark_ticker": benchmark,
                "alpha": alpha,
                "beta": beta,
                "residual_vol": residual_vol,
                "estimation_n": estimation_n,
            }
        )

        pre = returns.iloc[:event_idx]
        row["pre_return_5d"] = sum_log_returns(pre[ticker].tail(5)) if len(pre) else np.nan
        row["pre_return_20d"] = sum_log_returns(pre[ticker].tail(20)) if len(pre) else np.nan
        row["pre_vol_20d"] = float(pre[ticker].tail(20).std(ddof=1)) if len(pre) >= 2 else np.nan
        row["benchmark_pre_return_20d"] = sum_log_returns(pre[benchmark].tail(20)) if len(pre) else np.nan
        row["benchmark_pre_vol_20d"] = float(pre[benchmark].tail(20).std(ddof=1)) if len(pre) >= 2 else np.nan

        sector = str(event.get("sector_benchmark", "") or "").upper().strip()
        if sector == "UNKNOWN":
            sector = ""
        has_sector = bool(sector) and sector in returns.columns and config.include_sector_adjustment

        for h in config.horizons:
            window = returns.iloc[event_idx : event_idx + h]
            if len(window) < h or window[[ticker, benchmark]].dropna().shape[0] < h:
                row[f"raw_return_h{h}"] = np.nan
                row[f"benchmark_return_h{h}"] = np.nan
                row[f"expected_return_h{h}"] = np.nan
                row[f"car_market_model_h{h}"] = np.nan
                row[f"car_index_adj_h{h}"] = np.nan
                row[f"car_sector_adj_h{h}"] = np.nan
                row[f"z_h{h}"] = np.nan
                row[f"p_value_h{h}"] = np.nan
                row[f"significant_95_h{h}"] = False
                row[f"target_direction_h{h}"] = "unknown"
                row[f"target_positive_h{h}"] = np.nan
                continue

            y = window[ticker]
            x = window[benchmark]
            expected_daily = alpha + beta * x
            raw_log = sum_log_returns(y)
            benchmark_log = sum_log_returns(x)
            expected_log = float(expected_daily.sum())
            car = float((y - expected_daily).sum())
            car_index_adj = float((y - x).sum())
            z = float(car / (residual_vol * sqrt(h)))
            p_value = float(2.0 * (1.0 - normal_cdf(abs(z))))

            row[f"raw_return_h{h}"] = log_to_simple(raw_log)
            row[f"benchmark_return_h{h}"] = log_to_simple(benchmark_log)
            row[f"expected_return_h{h}"] = log_to_simple(expected_log)
            row[f"car_market_model_h{h}"] = car
            row[f"car_market_model_simple_h{h}"] = log_to_simple(car)
            row[f"car_index_adj_h{h}"] = car_index_adj
            row[f"car_index_adj_simple_h{h}"] = log_to_simple(car_index_adj)
            if has_sector and window[[ticker, sector]].dropna().shape[0] == h:
                sector_log = sum_log_returns(window[sector])
                row[f"sector_return_h{h}"] = log_to_simple(sector_log)
                row[f"car_sector_adj_h{h}"] = float((window[ticker] - window[sector]).sum())
                row[f"car_sector_adj_simple_h{h}"] = log_to_simple(row[f"car_sector_adj_h{h}"])
            else:
                row[f"sector_return_h{h}"] = np.nan
                row[f"car_sector_adj_h{h}"] = np.nan
                row[f"car_sector_adj_simple_h{h}"] = np.nan
            row[f"z_h{h}"] = z
            row[f"p_value_h{h}"] = p_value
            row[f"significant_95_h{h}"] = bool(abs(z) >= 1.96)
            row[f"target_direction_h{h}"] = signed_direction(car, config.flat_threshold)
            row[f"target_positive_h{h}"] = bool(car > 0)

        rows.append(row)
        diag.events_ok += 1

    out = pd.DataFrame(rows)
    return out, diag


def run_event_study(
    events_path: str | Path,
    prices_dir: str | Path,
    benchmark_ticker: str = "SPY",
    horizons: Iterable[int] = (1, 3, 10),
    estimation_window: int = 120,
    estimation_gap: int = 5,
    min_estimation_observations: int = 60,
) -> tuple[pd.DataFrame, EventStudyDiagnostics]:
    events = load_events(events_path)
    config = EventStudyConfig(
        benchmark_ticker=benchmark_ticker.upper(),
        horizons=tuple(int(h) for h in horizons),
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    tickers = event_tickers(events, benchmark=config.benchmark_ticker)
    returns = load_log_returns(prices_dir, tickers)
    return compute_event_study_frame(events, returns, config)
