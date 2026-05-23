from __future__ import annotations

import csv
import math
import statistics
from datetime import date
from pathlib import Path

from .prices import resolve_price_csv
from .sec_common import clean_text, market_close, market_open, parse_date, parse_datetime_et, read_csv_rows, to_float, write_csv_rows

CONTEXT_FIELDS = [
    "last_close_before_event",
    "market_cap_before_event",
    "shares_outstanding_before_event",
    "pre_event_market_adjusted_return_20d",
    "pre_event_market_adjusted_return_60d",
    "pre_event_volatility_20d",
    "dollar_volume_20d",
    "company_size_bucket",
]


def _load_prices(prices_dir: str | Path, ticker: str) -> list[dict[str, float | date]]:
    path = resolve_price_csv(prices_dir, ticker)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        lower = {str(col).lower(): col for col in reader.fieldnames or []}
        date_col = lower.get("date")
        close_col = lower.get("adj_close") or lower.get("adjusted_close") or lower.get("close")
        volume_col = lower.get("volume")
        if not date_col or not close_col:
            raise ValueError(f"Price CSV must contain date and close/adj_close columns: {path}")
        rows = []
        for row in reader:
            day = parse_date(row.get(date_col))
            close = to_float(row.get(close_col))
            if day is None or close is None:
                continue
            volume = to_float(row.get(volume_col)) if volume_col else None
            rows.append({"date": day, "close": close, "volume": volume if volume is not None else math.nan})
    return sorted(rows, key=lambda item: item["date"])  # type: ignore[index]


def _anchor_index(prices: list[dict[str, float | date]], event_value: object, release_session: object = "") -> int | None:
    event_dt, date_only = parse_datetime_et(event_value)
    if event_dt is None:
        return None
    session = clean_text(release_session).lower()
    include_same_day = False
    if session == "after_close" or (not date_only and event_dt >= market_close(event_dt.date())):
        include_same_day = True
    elif session in {"before_open", "intraday"}:
        include_same_day = False
    elif not date_only and event_dt < market_open(event_dt.date()):
        include_same_day = False
    elif not date_only and event_dt >= market_close(event_dt.date()):
        include_same_day = True
    target_day = event_dt.date()
    candidates = []
    for idx, row in enumerate(prices):
        row_day = row["date"]
        if include_same_day:
            keep = row_day <= target_day
        else:
            keep = row_day < target_day
        if keep:
            candidates.append(idx)
    return candidates[-1] if candidates else None


def _window_return(prices: list[dict[str, float | date]], anchor_idx: int | None, window: int) -> float | None:
    if anchor_idx is None or anchor_idx - window < 0:
        return None
    start = float(prices[anchor_idx - window]["close"])
    end = float(prices[anchor_idx]["close"])
    if start == 0:
        return None
    return end / start - 1.0


def _volatility(prices: list[dict[str, float | date]], anchor_idx: int | None, window: int) -> float | None:
    if anchor_idx is None or anchor_idx - window < 0:
        return None
    returns = []
    for idx in range(anchor_idx - window + 1, anchor_idx + 1):
        prev = float(prices[idx - 1]["close"])
        cur = float(prices[idx]["close"])
        if prev:
            returns.append(cur / prev - 1.0)
    if len(returns) < 2:
        return None
    return statistics.stdev(returns)


def _dollar_volume(prices: list[dict[str, float | date]], anchor_idx: int | None, window: int) -> float | None:
    if anchor_idx is None or anchor_idx - window + 1 < 0:
        return None
    values = []
    for row in prices[anchor_idx - window + 1 : anchor_idx + 1]:
        volume = float(row.get("volume", math.nan))
        close = float(row["close"])
        if not math.isnan(volume):
            values.append(close * volume)
    return sum(values) / len(values) if values else None


def _load_point_in_time(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    rows, _ = read_csv_rows(p)
    return rows


def _lookup_pit(rows: list[dict[str, str]], ticker: str, event_day: date, value_names: list[str]) -> tuple[float | None, str]:
    if not rows:
        return None, "missing"
    candidates = []
    unverified = []
    for row in rows:
        if clean_text(row.get("ticker")).upper() != ticker.upper():
            continue
        value = None
        for name in value_names:
            value = to_float(row.get(name))
            if value is not None:
                break
        if value is None:
            continue
        asof = parse_date(row.get("asof_date"))
        if asof is None:
            unverified.append((event_day, value))
        elif asof <= event_day:
            candidates.append((asof, value))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1], "point_in_time"
    if unverified:
        return unverified[0][1], "unverified_no_asof_date"
    return None, "missing"


def size_bucket(market_cap: float | None) -> str:
    if market_cap is None:
        return "unknown"
    if market_cap < 300_000_000:
        return "micro"
    if market_cap < 2_000_000_000:
        return "small"
    if market_cap < 10_000_000_000:
        return "mid"
    if market_cap < 200_000_000_000:
        return "large"
    return "mega"


def add_sec_context(
    input_path: str | Path,
    out_path: str | Path,
    *,
    prices_dir: str | Path,
    benchmark_ticker: str = "SPY",
    shares_outstanding_path: str | Path | None = None,
    market_cap_path: str | Path | None = None,
) -> list[dict[str, object]]:
    rows, columns = read_csv_rows(input_path)
    shares_rows = _load_point_in_time(shares_outstanding_path)
    market_cap_rows = _load_point_in_time(market_cap_path)
    price_cache: dict[str, list[dict[str, float | date]]] = {}
    benchmark_prices: list[dict[str, float | date]] = []
    try:
        benchmark_prices = _load_prices(prices_dir, benchmark_ticker)
    except FileNotFoundError:
        benchmark_prices = []

    output: list[dict[str, object]] = []
    for row in rows:
        out = dict(row)
        ticker = clean_text(row.get("ticker")).upper()
        notes: list[str] = []
        event_dt, _ = parse_datetime_et(row.get("event_time") or row.get("filing_acceptance_time"))
        event_day = event_dt.date() if event_dt else None
        stock_prices: list[dict[str, float | date]] = []
        try:
            stock_prices = price_cache.setdefault(ticker, _load_prices(prices_dir, ticker)) if ticker else []
        except FileNotFoundError:
            notes.append("missing_price_history")

        anchor = _anchor_index(stock_prices, row.get("event_time") or row.get("filing_acceptance_time"), row.get("release_session")) if stock_prices else None
        bench_anchor = _anchor_index(benchmark_prices, row.get("event_time") or row.get("filing_acceptance_time"), row.get("release_session")) if benchmark_prices else None
        last_close = float(stock_prices[anchor]["close"]) if anchor is not None else None
        out["last_close_before_event"] = last_close if last_close is not None else ""

        shares, shares_status = (None, "missing")
        market_cap, market_cap_status = (None, "missing")
        if event_day is not None:
            shares, shares_status = _lookup_pit(shares_rows, ticker, event_day, ["shares_outstanding_before_event", "shares_outstanding"])
            market_cap, market_cap_status = _lookup_pit(market_cap_rows, ticker, event_day, ["market_cap_before_event", "market_cap"])
        if market_cap is None and shares is not None and last_close is not None:
            market_cap = shares * last_close
            market_cap_status = shares_status
        out["shares_outstanding_before_event"] = shares if shares is not None else ""
        out["market_cap_before_event"] = market_cap if market_cap is not None else ""

        for window in (20, 60):
            stock_ret = _window_return(stock_prices, anchor, window)
            bench_ret = _window_return(benchmark_prices, bench_anchor, window)
            adjusted = stock_ret - bench_ret if stock_ret is not None and bench_ret is not None else None
            out[f"pre_event_market_adjusted_return_{window}d"] = adjusted if adjusted is not None else ""
        vol = _volatility(stock_prices, anchor, 20)
        dollar_volume = _dollar_volume(stock_prices, anchor, 20)
        out["pre_event_volatility_20d"] = vol if vol is not None else ""
        out["dollar_volume_20d"] = dollar_volume if dollar_volume is not None else ""
        out["company_size_bucket"] = size_bucket(market_cap)

        statuses = [f"shares:{shares_status}", f"market_cap:{market_cap_status}"]
        if not benchmark_prices:
            statuses.append("missing_benchmark_prices")
        if any(status.endswith("unverified_no_asof_date") for status in statuses):
            notes.append("current_or_non_pit_capitalization_used")
            out["model_eligible"] = "false"
        elif "model_eligible" not in out or clean_text(out.get("model_eligible")) == "":
            out["model_eligible"] = "true"
        out["context_status"] = ";".join(statuses)
        out["context_notes"] = "; ".join(notes)
        output.append(out)

    out_columns = list(columns)
    for col in CONTEXT_FIELDS + ["context_status", "context_notes", "model_eligible"]:
        if col not in out_columns:
            out_columns.append(col)
    write_csv_rows(out_path, output, out_columns)
    return output
