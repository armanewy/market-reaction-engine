from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .paths import ensure_dir

PRICE_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a price DataFrame to date/open/high/low/close/adj_close/volume."""
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()
    rename = {c: c.strip().lower().replace(" ", "_") for c in out.columns}
    out = out.rename(columns=rename)
    if "datetime" in out.columns and "date" not in out.columns:
        out = out.rename(columns={"datetime": "date"})
    if "adj_close" not in out.columns:
        if "adjclose" in out.columns:
            out = out.rename(columns={"adjclose": "adj_close"})
        elif "close" in out.columns:
            # Fallback for adjusted feeds. The README warns this is acceptable for
            # prototyping but not a production-quality total-return source.
            out["adj_close"] = out["close"]
    missing = [c for c in ["date", "adj_close"] if c not in out.columns]
    if missing:
        raise ValueError(f"Price data missing required columns: {missing}")

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in out.columns:
            out[col] = np.nan

    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    out = out[PRICE_COLUMNS]
    out = out.dropna(subset=["date", "adj_close"]).drop_duplicates("date")
    out = out.sort_values("date").reset_index(drop=True)
    return out


def price_path(prices_dir: str | Path, ticker: str) -> Path:
    return Path(prices_dir) / f"{ticker.upper()}.csv"


def price_file_candidates(prices_dir: str | Path, ticker: str) -> list[Path]:
    base = Path(prices_dir)
    raw = str(ticker).strip()
    upper = raw.upper()
    lower = raw.lower()
    return [
        base / f"{raw}.csv",
        base / f"{upper}.csv",
        base / f"{lower}.csv",
        base / upper / "prices.csv",
        base / lower / "prices.csv",
    ]


def resolve_price_csv(prices_dir: str | Path, ticker: str) -> Path:
    for path in price_file_candidates(prices_dir, ticker):
        if path.exists():
            return path
    raise FileNotFoundError(f"No price CSV found for {ticker!r} under {prices_dir}")


def load_price_csv(prices_dir: str | Path, ticker: str) -> pd.DataFrame:
    path = resolve_price_csv(prices_dir, ticker)
    return normalize_price_frame(pd.read_csv(path))


def load_adjusted_closes(prices_dir: str | Path, tickers: Iterable[str]) -> pd.DataFrame:
    series = []
    for ticker in sorted({t.upper() for t in tickers}):
        df = load_price_csv(prices_dir, ticker)
        s = df.set_index("date")["adj_close"].rename(ticker)
        series.append(s)
    if not series:
        raise ValueError("No tickers supplied")
    prices = pd.concat(series, axis=1).sort_index()
    prices.index = pd.to_datetime(prices.index).tz_localize(None).normalize()
    return prices


def load_log_returns(prices_dir: str | Path, tickers: Iterable[str]) -> pd.DataFrame:
    prices = load_adjusted_closes(prices_dir, tickers)
    returns = np.log(prices / prices.shift(1))
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return returns


def fetch_yfinance_prices(
    tickers: Iterable[str],
    start: str,
    end: str,
    out_dir: str | Path,
    sleep_seconds: float = 0.2,
) -> list[Path]:
    """Fetch daily price data with yfinance and write one CSV per ticker.

    yfinance is useful for prototyping. For serious backtests, replace this with
    a paid point-in-time source such as CRSP, Polygon, Tiingo, Nasdaq Data Link,
    or your broker's historical data feed.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install yfinance to use fetch-prices") from exc

    out = ensure_dir(out_dir)
    paths: list[Path] = []
    for ticker in sorted({t.upper() for t in tickers}):
        data = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=False,
            progress=False,
            actions=False,
            threads=False,
        )
        if data.empty:
            raise RuntimeError(f"No yfinance data returned for {ticker}")
        data = data.reset_index()
        # yfinance can return a MultiIndex depending on version/options.
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] if c[0] else c[1] for c in data.columns]
        data = data.rename(
            columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )
        normalized = normalize_price_frame(data)
        p = price_path(out, ticker)
        normalized.to_csv(p, index=False)
        paths.append(p)
        time.sleep(sleep_seconds)
    return paths
