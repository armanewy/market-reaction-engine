from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import make_event_template
from .sec import SecClient, _release_session_from_acceptance

EARNINGS_8K_ITEM = "2.02"
GUIDANCE_ITEM_CANDIDATES = {"7.01", "8.01"}
PERIODIC_FORMS = {"10-Q", "10-K"}

# Columns that are useful to keep as numeric model features when earnings rows
# are later joined to event-study results.
NUMERIC_EARNINGS_COLUMNS = [
    "reported_eps",
    "estimated_eps",
    "eps_estimate",
    "actual_eps",
    "consensus_eps",
    "eps_surprise",
    "eps_surprise_pct",
    "eps_abs_surprise_pct",
    "earnings_surprise_abs_max_pct",
    "eps_signal_strength",
    "eps_surprise_sign",
    "eps_has_estimate",
]


@dataclass
class CorpusDiagnostics:
    tickers_requested: int = 0
    tickers_with_events: int = 0
    rows_written: int = 0
    skipped: dict[str, int] | None = None
    warnings: list[str] | None = None

    def __post_init__(self) -> None:
        if self.skipped is None:
            self.skipped = {}
        if self.warnings is None:
            self.warnings = []

    def add_skip(self, reason: str) -> None:
        assert self.skipped is not None
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(value: object) -> str:
    return str(value or "").strip()


def _normalize_timestamp(ts: object) -> pd.Timestamp:
    out = pd.to_datetime(ts, errors="coerce")
    if pd.isna(out):
        out = pd.Timestamp.utcnow()
    out = pd.Timestamp(out)
    if out.tzinfo is not None:
        out = out.tz_convert(None) if getattr(out, "tz", None) is not None else out.tz_localize(None)
    return out


def normalize_sec_items(items: object) -> set[str]:
    """Normalize SEC item strings such as 'Item 2.02; 9.01'."""
    text = re.sub(r"(?i)\bitem\b", "", str(items or ""))
    out: set[str] = set()
    for part in re.split(r"[,;\s]+", text):
        p = part.strip().strip(".")
        if re.fullmatch(r"\d+(?:\.\d+)?", p):
            out.add(p)
    return out


def _contains_item(items: object, item: str) -> bool:
    parts = normalize_sec_items(items)
    return item in parts or any(p.startswith(item) for p in parts)


def classify_earnings_filing(
    row: pd.Series,
    include_periodic: bool = False,
    include_guidance_candidates: bool = True,
    include_guidance_related: bool | None = None,
) -> tuple[bool, str, str, str]:
    """Classify SEC filings as earnings/guidance candidates.

    8-K Item 2.02 is the cleanest SEC signal for an earnings release. Optional
    8-K Item 7.01/8.01 guidance candidates are much noisier and should be
    manually reviewed before modeling.
    """
    if include_guidance_related is not None:
        include_guidance_candidates = include_guidance_related

    form = _norm(row.get("form")).upper()
    items = _norm(row.get("items"))
    desc = _norm(row.get("primaryDocDescription")).lower()
    primary_doc = _norm(row.get("primaryDocument")).lower()

    if form in {"8-K", "8-K/A"} and _contains_item(items, EARNINGS_8K_ITEM):
        return True, "earnings", "8k_item_2_02_results", "High-confidence earnings-release candidate from 8-K Item 2.02."

    guidance_words = ["guidance", "outlook", "preliminary results", "business update", "financial update"]
    has_guidance_word = any(w in desc or w in primary_doc for w in guidance_words)
    has_guidance_item = any(_contains_item(items, item) for item in GUIDANCE_ITEM_CANDIDATES)
    if form in {"8-K", "8-K/A"} and include_guidance_candidates and has_guidance_item and has_guidance_word:
        return True, "guidance", "8k_guidance_candidate", "Noisy Item 7.01/8.01 guidance/outlook candidate; manually review."

    if include_periodic and form in PERIODIC_FORMS:
        subtype = "sec_10q_periodic" if form == "10-Q" else "sec_10k_annual"
        return True, "earnings", subtype, "Periodic report candidate. Usually less clean than the earnings release; manually review timing."

    return False, "", "", "Not an earnings/guidance candidate under current filters."


def is_earnings_8k_row(row: pd.Series) -> bool:
    form = _norm(row.get("form")).upper()
    return form in {"8-K", "8-K/A"} and _contains_item(row.get("items", ""), EARNINGS_8K_ITEM)


def filter_earnings_filings(filings: pd.DataFrame) -> pd.DataFrame:
    if filings.empty:
        return filings.copy()
    return filings[filings.apply(is_earnings_8k_row, axis=1)].copy().reset_index(drop=True)


def _source_url(row: pd.Series) -> str:
    try:
        cik = int(row["cik"])
    except Exception:
        return ""
    accession = _norm(row.get("accessionNumber"))
    primary_doc = _norm(row.get("primaryDocument"))
    if not accession or not primary_doc:
        return ""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary_doc}"


def _event_time_from_filing(row: pd.Series) -> pd.Timestamp:
    accepted = row.get("acceptanceDateTime", row.get("filingDate", ""))
    ts = pd.to_datetime(accepted, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(row.get("filingDate"), errors="coerce")
    return _normalize_timestamp(ts)


def filing_to_earnings_event_row(
    row: pd.Series,
    sector_benchmark: str = "",
    include_periodic: bool = False,
    include_guidance_candidates: bool = True,
    include_guidance_related: bool | None = None,
) -> dict | None:
    ok, event_type, subtype, note = classify_earnings_filing(
        row,
        include_periodic=include_periodic,
        include_guidance_candidates=include_guidance_candidates,
        include_guidance_related=include_guidance_related,
    )
    if not ok:
        return None

    ticker = _norm(row.get("ticker")).upper()
    company = _norm(row.get("company_name")) or ticker
    form = _norm(row.get("form")).upper()
    accepted = _norm(row.get("acceptanceDateTime")) or _norm(row.get("filingDate"))
    filing_date = _norm(row.get("filingDate"))
    accession = _norm(row.get("accessionNumber"))
    event_time = _event_time_from_filing(row)
    items = ",".join(sorted(normalize_sec_items(row.get("items", ""))))

    return {
        "event_id": f"{ticker}_{event_type}_{filing_date}_{accession}",
        "ticker": ticker,
        "event_time": event_time.isoformat(),
        "event_type": event_type,
        "summary": f"{company} {event_type} candidate from SEC {form} filing ({subtype}). Curate surprise/materiality before modeling.",
        "event_subtype": subtype,
        "source_type": "sec_filing",
        "source_url": _source_url(row),
        "release_session": _release_session_from_acceptance(accepted),
        "expectedness": "unknown",
        "surprise_direction": "unknown",
        "surprise_magnitude": "unknown",
        "materiality": 0.7 if event_type == "earnings" else 0.5,
        "sector_benchmark": sector_benchmark.upper().strip(),
        "notes": note,
        "event_family": "earnings_guidance",
        "sec_form": form,
        "sec_items": items,
        "accession_number": accession,
        "filing_date": filing_date,
        "fiscal_period_end": _norm(row.get("reportDate")),
        "primary_document": _norm(row.get("primaryDocument")),
        "primary_doc_description": _norm(row.get("primaryDocDescription")),
        "company_name": company,
        "requires_manual_review": True,
        "expectation_source": "sec_candidate_no_consensus",
        "expectation_quality": "primary_source_event_no_surprise_data",
        "expectation_confidence": 0.25,
    }


def filings_to_earnings_events(filings: pd.DataFrame, sector_benchmark: str = "") -> pd.DataFrame:
    rows: list[dict] = []
    for _, filing in filter_earnings_filings(filings).iterrows():
        row = filing_to_earnings_event_row(
            filing,
            sector_benchmark=sector_benchmark,
            include_periodic=False,
            include_guidance_candidates=False,
        )
        if row is not None:
            rows.append(row)
    return pd.DataFrame(rows)


earnings_filings_to_events = filings_to_earnings_events


def build_earnings_corpus_from_sec(
    client: SecClient,
    tickers: Iterable[str],
    out_path: str | Path,
    start: str | None = None,
    end: str | None = None,
    sector_benchmark: str = "",
    ticker_to_sector_benchmark: dict[str, str] | None = None,
    limit_per_ticker: int | None = None,
    include_periodic: bool = False,
    include_guidance_candidates: bool = True,
) -> pd.DataFrame:
    """Build primary-source SEC earnings/guidance candidate events.

    These rows deliberately remain conservative: they identify public filing
    events, but they do not infer analyst surprise, revenue surprise, or market
    materiality from later price movement.
    """
    rows: list[dict] = []
    forms = ["8-K", "8-K/A"] + (["10-Q", "10-K"] if include_periodic else [])
    start_ts = pd.to_datetime(start, errors="coerce") if start else None
    end_ts = pd.to_datetime(end, errors="coerce") if end else None
    sector_map = {k.upper(): v.upper() for k, v in (ticker_to_sector_benchmark or {}).items()}

    for ticker in sorted({str(t).upper().strip() for t in tickers if str(t).strip()}):
        filings = client.recent_filings(ticker, forms=forms)
        if filings.empty:
            continue
        filings = filings.copy()
        filings["_event_time"] = pd.to_datetime(filings.get("acceptanceDateTime", filings.get("filingDate")), errors="coerce")
        if start_ts is not None and not pd.isna(start_ts):
            filings = filings[filings["_event_time"] >= start_ts]
        if end_ts is not None and not pd.isna(end_ts):
            filings = filings[filings["_event_time"] <= end_ts]
        filings = filings.sort_values("_event_time", ascending=True)
        if limit_per_ticker:
            filings = filings.tail(int(limit_per_ticker))
        sec_bench = sector_map.get(ticker, sector_benchmark)
        for _, filing in filings.iterrows():
            event_row = filing_to_earnings_event_row(
                filing,
                sector_benchmark=sec_bench,
                include_periodic=include_periodic,
                include_guidance_candidates=include_guidance_candidates,
            )
            if event_row is not None:
                rows.append(event_row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates("event_id").sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    make_event_template(out_path, out.to_dict(orient="records"))
    return out


def build_sec_earnings_corpus(
    tickers: Iterable[str],
    out_path: str | Path,
    *,
    client: SecClient | None = None,
    sector_benchmark: str = "",
    start: str | None = None,
    end: str | None = None,
    limit_per_ticker: int | None = 80,
    include_guidance_related: bool = False,
    user_agent: str | None = None,
    requests_per_second: float = 5.0,
) -> tuple[pd.DataFrame, CorpusDiagnostics]:
    ticker_list = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
    diag = CorpusDiagnostics(tickers_requested=len(ticker_list))
    client = client or SecClient(user_agent=user_agent, requests_per_second=requests_per_second)
    out = build_earnings_corpus_from_sec(
        client=client,
        tickers=ticker_list,
        out_path=out_path,
        start=start,
        end=end,
        sector_benchmark=sector_benchmark,
        limit_per_ticker=limit_per_ticker,
        include_periodic=False,
        include_guidance_candidates=include_guidance_related,
    )
    diag.rows_written = len(out)
    tickers_with = set(out["ticker"].dropna().astype(str).str.upper()) if not out.empty else set()
    diag.tickers_with_events = len(tickers_with)
    for ticker in ticker_list:
        if ticker not in tickers_with:
            diag.add_skip(f"{ticker}: no SEC earnings candidates after filters")
    if not include_guidance_related:
        assert diag.warnings is not None
        diag.warnings.append("Guidance-related Item 7.01/8.01 candidates were excluded; rerun with --include-guidance-candidates to inspect them.")
    return out, diag


def _float_or_nan(value: object) -> float:
    if value is None:
        return float("nan")
    s = str(value).strip()
    if not s or s.lower() in {"none", "null", "nan", "na", "n/a", "--"}:
        return float("nan")
    try:
        return float(s.replace(",", "").replace("%", ""))
    except ValueError:
        return float("nan")


def _release_session_from_timestamp(ts: pd.Timestamp) -> str:
    ts = _normalize_timestamp(ts)
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return "unknown"
    if ts.hour < 9 or (ts.hour == 9 and ts.minute < 30):
        return "before_open"
    if ts.hour >= 16:
        return "after_close"
    return "intraday"


def _surprise_labels(eps_surprise_pct: float) -> tuple[str, str, str]:
    if pd.isna(eps_surprise_pct):
        return "unknown", "unknown", "unknown"
    direction = "positive" if eps_surprise_pct > 0 else ("negative" if eps_surprise_pct < 0 else "neutral")
    abs_pct = abs(float(eps_surprise_pct))
    mag = "high" if abs_pct >= 0.20 else ("medium" if abs_pct >= 0.08 else ("low" if abs_pct >= 0.02 else "neutral"))
    expectedness = "surprise" if abs_pct >= 0.08 else ("partial_surprise" if abs_pct >= 0.02 else "expected")
    return expectedness, direction, mag


def _event_time_from_reported_date(reported_date: pd.Timestamp, release_session: str) -> pd.Timestamp:
    d = pd.Timestamp(reported_date).normalize()
    if release_session == "after_close":
        return d + pd.Timedelta(hours=16, minutes=5)
    if release_session == "before_open":
        return d + pd.Timedelta(hours=8, minutes=5)
    return d


def _earnings_row_from_eps(
    *,
    ticker: str,
    event_time: pd.Timestamp,
    reported_date: str,
    fiscal_period_end: str,
    source_type: str,
    source_url: str,
    event_subtype: str,
    release_session: str,
    sector_benchmark: str,
    actual_eps: float,
    consensus_eps: float,
    eps_surprise: float,
    eps_surprise_pct: float,
    notes: str,
) -> dict:
    if pd.notna(eps_surprise_pct) and abs(float(eps_surprise_pct)) > 1:
        eps_surprise_pct = float(eps_surprise_pct) / 100.0
    if pd.isna(eps_surprise) and pd.notna(actual_eps) and pd.notna(consensus_eps):
        eps_surprise = actual_eps - consensus_eps
    if pd.isna(eps_surprise_pct) and pd.notna(eps_surprise) and pd.notna(consensus_eps) and consensus_eps != 0:
        eps_surprise_pct = eps_surprise / abs(consensus_eps)
    expectedness, direction, magnitude = _surprise_labels(eps_surprise_pct)
    abs_pct = abs(eps_surprise_pct) if pd.notna(eps_surprise_pct) else float("nan")
    return {
        "event_id": f"{ticker}_{event_subtype}_{reported_date}_{fiscal_period_end}",
        "ticker": ticker,
        "event_time": event_time.isoformat(),
        "event_type": "earnings",
        "summary": f"{ticker} quarterly EPS actual={actual_eps}, estimate={consensus_eps}, surprise_pct={eps_surprise_pct}.",
        "event_subtype": event_subtype,
        "source_type": source_type,
        "source_url": source_url,
        "release_session": release_session,
        "expectedness": expectedness,
        "surprise_direction": direction,
        "surprise_magnitude": magnitude,
        "materiality": 0.7,
        "sector_benchmark": sector_benchmark.upper().strip(),
        "notes": notes,
        "event_family": "earnings_guidance",
        "fiscal_period_end": fiscal_period_end,
        "reported_date": reported_date,
        "actual_eps": actual_eps,
        "consensus_eps": consensus_eps,
        "reported_eps": actual_eps,
        "estimated_eps": consensus_eps,
        "eps_estimate": consensus_eps,
        "eps_surprise": eps_surprise,
        "eps_surprise_pct": eps_surprise_pct,
        "eps_abs_surprise_pct": abs_pct,
        "earnings_surprise_abs_max_pct": abs_pct,
        "eps_signal_strength": float(min(abs_pct / 0.20, 3.0)) if pd.notna(abs_pct) else np.nan,
        "eps_surprise_sign": 1 if direction == "positive" else (-1 if direction == "negative" else 0),
        "eps_has_estimate": bool(pd.notna(consensus_eps)),
        "expectation_source_type": source_type,
        "expectation_quality": "bootstrap_not_point_in_time_verified",
    }


def build_yfinance_earnings_corpus(
    tickers: Iterable[str],
    out_path: str | Path,
    *,
    sector_benchmark: str = "",
    start: str | None = None,
    end: str | None = None,
    limit_per_ticker: int = 40,
    sleep_seconds: float = 0.2,
) -> tuple[pd.DataFrame, CorpusDiagnostics]:
    """Build a prototype EPS-surprise corpus from yfinance earnings dates.

    yfinance is useful for a free/research bootstrap, but the rows should be
    treated as non-institutional until release timing and estimates are curated.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install yfinance to use build_yfinance_earnings_corpus") from exc

    ticker_list = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
    diag = CorpusDiagnostics(tickers_requested=len(ticker_list))
    start_ts = pd.to_datetime(start, errors="coerce") if start else None
    end_ts = pd.to_datetime(end, errors="coerce") if end else None
    rows: list[dict] = []

    for ticker in ticker_list:
        try:
            dates = yf.Ticker(ticker).get_earnings_dates(limit=limit_per_ticker)
        except Exception as exc:  # pragma: no cover - provider behavior
            diag.add_skip(f"{ticker}: yfinance fetch failed: {exc}")
            continue
        if dates is None or len(dates) == 0:
            diag.add_skip(f"{ticker}: no yfinance earnings dates")
            continue
        df = dates.copy().reset_index()
        norm_cols = {str(c).strip().lower().replace(" ", "_").replace("%", "pct").replace("(", "").replace(")", ""): c for c in df.columns}
        date_col = norm_cols.get("earnings_date") or norm_cols.get("index") or df.columns[0]
        eps_est_col = norm_cols.get("eps_estimate")
        eps_rep_col = norm_cols.get("reported_eps")
        surprise_col = norm_cols.get("surprisepct") or norm_cols.get("surprise_pct")
        df["_event_time"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["_event_time"]).sort_values("_event_time", ascending=True)
        if start_ts is not None and not pd.isna(start_ts):
            df = df[df["_event_time"] >= start_ts]
        if end_ts is not None and not pd.isna(end_ts):
            df = df[df["_event_time"] <= end_ts]
        before = len(rows)
        for i, r in df.iterrows():
            event_time = _normalize_timestamp(r["_event_time"])
            actual_eps = _float_or_nan(r.get(eps_rep_col)) if eps_rep_col else float("nan")
            consensus_eps = _float_or_nan(r.get(eps_est_col)) if eps_est_col else float("nan")
            eps_surprise_pct = _float_or_nan(r.get(surprise_col)) if surprise_col else float("nan")
            eps_surprise = actual_eps - consensus_eps if pd.notna(actual_eps) and pd.notna(consensus_eps) else float("nan")
            rows.append(
                _earnings_row_from_eps(
                    ticker=ticker,
                    event_time=event_time,
                    reported_date=event_time.date().isoformat(),
                    fiscal_period_end="unknown",
                    source_type="yfinance_earnings_dates",
                    source_url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
                    event_subtype="yfinance_eps_history",
                    release_session=_release_session_from_timestamp(event_time),
                    sector_benchmark=sector_benchmark,
                    actual_eps=actual_eps,
                    consensus_eps=consensus_eps,
                    eps_surprise=eps_surprise,
                    eps_surprise_pct=eps_surprise_pct,
                    notes="Bootstrap yfinance EPS-history row; validate exact release timing and point-in-time expectations before serious use.",
                )
            )
        if len(rows) > before:
            diag.tickers_with_events += 1
        else:
            diag.add_skip(f"{ticker}: no yfinance earnings rows after date filters")
        time.sleep(max(0.0, float(sleep_seconds)))

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates("event_id").sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    make_event_template(out_path, out.to_dict("records"))
    diag.rows_written = len(out)
    return out, diag



def fetch_alpha_vantage_earnings_history(ticker: str, api_key: str | None = None) -> pd.DataFrame:
    """Fetch Alpha Vantage quarterly earnings history for one ticker."""
    import requests

    key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        raise ValueError("Set ALPHAVANTAGE_API_KEY or ALPHA_VANTAGE_API_KEY, or pass api_key")
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "EARNINGS", "symbol": ticker.upper().strip(), "apikey": key},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Alpha Vantage request failed {resp.status_code} for {ticker}: {resp.text[:500]}")
    payload = resp.json()
    if "Information" in payload or "Note" in payload or "Error Message" in payload:
        msg = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
        raise RuntimeError(f"Alpha Vantage returned a non-data response for {ticker}: {msg}")
    return pd.DataFrame(payload.get("quarterlyEarnings", []) or [])


def alpha_vantage_earnings_to_event_rows(
    ticker: str,
    earnings: pd.DataFrame,
    *,
    sector_benchmark: str = "",
    start: str | None = None,
    end: str | None = None,
    limit_per_ticker: int | None = None,
    release_session: str = "unknown",
) -> pd.DataFrame:
    """Convert Alpha Vantage quarterly EPS history into MRE event rows."""
    ticker = ticker.upper().strip()
    if earnings.empty:
        return pd.DataFrame()
    start_ts = pd.to_datetime(start, errors="coerce") if start else None
    end_ts = pd.to_datetime(end, errors="coerce") if end else None
    rows: list[dict] = []
    df = earnings.copy()
    df["_reported_date"] = pd.to_datetime(df.get("reportedDate"), errors="coerce")
    df = df.dropna(subset=["_reported_date"]).sort_values("_reported_date", ascending=True)
    if start_ts is not None and not pd.isna(start_ts):
        df = df[df["_reported_date"] >= start_ts]
    if end_ts is not None and not pd.isna(end_ts):
        df = df[df["_reported_date"] <= end_ts]
    if limit_per_ticker:
        df = df.tail(int(limit_per_ticker))
    for _, raw in df.iterrows():
        reported_date = pd.Timestamp(raw["_reported_date"])
        fiscal_date = pd.to_datetime(raw.get("fiscalDateEnding"), errors="coerce")
        fiscal_label = pd.Timestamp(fiscal_date).date().isoformat() if pd.notna(fiscal_date) else "unknown"
        reported_label = reported_date.date().isoformat()
        event_time = _event_time_from_reported_date(reported_date, release_session)
        rows.append(
            _earnings_row_from_eps(
                ticker=ticker,
                event_time=event_time,
                reported_date=reported_label,
                fiscal_period_end=fiscal_label,
                source_type="alpha_vantage_earnings",
                source_url="https://www.alphavantage.co/documentation/#earnings",
                event_subtype="alpha_vantage_quarterly_eps",
                release_session=release_session,
                sector_benchmark=sector_benchmark,
                actual_eps=_float_or_nan(raw.get("reportedEPS")),
                consensus_eps=_float_or_nan(raw.get("estimatedEPS")),
                eps_surprise=_float_or_nan(raw.get("surprise")),
                eps_surprise_pct=_float_or_nan(raw.get("surprisePercentage")),
                notes="Bootstrap row from Alpha Vantage. Validate release timing and add revenue/guidance/options expectations before serious use.",
            )
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates("event_id").sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    return out

def build_alpha_vantage_earnings_corpus(
    tickers: Iterable[str],
    out_path: str | Path,
    api_key: str | None = None,
    sector_benchmark: str = "",
    start: str | None = None,
    end: str | None = None,
    limit_per_ticker: int | None = None,
    requests_per_minute: float = 5.0,
    release_session: str = "unknown",
) -> pd.DataFrame:
    """Build an EPS-surprise earnings corpus from Alpha Vantage EARNINGS.

    This is a bootstrap adapter. It gives reported EPS, estimated EPS,
    surprise, and surprise percentage, but not a high-confidence historical
    release timestamp. For serious event studies, manually curate release
    session/event_time or replace this with a paid point-in-time estimates feed.
    """
    import requests

    key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        raise ValueError("Set ALPHAVANTAGE_API_KEY or pass --api-key")

    start_ts = pd.to_datetime(start, errors="coerce") if start else None
    end_ts = pd.to_datetime(end, errors="coerce") if end else None
    rows: list[dict] = []

    for ticker in sorted({str(t).upper().strip() for t in tickers if str(t).strip()}):
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "EARNINGS", "symbol": ticker, "apikey": key},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Alpha Vantage request failed {resp.status_code} for {ticker}: {resp.text[:500]}")
        payload = resp.json()
        if "Information" in payload or "Note" in payload or "Error Message" in payload:
            msg = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
            raise RuntimeError(f"Alpha Vantage returned a non-data response for {ticker}: {msg}")

        ticker_rows: list[dict] = []
        for raw in payload.get("quarterlyEarnings", []) or []:
            reported_date = pd.to_datetime(raw.get("reportedDate"), errors="coerce")
            if pd.isna(reported_date):
                continue
            if start_ts is not None and not pd.isna(start_ts) and reported_date < start_ts:
                continue
            if end_ts is not None and not pd.isna(end_ts) and reported_date > end_ts:
                continue
            fiscal_date = pd.to_datetime(raw.get("fiscalDateEnding"), errors="coerce")
            fiscal_label = pd.Timestamp(fiscal_date).date().isoformat() if pd.notna(fiscal_date) else "unknown"
            reported_label = pd.Timestamp(reported_date).date().isoformat()
            event_time = _event_time_from_reported_date(pd.Timestamp(reported_date), release_session)
            ticker_rows.append(
                _earnings_row_from_eps(
                    ticker=ticker,
                    event_time=event_time,
                    reported_date=reported_label,
                    fiscal_period_end=fiscal_label,
                    source_type="alpha_vantage_earnings",
                    source_url="https://www.alphavantage.co/documentation/#earnings",
                    event_subtype="alpha_vantage_quarterly_eps",
                    release_session=release_session,
                    sector_benchmark=sector_benchmark,
                    actual_eps=_float_or_nan(raw.get("reportedEPS")),
                    consensus_eps=_float_or_nan(raw.get("estimatedEPS")),
                    eps_surprise=_float_or_nan(raw.get("surprise")),
                    eps_surprise_pct=_float_or_nan(raw.get("surprisePercentage")),
                    notes="Bootstrap row from Alpha Vantage. Validate release timing and add revenue/guidance/options expectations before serious use.",
                )
            )
        if limit_per_ticker:
            ticker_rows = sorted(ticker_rows, key=lambda r: r["event_time"])[-int(limit_per_ticker):]
        rows.extend(ticker_rows)
        time.sleep(60.0 / max(float(requests_per_minute), 0.1))

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates("event_id").sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    make_event_template(out_path, out.to_dict("records"))
    return out


def write_manual_earnings_template(out_path: str | Path, tickers: Iterable[str] | None = None) -> pd.DataFrame:
    """Write a manual earnings/guidance event template."""
    rows: list[dict] = []
    for ticker in sorted({str(t).upper().strip() for t in (tickers or []) if str(t).strip()}):
        rows.append(
            {
                "event_id": f"{ticker}_earnings_manual_YYYYMMDD",
                "ticker": ticker,
                "event_time": "YYYY-MM-DDTHH:MM:SS",
                "event_type": "earnings",
                "summary": "Fill in the point-in-time earnings/guidance summary before modeling.",
                "event_subtype": "quarterly_results",
                "source_type": "press_release_or_sec_filing",
                "source_url": "",
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": "unknown",
                "surprise_magnitude": "unknown",
                "materiality": 0.7,
                "sector_benchmark": "",
                "notes": "Curate event_time, release_session, expectedness, surprise_direction, surprise_magnitude, and materiality before use.",
                "event_family": "earnings_guidance",
                "fiscal_period_end": "",
            }
        )
    make_event_template(out_path, rows)
    return pd.read_csv(out_path)
