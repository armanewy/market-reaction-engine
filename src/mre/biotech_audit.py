from __future__ import annotations

import json
from math import exp, log
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .paths import ensure_dir, ensure_parent
from .prices import load_price_csv


BIOTECH_AUDIT_DECISIONS = {
    "result survives audit",
    "result weakened but still promising",
    "timestamp leakage found",
    "outlier-driven",
    "execution unrealistic",
}

NEGATIVE_FAILURE_TYPES = {
    "fda_complete_response_letter",
    "trial_halt",
    "endpoint_failure",
    "trial_discontinuation",
}

RESULT_LANGUAGE = (
    "announced topline",
    "topline results",
    "met primary endpoint",
    "did not meet",
    "failed to meet",
    "statistically significant",
    "complete response letter",
    "crl",
    "clinical hold",
    "trial halted",
    "study discontinued",
    "fda approved",
)

PRIOR_LANGUAGE = ("previously announced", "as previously disclosed", "previously reported", "previously presented")
CONFERENCE_PUBLICATION_LANGUAGE = (
    "conference",
    "poster",
    "oral presentation",
    "abstract",
    "published in",
    "publication",
)
PIPELINE_TABLE_LANGUAGE = ("pipeline table", "pipeline update", "corporate presentation", "investor presentation")


def _read_csv(value: str | Path | pd.DataFrame | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    p = Path(value)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].map(_bool_value)


def _to_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _write_json(path: str | Path, payload: dict[str, object]) -> Path:
    p = ensure_parent(path)
    p.write_text(json.dumps(_to_jsonable(payload), indent=2), encoding="utf-8")
    return p


def _simple_from_log(value: object) -> float:
    try:
        x = float(value)
    except Exception:
        return float("nan")
    if np.isnan(x):
        return float("nan")
    return float(exp(x) - 1.0)


def _log_from_simple(value: object) -> float:
    try:
        x = float(value)
    except Exception:
        return float("nan")
    if np.isnan(x) or x <= -1.0:
        return float("nan")
    return float(log(1.0 + x))


def _contains_any(text: object, needles: Iterable[str]) -> bool:
    lower = _clean_text(text).lower()
    return any(needle in lower for needle in needles)


def _norm_key(value: object) -> str:
    text = _clean_text(value).lower()
    chars = [c if c.isalnum() else " " for c in text]
    return " ".join("".join(chars).split())


def _dominant_clean(series: pd.Series, default: str = "unknown") -> str:
    cleaned = series.map(_clean_text)
    cleaned = cleaned[cleaned.ne("")]
    if cleaned.empty:
        return default
    mode = cleaned.mode()
    return _clean_text(mode.iloc[0]) if not mode.empty else default


def _split_doc_ids(value: object) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    return [part.strip() for part in text.replace(",", ";").split(";") if part.strip()]


def _parse_utc(value: object) -> pd.Timestamp | pd.NaT:
    text = _clean_text(value)
    if not text:
        return pd.NaT
    return pd.to_datetime(text, errors="coerce", utc=True)


def _as_date(value: object) -> pd.Timestamp | pd.NaT:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return pd.Timestamp(ts).tz_localize(None).normalize()


def _session_from_eastern(ts: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(ts):
        return "unknown"
    eastern = pd.Timestamp(ts).tz_convert(ZoneInfo("America/New_York"))
    minutes = eastern.hour * 60 + eastern.minute
    if minutes < 9 * 60 + 30:
        return "before_open"
    if minutes < 16 * 60:
        return "intraday"
    return "after_close"


def _eastern_iso(ts: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).tz_convert(ZoneInfo("America/New_York")).isoformat()


def _source_groups(source_documents: pd.DataFrame) -> dict[str, dict[str, object]]:
    if source_documents.empty or "event_id" not in source_documents.columns:
        return {}
    groups: dict[str, dict[str, object]] = {}
    for event_id, group in source_documents.groupby(source_documents["event_id"].astype(str), dropna=False):
        times = [_parse_utc(v) for v in group.get("event_time", pd.Series(dtype=object))]
        times = [t for t in times if not pd.isna(t)]
        source_types = sorted({_clean_text(v) for v in group.get("source_type", pd.Series(dtype=object)) if _clean_text(v)})
        groups[str(event_id)] = {
            "source_doc_count": int(len(group)),
            "source_types": source_types,
            "source_event_time_utc": min(times).isoformat() if times else "",
            "source_url_count": int(group.get("source_url", pd.Series(dtype=object)).dropna().nunique()),
            "source_hash_count": int(group.get("source_hash", pd.Series(dtype=object)).dropna().nunique()),
        }
    return groups


def _load_price_cached(prices_dir: str | Path, ticker: str, cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ticker = str(ticker).upper().strip()
    if ticker not in cache:
        cache[ticker] = load_price_csv(prices_dir, ticker)
    return cache[ticker]


def _first_on_or_after(dates: pd.Series | pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    if isinstance(dates, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(dates).tz_localize(None).normalize()
    else:
        idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates), errors="coerce").dt.tz_localize(None).dt.normalize())
    idx = idx.dropna().sort_values()
    pos = idx.searchsorted(pd.Timestamp(date).tz_localize(None).normalize(), side="left")
    if pos >= len(idx):
        return pd.NaT
    return pd.Timestamp(idx[pos])


def _first_after(dates: pd.Series | pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    if isinstance(dates, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(dates).tz_localize(None).normalize()
    else:
        idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates), errors="coerce").dt.tz_localize(None).dt.normalize())
    idx = idx.dropna().sort_values()
    pos = idx.searchsorted(pd.Timestamp(date).tz_localize(None).normalize(), side="right")
    if pos >= len(idx):
        return pd.NaT
    return pd.Timestamp(idx[pos])


def _expected_reaction_start(price_dates: pd.Series | pd.DatetimeIndex, event_time_utc: pd.Timestamp | pd.NaT, session: str) -> pd.Timestamp | pd.NaT:
    if pd.isna(event_time_utc):
        return pd.NaT
    event_date_et = pd.Timestamp(event_time_utc).tz_convert(ZoneInfo("America/New_York")).tz_localize(None).normalize()
    if session == "after_close":
        return _first_after(price_dates, event_date_et)
    return _first_on_or_after(price_dates, event_date_et)


def build_timestamp_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    source_documents: str | Path | pd.DataFrame | None = None,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Audit daily reaction windows against SEC acceptance timestamps.

    This does not relabel events. It checks whether the first daily return window
    could have used information before the event was public.
    """
    events = _read_csv(event_study)
    sources = _read_csv(source_documents)
    source_by_event = _source_groups(sources)
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []

    for _, row in events.iterrows():
        event_id = _clean_text(row.get("event_id"))
        ticker = _clean_text(row.get("ticker")).upper()
        source_info = source_by_event.get(event_id, {})
        source_time = _parse_utc(source_info.get("source_event_time_utc", "")) if source_info else pd.NaT
        fallback_time = _parse_utc(row.get("event_time"))
        event_time_utc = source_time if not pd.isna(source_time) else fallback_time
        inferred_session = _session_from_eastern(event_time_utc)
        used_session = _clean_text(row.get("release_session")).lower() or "unknown"
        reaction_start = _as_date(row.get("reaction_start"))
        actual = "" if pd.isna(reaction_start) else reaction_start.date().isoformat()
        expected = pd.NaT
        expected_used = pd.NaT
        price_status = "ok"
        try:
            prices = _load_price_cached(prices_dir, ticker, price_cache)
            expected = _expected_reaction_start(prices["date"], event_time_utc, inferred_session)
            expected_used = _expected_reaction_start(prices["date"], event_time_utc, used_session)
        except Exception as exc:
            price_status = f"price_lookup_failed: {exc}"

        findings: list[str] = []
        risk = "low"
        if pd.isna(event_time_utc):
            risk = "medium"
            findings.append("missing_sec_acceptance_time")
        if price_status != "ok":
            risk = "medium"
            findings.append(price_status)
        if used_session != "unknown" and inferred_session != "unknown" and used_session != inferred_session:
            findings.append("release_session_differs_from_sec_acceptance_et")
        if not pd.isna(expected) and not pd.isna(reaction_start):
            if reaction_start < expected:
                risk = "high"
                findings.append("reaction_start_before_sec_timestamp_first_tradable")
            elif used_session != inferred_session and expected == reaction_start:
                findings.append("session_mismatch_no_daily_window_shift")
            elif reaction_start > expected:
                findings.append("reaction_start_after_sec_timestamp_first_tradable")
        if inferred_session == "intraday":
            findings.append("daily_ohlc_cannot_verify_intraday_fill_or_trading_halt")
        if inferred_session == "after_close" and not pd.isna(expected) and reaction_start == expected:
            findings.append("after_close_correctly_shifted_to_next_trading_day")
        if risk != "high" and any("daily_ohlc" in finding for finding in findings):
            risk = "medium"

        rows.append(
            {
                "event_id": event_id,
                "ticker": ticker,
                "event_time_raw": _clean_text(row.get("event_time")),
                "source_event_time_utc": "" if pd.isna(event_time_utc) else event_time_utc.isoformat(),
                "sec_acceptance_time_et": _eastern_iso(event_time_utc),
                "release_session_used": used_session,
                "session_from_sec_acceptance_et": inferred_session,
                "session_mismatch": bool(used_session != inferred_session and inferred_session != "unknown" and used_session != "unknown"),
                "reaction_start": actual,
                "expected_reaction_start_from_sec_session": "" if pd.isna(expected) else expected.date().isoformat(),
                "expected_reaction_start_from_used_session": "" if pd.isna(expected_used) else expected_used.date().isoformat(),
                "reaction_start_before_expected": bool(not pd.isna(expected) and not pd.isna(reaction_start) and reaction_start < expected),
                "first_tradable_window_status": "needs_review" if risk in {"medium", "high"} else "ok",
                "timestamp_risk_level": risk,
                "source_doc_count": int(source_info.get("source_doc_count", 0) or 0),
                "source_types": ";".join(source_info.get("source_types", [])) if source_info else "",
                "press_release_time_status": "sec_exhibit_acceptance_only" if "sec_exhibit" in source_info.get("source_types", []) else "not_separately_available",
                "fda_page_timing_status": "not_available_in_local_artifacts",
                "timestamp_findings": ";".join(findings) if findings else "none",
            }
        )

    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def build_duplicate_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    source_documents: str | Path | pd.DataFrame | None = None,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    events = _read_csv(event_study)
    sources = _read_csv(source_documents)
    source_by_event = _source_groups(sources)
    if events.empty:
        out = pd.DataFrame()
        if out_path:
            ensure_parent(out_path)
            out.to_csv(out_path, index=False)
        return out

    work = events.copy()
    work["_reaction_date"] = pd.to_datetime(work.get("reaction_start", work.get("event_time")), errors="coerce").dt.date.astype(str)
    asset_key = []
    for _, row in work.iterrows():
        parts = [_norm_key(row.get("nct_id")), _norm_key(row.get("trial_name")), _norm_key(row.get("drug_asset")), _norm_key(row.get("indication"))]
        asset_key.append(next((part for part in parts if part), _norm_key(row.get("biotech_catalyst_event_type", row.get("event_type")))))
    work["_asset_key"] = asset_key
    event_type = work.get("biotech_catalyst_event_type", work.get("event_type", pd.Series("", index=work.index))).fillna("").astype(str).str.lower()
    ticker = work.get("ticker", pd.Series("", index=work.index)).fillna("").astype(str).str.upper()
    work["_duplicate_key"] = ticker + "|" + work["_reaction_date"] + "|" + event_type + "|" + work["_asset_key"]
    counts = work["_duplicate_key"].value_counts()

    rows: list[dict[str, object]] = []
    for _, row in work.iterrows():
        event_id = _clean_text(row.get("event_id"))
        info = source_by_event.get(event_id, {})
        source_types = set(info.get("source_types", []))
        text = " ".join(
            [
                _clean_text(row.get("summary")),
                _clean_text(row.get("source_evidence_text")),
                _clean_text(row.get("review_notes")),
                _clean_text(row.get("parser_quality_flags")),
            ]
        )
        prior = _contains_any(text, PRIOR_LANGUAGE)
        conf = _contains_any(text, CONFERENCE_PUBLICATION_LANGUAGE)
        pipeline = _contains_any(text, PIPELINE_TABLE_LANGUAGE)
        result_terms = _contains_any(text, RESULT_LANGUAGE)
        source_mirror = bool("sec_primary_filing" in source_types and "sec_exhibit" in source_types)
        same_key_count = int(counts.get(row["_duplicate_key"], 0))
        findings: list[str] = []
        risk = "low"
        duplicate_type = "none"
        if same_key_count > 1:
            duplicate_type = "same_ticker_asset_day_duplicate"
            risk = "high"
            findings.append("same_ticker_asset_event_type_reaction_day_count_gt_1")
        if source_mirror:
            if duplicate_type == "none":
                duplicate_type = "source_mirror_only"
            findings.append("same_catalyst_supported_by_8k_and_exhibit")
        if prior:
            if duplicate_type == "none":
                duplicate_type = "prior_announcement_language"
            risk = "medium" if risk == "low" else risk
            findings.append("prior_announcement_language_present")
        if conf:
            if duplicate_type == "none":
                duplicate_type = "conference_publication_language"
            risk = "medium" if risk == "low" and not result_terms else risk
            findings.append("conference_or_publication_language_present")
        if pipeline:
            if duplicate_type == "none":
                duplicate_type = "pipeline_update_language"
            risk = "medium" if risk == "low" and not result_terms else risk
            findings.append("pipeline_or_investor_presentation_language_present")

        rows.append(
            {
                "event_id": event_id,
                "ticker": _clean_text(row.get("ticker")).upper(),
                "reaction_start": _clean_text(row.get("reaction_start")),
                "biotech_catalyst_event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type"))),
                "drug_asset": _clean_text(row.get("drug_asset")),
                "indication": _clean_text(row.get("indication")),
                "trial_name": _clean_text(row.get("trial_name")),
                "nct_id": _clean_text(row.get("nct_id")),
                "duplicate_key": row["_duplicate_key"],
                "same_key_event_count": same_key_count,
                "source_doc_count": int(info.get("source_doc_count", 0) or 0),
                "source_types": ";".join(sorted(source_types)),
                "source_mirror_flag": source_mirror,
                "prior_announcement_language_flag": prior,
                "conference_publication_language_flag": conf,
                "pipeline_or_investor_deck_language_flag": pipeline,
                "explicit_result_language_flag": result_terms,
                "duplicate_type": duplicate_type,
                "duplicate_risk_level": risk,
                "duplicate_findings": ";".join(findings) if findings else "none",
            }
        )
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def _event_ok(frame: pd.DataFrame) -> pd.DataFrame:
    if "event_status" not in frame.columns:
        return frame.copy()
    return frame[frame["event_status"].fillna("").astype(str).eq("ok")].copy()


def _summarize_log_returns(series: pd.Series) -> dict[str, object]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "mean_log": float(s.mean()),
        "median_log": float(s.median()),
        "mean_simple": float(s.map(_simple_from_log).mean()),
        "median_simple": float(s.map(_simple_from_log).median()),
        "positive_rate": float((s > 0).mean()),
        "mean_abs_log": float(s.abs().mean()),
    }


def build_outlier_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    strategy_trades: str | Path | pd.DataFrame | None = None,
    out_path: str | Path | None = None,
) -> dict[str, object]:
    events = _event_ok(_read_csv(event_study))
    trades = _read_csv(strategy_trades)
    frame = events.copy()
    car = pd.to_numeric(frame.get("car_sector_adj_h1", pd.Series(np.nan, index=frame.index)), errors="coerce")
    frame = frame[car.notna()].copy()
    frame["_h1"] = car.loc[frame.index]
    frame["_abs_h1"] = frame["_h1"].abs()
    frame = frame.sort_values("_abs_h1", ascending=False).reset_index(drop=True)
    total_abs = float(frame["_abs_h1"].sum()) if not frame.empty else 0.0
    exclusion_rows: list[dict[str, object]] = []
    for n in [0, 1, 3, 5]:
        subset = frame.iloc[n:].copy()
        row: dict[str, object] = {"excluded_top_abs_h1_events": n, "rows": int(len(subset))}
        for h in [1, 3, 10]:
            row[f"h{h}"] = _summarize_log_returns(subset.get(f"car_sector_adj_h{h}", pd.Series(dtype=float)))
        exclusion_rows.append(row)

    ticker_rows: list[dict[str, object]] = []
    if not frame.empty and total_abs > 0:
        for ticker, group in frame.groupby(frame["ticker"].fillna("").astype(str).str.upper(), dropna=False):
            ticker_rows.append(
                {
                    "ticker": ticker,
                    "event_count": int(len(group)),
                    "abs_h1_sum": float(group["_abs_h1"].sum()),
                    "abs_h1_share": float(group["_abs_h1"].sum() / total_abs),
                    "mean_h1": float(group["_h1"].mean()),
                }
            )
    ticker_rows = sorted(ticker_rows, key=lambda item: item["abs_h1_share"], reverse=True)

    indication_rows: list[dict[str, object]] = []
    if "indication" in frame.columns and total_abs > 0:
        indications = frame["indication"].fillna("unknown").map(lambda v: _norm_key(v) or "unknown")
        for indication, group in frame.groupby(indications, dropna=False):
            indication_rows.append(
                {
                    "indication": indication,
                    "event_count": int(len(group)),
                    "abs_h1_share": float(group["_abs_h1"].sum() / total_abs),
                    "mean_h1": float(group["_h1"].mean()),
                }
            )
    indication_rows = sorted(indication_rows, key=lambda item: item["abs_h1_share"], reverse=True)

    event_type = frame.get("biotech_catalyst_event_type", frame.get("event_type", pd.Series("", index=frame.index))).fillna("").astype(str).str.lower()
    failure_mask = event_type.isin(NEGATIVE_FAILURE_TYPES) | _bool_series(frame, "trial_failure_flag")
    failure_abs_share = float(frame.loc[failure_mask, "_abs_h1"].sum() / total_abs) if total_abs > 0 else None
    failure_mean = float(frame.loc[failure_mask, "_h1"].mean()) if failure_mask.any() else None

    top_events = [
        {
            "rank": int(i + 1),
            "event_id": _clean_text(row.get("event_id")),
            "ticker": _clean_text(row.get("ticker")),
            "biotech_catalyst_event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type"))),
            "event_direction_pre_price": _clean_text(row.get("event_direction_pre_price")),
            "market_cap_bucket": _clean_text(row.get("market_cap_bucket")),
            "h1_car_sector_adj": float(row["_h1"]),
            "h3_car_sector_adj": float(pd.to_numeric(pd.Series([row.get("car_sector_adj_h3")]), errors="coerce").iloc[0]),
            "abs_h1_share": float(row["_abs_h1"] / total_abs) if total_abs > 0 else None,
        }
        for i, row in frame.head(10).iterrows()
    ]

    trade_summary: dict[str, object] = {"available": False}
    if not trades.empty and "net_event_return" in trades.columns:
        trade_frame = trades.copy()
        trade_frame["_abs_net"] = pd.to_numeric(trade_frame["net_event_return"], errors="coerce").abs()
        total_trade_abs = float(trade_frame["_abs_net"].sum())
        trade_summary = {
            "available": True,
            "n_trades": int(len(trade_frame)),
            "top_1_abs_net_share": float(trade_frame["_abs_net"].nlargest(1).sum() / total_trade_abs) if total_trade_abs > 0 else None,
            "top_5_abs_net_share": float(trade_frame["_abs_net"].nlargest(5).sum() / total_trade_abs) if total_trade_abs > 0 else None,
        }

    summary: dict[str, object] = {
        "event_rows": int(len(frame)),
        "top_1_abs_h1_share": float(frame["_abs_h1"].head(1).sum() / total_abs) if total_abs > 0 else None,
        "top_3_abs_h1_share": float(frame["_abs_h1"].head(3).sum() / total_abs) if total_abs > 0 else None,
        "top_5_abs_h1_share": float(frame["_abs_h1"].head(5).sum() / total_abs) if total_abs > 0 else None,
        "top_ticker_abs_h1_share": ticker_rows[0]["abs_h1_share"] if ticker_rows else None,
        "top_ticker": ticker_rows[0]["ticker"] if ticker_rows else "",
        "top_indication_abs_h1_share": indication_rows[0]["abs_h1_share"] if indication_rows else None,
        "top_indication": indication_rows[0]["indication"] if indication_rows else "",
        "crl_halt_failure_event_count": int(failure_mask.sum()),
        "crl_halt_failure_abs_h1_share": failure_abs_share,
        "crl_halt_failure_mean_h1": failure_mean,
        "exclusion_sensitivity": exclusion_rows,
        "top_events": top_events,
        "ticker_concentration": ticker_rows[:10],
        "indication_concentration": indication_rows[:10],
        "strategy_trade_concentration": trade_summary,
    }

    if out_path:
        write_outlier_audit_markdown(out_path, summary)
    return summary


def write_outlier_audit_markdown(path: str | Path, summary: dict[str, object]) -> Path:
    lines = [
        "# Biotech Catalyst Outlier Audit",
        "",
        "This audit tries to break the Agent 3D result. It does not change parser labels, thresholds, or event definitions.",
        "",
        "## Concentration Summary",
        "",
        f"- event rows: {summary.get('event_rows')}",
        f"- top 1 absolute h1 event share: {summary.get('top_1_abs_h1_share')}",
        f"- top 3 absolute h1 event share: {summary.get('top_3_abs_h1_share')}",
        f"- top 5 absolute h1 event share: {summary.get('top_5_abs_h1_share')}",
        f"- top ticker: {summary.get('top_ticker')} ({summary.get('top_ticker_abs_h1_share')})",
        f"- top indication: {summary.get('top_indication')} ({summary.get('top_indication_abs_h1_share')})",
        f"- CRL / halt / failure rows: {summary.get('crl_halt_failure_event_count')}",
        f"- CRL / halt / failure absolute h1 share: {summary.get('crl_halt_failure_abs_h1_share')}",
        f"- CRL / halt / failure mean h1: {summary.get('crl_halt_failure_mean_h1')}",
        "",
        "## Top Absolute h1 Events",
        "",
        "| rank | ticker | event_type | direction | h1 | h3 | abs_share | event_id |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("top_events", []):
        lines.append(
            f"| {row['rank']} | {row['ticker']} | {row['biotech_catalyst_event_type']} | {row['event_direction_pre_price']} | "
            f"{row['h1_car_sector_adj']:.6f} | {row['h3_car_sector_adj']:.6f} | {row['abs_h1_share']:.6f} | {row['event_id']} |"
        )
    lines.extend(["", "## Excluding Top Absolute h1 Events", "", "| excluded | rows | h1 mean | h1 median | h3 mean | h10 mean |", "| ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in summary.get("exclusion_sensitivity", []):
        h1 = row.get("h1", {})
        h3 = row.get("h3", {})
        h10 = row.get("h10", {})
        lines.append(
            f"| {row.get('excluded_top_abs_h1_events')} | {row.get('rows')} | {h1.get('mean_log')} | {h1.get('median_log')} | {h3.get('mean_log')} | {h10.get('mean_log')} |"
        )
    lines.extend(["", "## Ticker Concentration", "", "| ticker | events | abs_h1_share | mean_h1 |", "| --- | ---: | ---: | ---: |"])
    for row in summary.get("ticker_concentration", []):
        lines.append(f"| {row['ticker']} | {row['event_count']} | {row['abs_h1_share']:.6f} | {row['mean_h1']:.6f} |")
    lines.extend(["", "## Therapeutic Area / Indication Concentration", "", "| indication | events | abs_h1_share | mean_h1 |", "| --- | ---: | ---: | ---: |"])
    for row in summary.get("indication_concentration", []):
        lines.append(f"| {row['indication']} | {row['event_count']} | {row['abs_h1_share']:.6f} | {row['mean_h1']:.6f} |")
    trade = summary.get("strategy_trade_concentration", {}) or {}
    lines.extend(
        [
            "",
            "## Strategy Trade Concentration",
            "",
            f"- available: {trade.get('available')}",
            f"- trades: {trade.get('n_trades')}",
            f"- top 1 absolute net-return share: {trade.get('top_1_abs_net_share')}",
            f"- top 5 absolute net-return share: {trade.get('top_5_abs_net_share')}",
            "",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def build_liquidity_risk_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    events = _event_ok(_read_csv(event_study))
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for _, row in events.iterrows():
        ticker = _clean_text(row.get("ticker")).upper()
        reaction_start = _as_date(row.get("reaction_start"))
        flags: list[str] = []
        metrics: dict[str, object] = {
            "event_id": _clean_text(row.get("event_id")),
            "ticker": ticker,
            "reaction_start": "" if pd.isna(reaction_start) else reaction_start.date().isoformat(),
            "biotech_catalyst_event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type"))),
            "market_cap_before_event": row.get("market_cap_before_event", np.nan),
            "market_cap_bucket": _clean_text(row.get("market_cap_bucket")),
        }
        try:
            prices = _load_price_cached(prices_dir, ticker, price_cache)
            prices = prices.sort_values("date").reset_index(drop=True)
            idx = prices.index[prices["date"].eq(reaction_start)]
            if len(idx) == 0:
                flags.append("missing_reaction_start_price")
            else:
                pos = int(idx[0])
                prior = prices.iloc[max(0, pos - 20) : pos].copy()
                prev = prices.iloc[pos - 1] if pos > 0 else None
                current = prices.iloc[pos]
                prev_close = float(prev["adj_close"]) if prev is not None else np.nan
                open_price = float(current["open"]) if not pd.isna(current["open"]) else np.nan
                close_price = float(current["close"]) if not pd.isna(current["close"]) else float(current["adj_close"])
                metrics.update(
                    {
                        "prev_close": prev_close,
                        "reaction_open": open_price,
                        "reaction_close": close_price,
                        "pre20_avg_dollar_volume": float((prior["close"] * prior["volume"]).mean()) if len(prior) else np.nan,
                        "pre20_median_dollar_volume": float((prior["close"] * prior["volume"]).median()) if len(prior) else np.nan,
                        "pre20_avg_volume": float(prior["volume"].mean()) if len(prior) else np.nan,
                        "gap_from_prev_close": float(open_price / prev_close - 1.0) if prev_close and not np.isnan(open_price) else np.nan,
                        "event_day_open_to_close": float(close_price / open_price - 1.0) if open_price and not np.isnan(open_price) else np.nan,
                        "event_day_range_over_open": float((current["high"] - current["low"]) / open_price) if open_price and not np.isnan(open_price) else np.nan,
                    }
                )
                if prev_close < 1.0:
                    flags.append("price_under_1")
                if prev_close < 5.0:
                    flags.append("price_under_5")
                avg_dollar = metrics["pre20_avg_dollar_volume"]
                if pd.notna(avg_dollar) and float(avg_dollar) < 1_000_000:
                    flags.append("very_low_pre20_dollar_volume")
                elif pd.notna(avg_dollar) and float(avg_dollar) < 5_000_000:
                    flags.append("low_pre20_dollar_volume")
                gap = metrics["gap_from_prev_close"]
                if pd.notna(gap) and abs(float(gap)) >= 0.20:
                    flags.append("gap_abs_ge_20pct")
                elif pd.notna(gap) and abs(float(gap)) >= 0.10:
                    flags.append("gap_abs_ge_10pct")
        except Exception as exc:
            flags.append(f"price_lookup_failed:{exc}")

        text = " ".join([_clean_text(row.get("source_evidence_text")), _clean_text(row.get("summary")), _clean_text(row.get("review_notes"))]).lower()
        if "clinical hold" in text or "trial halt" in text or "halted" in text:
            flags.append("clinical_hold_or_halt_language")
        risk_score = sum(flag in flags for flag in ["price_under_1", "very_low_pre20_dollar_volume", "gap_abs_ge_20pct"])
        if risk_score >= 2:
            risk = "high"
        elif flags:
            risk = "medium"
        else:
            risk = "low"
        metrics["liquidity_execution_risk"] = risk
        metrics["risk_flags"] = ";".join(flags) if flags else "none"
        rows.append(metrics)
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def _price_return_window(prices: pd.DataFrame, start: pd.Timestamp, horizon: int, *, column: str = "adj_close") -> float:
    prices = prices.sort_values("date").reset_index(drop=True)
    idx = prices.index[prices["date"].eq(start)]
    if len(idx) == 0:
        return float("nan")
    pos = int(idx[0])
    if pos < 1 or pos + horizon - 1 >= len(prices):
        return float("nan")
    prev = float(prices.loc[pos - 1, column])
    end = float(prices.loc[pos + horizon - 1, column])
    if prev <= 0 or end <= 0:
        return float("nan")
    return float(log(end / prev))


def _beta_to_xbi(
    prices_dir: str | Path,
    ticker: str,
    before_date: pd.Timestamp,
    price_cache: dict[str, pd.DataFrame],
    *,
    window: int = 120,
    min_obs: int = 50,
) -> float:
    try:
        px = _load_price_cached(prices_dir, ticker, price_cache)
        xbi = _load_price_cached(prices_dir, "XBI", price_cache)
    except Exception:
        return float("nan")
    series = pd.concat(
        [
            px.set_index("date")["adj_close"].rename("ticker"),
            xbi.set_index("date")["adj_close"].rename("xbi"),
        ],
        axis=1,
    ).sort_index()
    returns = np.log(series / series.shift(1)).dropna()
    returns = returns[returns.index < before_date].tail(window)
    if len(returns) < min_obs or returns["xbi"].var() <= 0:
        return float("nan")
    return float(returns["ticker"].cov(returns["xbi"]) / returns["xbi"].var())


def build_matched_peer_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    events = _event_ok(_read_csv(event_study))
    if events.empty:
        out = pd.DataFrame()
        if out_path:
            ensure_parent(out_path)
            out.to_csv(out_path, index=False)
        return out
    price_dir = Path(prices_dir)
    tickers = sorted(p.stem.upper() for p in price_dir.glob("*.csv") if p.stem.upper() not in {"SPY", "XBI", "IBB"})
    profile: dict[str, dict[str, object]] = {}
    for ticker, group in events.groupby(events["ticker"].astype(str).str.upper()):
        caps = pd.to_numeric(group.get("market_cap_before_event", pd.Series(dtype=float)), errors="coerce").dropna()
        profile[ticker] = {
            "market_cap": float(caps.median()) if len(caps) else np.nan,
            "market_cap_bucket": _dominant_clean(group["market_cap_bucket"]) if "market_cap_bucket" in group else "unknown",
            "trial_phase": _dominant_clean(group["trial_phase"]) if "trial_phase" in group else "unknown",
            "indication": _dominant_clean(group["indication"]) if "indication" in group else "unknown",
        }
    event_dates_by_ticker = {
        ticker: set(pd.to_datetime(group["reaction_start"], errors="coerce").dt.normalize().dropna())
        for ticker, group in events.groupby(events["ticker"].astype(str).str.upper())
    }
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for _, row in events.iterrows():
        ticker = _clean_text(row.get("ticker")).upper()
        reaction_start = _as_date(row.get("reaction_start"))
        if pd.isna(reaction_start):
            continue
        original_beta = _beta_to_xbi(prices_dir, ticker, reaction_start, price_cache)
        original_bucket = _clean_text(row.get("market_cap_bucket")) or profile.get(ticker, {}).get("market_cap_bucket", "unknown")
        original_phase = _norm_key(row.get("trial_phase"))
        original_indication = set(_norm_key(row.get("indication")).split())
        candidates: list[dict[str, object]] = []
        for peer in tickers:
            if peer == ticker:
                continue
            if reaction_start in event_dates_by_ticker.get(peer, set()):
                continue
            try:
                peer_prices = _load_price_cached(prices_dir, peer, price_cache)
                if not peer_prices["date"].eq(reaction_start).any():
                    continue
            except Exception:
                continue
            peer_profile = profile.get(peer, {})
            peer_beta = _beta_to_xbi(prices_dir, peer, reaction_start, price_cache)
            peer_bucket = _clean_text(peer_profile.get("market_cap_bucket", "unknown"))
            peer_phase = _norm_key(peer_profile.get("trial_phase", ""))
            peer_indication = set(_norm_key(peer_profile.get("indication", "")).split())
            beta_penalty = abs(peer_beta - original_beta) if pd.notna(peer_beta) and pd.notna(original_beta) else 1.0
            bucket_penalty = 0.0 if peer_bucket and peer_bucket == original_bucket else 0.5
            phase_penalty = 0.0 if peer_phase and peer_phase == original_phase else 0.25
            overlap = 0.0
            if original_indication and peer_indication:
                overlap = len(original_indication & peer_indication) / max(1, len(original_indication | peer_indication))
            indication_penalty = 0.25 * (1.0 - overlap)
            score = float(beta_penalty + bucket_penalty + phase_penalty + indication_penalty)
            candidates.append(
                {
                    "peer_ticker": peer,
                    "peer_beta_xbi": peer_beta,
                    "peer_market_cap_bucket": peer_bucket or "unknown",
                    "peer_trial_phase_profile": peer_phase or "unknown",
                    "indication_overlap": overlap,
                    "score": score,
                }
            )
        if not candidates:
            continue
        best = min(candidates, key=lambda item: item["score"])
        peer_px = _load_price_cached(prices_dir, best["peer_ticker"], price_cache)
        xbi_px = _load_price_cached(prices_dir, "XBI", price_cache)
        out_row = {
            "event_id": _clean_text(row.get("event_id")),
            "ticker": ticker,
            "peer_ticker": best["peer_ticker"],
            "reaction_start": reaction_start.date().isoformat(),
            "biotech_catalyst_event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type"))),
            "event_direction_pre_price": _clean_text(row.get("event_direction_pre_price")),
            "market_cap_bucket": original_bucket,
            "peer_market_cap_bucket": best["peer_market_cap_bucket"],
            "original_beta_xbi": original_beta,
            "peer_beta_xbi": best["peer_beta_xbi"],
            "beta_abs_diff": abs(best["peer_beta_xbi"] - original_beta) if pd.notna(best["peer_beta_xbi"]) and pd.notna(original_beta) else np.nan,
            "trial_phase": _clean_text(row.get("trial_phase")),
            "peer_trial_phase_profile": best["peer_trial_phase_profile"],
            "indication_overlap": best["indication_overlap"],
            "match_score": best["score"],
        }
        for h in [1, 3, 10]:
            peer_log = _price_return_window(peer_px, reaction_start, h)
            xbi_log = _price_return_window(xbi_px, reaction_start, h)
            out_row[f"peer_car_sector_adj_h{h}"] = float(peer_log - xbi_log) if pd.notna(peer_log) and pd.notna(xbi_log) else np.nan
        rows.append(out_row)
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def _stress_summary_from_gross(trades: pd.DataFrame, *, gross_column: str, cost_bps_values: Iterable[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cost_bps in cost_bps_values:
        frame = trades.copy()
        frame["gross"] = pd.to_numeric(frame[gross_column], errors="coerce")
        frame["position"] = pd.to_numeric(frame["position"], errors="coerce")
        frame["net"] = frame["position"] * frame["gross"] - np.where(frame["position"].ne(0), float(cost_bps) / 10000.0, 0.0)
        frame = frame[frame["net"].notna() & frame["position"].ne(0)].copy()
        if frame.empty:
            rows.append({"all_in_cost_bps": float(cost_bps), "n_trades": 0})
            continue
        equity = (1.0 + frame["net"]).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        rows.append(
            {
                "all_in_cost_bps": float(cost_bps),
                "n_trades": int(len(frame)),
                "n_long": int((frame["position"] == 1).sum()),
                "n_short": int((frame["position"] == -1).sum()),
                "mean_net_event_return": float(frame["net"].mean()),
                "median_net_event_return": float(frame["net"].median()),
                "hit_rate": float((frame["net"] > 0).mean()),
                "cumulative_net_return": float(equity.iloc[-1] - 1.0),
                "max_drawdown": float(drawdown.min()),
                "long_mean_net_event_return": float(frame.loc[frame["position"] == 1, "net"].mean()) if (frame["position"] == 1).any() else None,
                "short_mean_net_event_return": float(frame.loc[frame["position"] == -1, "net"].mean()) if (frame["position"] == -1).any() else None,
            }
        )
    return rows


def _next_trading_day(price_dates: pd.Series, date: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    return _first_after(price_dates, date)


def build_next_open_trade_frame(
    strategy_trades: str | Path | pd.DataFrame,
    *,
    timestamp_audit: str | Path | pd.DataFrame,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    trades = _read_csv(strategy_trades)
    timestamps = _read_csv(timestamp_audit)
    if trades.empty:
        out = pd.DataFrame()
        if out_path:
            ensure_parent(out_path)
            out.to_csv(out_path, index=False)
        return out
    session_by_event = timestamps.set_index("event_id")["session_from_sec_acceptance_et"].to_dict() if "event_id" in timestamps.columns else {}
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    xbi = _load_price_cached(prices_dir, "XBI", price_cache)
    for _, row in trades.iterrows():
        ticker = _clean_text(row.get("ticker")).upper()
        reaction_start = _as_date(row.get("reaction_start"))
        if pd.isna(reaction_start):
            continue
        try:
            px = _load_price_cached(prices_dir, ticker, price_cache)
        except Exception:
            continue
        session = _clean_text(session_by_event.get(_clean_text(row.get("event_id")), "")).lower()
        entry_date = reaction_start
        if session == "intraday":
            entry_date = _next_trading_day(px["date"], reaction_start)
        if pd.isna(entry_date):
            continue
        ticker_day = px[px["date"].eq(entry_date)]
        xbi_day = xbi[xbi["date"].eq(entry_date)]
        if ticker_day.empty or xbi_day.empty:
            continue
        ticker_day = ticker_day.iloc[0]
        xbi_day = xbi_day.iloc[0]
        if pd.isna(ticker_day["open"]) or pd.isna(ticker_day["close"]) or ticker_day["open"] <= 0:
            continue
        if pd.isna(xbi_day["open"]) or pd.isna(xbi_day["close"]) or xbi_day["open"] <= 0:
            continue
        ticker_intraday = float(ticker_day["close"] / ticker_day["open"] - 1.0)
        xbi_intraday = float(xbi_day["close"] / xbi_day["open"] - 1.0)
        gross = ticker_intraday - xbi_intraday
        rows.append(
            {
                "event_id": _clean_text(row.get("event_id")),
                "ticker": ticker,
                "reaction_start": reaction_start.date().isoformat(),
                "session_from_sec_acceptance_et": session or "unknown",
                "next_open_entry_date": entry_date.date().isoformat(),
                "position": int(row.get("position")),
                "close_to_close_gross_event_return": row.get("gross_event_return", np.nan),
                "next_open_sector_adjusted_intraday_return": gross,
                "entry_rule": "next_trading_day_open_for_intraday_else_reaction_start_open",
            }
        )
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def build_execution_stress_report(
    strategy_trades: str | Path | pd.DataFrame,
    *,
    liquidity_audit: str | Path | pd.DataFrame | None = None,
    timestamp_audit: str | Path | pd.DataFrame | None = None,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
    next_open_out_path: str | Path | None = None,
    cost_bps_values: tuple[float, ...] = (5.0, 25.0, 50.0, 100.0),
) -> dict[str, object]:
    trades = _read_csv(strategy_trades)
    if trades.empty:
        report = {"n_trades": 0, "stress": [], "next_open_stress": [], "warning": "strategy trades unavailable"}
        if out_path:
            write_execution_stress_markdown(out_path, report)
        return report
    stress = _stress_summary_from_gross(trades, gross_column="gross_event_return", cost_bps_values=cost_bps_values)
    next_open = pd.DataFrame()
    next_open_stress: list[dict[str, object]] = []
    if timestamp_audit is not None:
        next_open = build_next_open_trade_frame(
            trades,
            timestamp_audit=timestamp_audit,
            prices_dir=prices_dir,
            out_path=next_open_out_path,
        )
        if not next_open.empty:
            next_open_stress = _stress_summary_from_gross(
                next_open.rename(columns={"next_open_sector_adjusted_intraday_return": "gross_event_return"}),
                gross_column="gross_event_return",
                cost_bps_values=cost_bps_values,
            )
    liquidity = _read_csv(liquidity_audit)
    liquidity_summary: dict[str, object] = {}
    if not liquidity.empty:
        flags = liquidity.get("risk_flags", pd.Series("", index=liquidity.index)).fillna("").astype(str)
        liquidity_summary = {
            "events": int(len(liquidity)),
            "high_liquidity_execution_risk": int((liquidity.get("liquidity_execution_risk", pd.Series("", index=liquidity.index)) == "high").sum()),
            "medium_or_high_liquidity_execution_risk": int(liquidity.get("liquidity_execution_risk", pd.Series("", index=liquidity.index)).isin(["medium", "high"]).sum()),
            "price_under_5_count": int(flags.str.contains("price_under_5", regex=False).sum()),
            "price_under_1_count": int(flags.str.contains("price_under_1", regex=False).sum()),
            "gap_abs_ge_20pct_count": int(flags.str.contains("gap_abs_ge_20pct", regex=False).sum()),
            "low_dollar_volume_count": int(flags.str.contains("low_pre20_dollar_volume|very_low_pre20_dollar_volume", regex=True).sum()),
        }
    report = {
        "n_trades": int(len(trades)),
        "stress": stress,
        "next_open_trades": int(len(next_open)),
        "next_open_stress": next_open_stress,
        "liquidity_summary": liquidity_summary,
        "next_open_note": "Intraday SEC-acceptance events are conservatively shifted to the next trading day's open because local data is daily OHLC only.",
    }
    if out_path:
        write_execution_stress_markdown(out_path, report)
    return report


def write_execution_stress_markdown(path: str | Path, report: dict[str, object]) -> Path:
    lines = [
        "# Biotech Catalyst Execution Stress Report",
        "",
        "This report stresses biotech catalyst strategy trades without retuning thresholds or changing labels.",
        "",
        f"- strategy trades: {report.get('n_trades')}",
        f"- next-open stress trades: {report.get('next_open_trades')}",
        f"- next-open note: {report.get('next_open_note')}",
        "",
        "## Close-To-Close Cost Stress",
        "",
        "| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("stress", []):
        lines.append(
            f"| {row.get('all_in_cost_bps')} | {row.get('n_trades')} | {row.get('n_long')} | {row.get('n_short')} | "
            f"{row.get('mean_net_event_return')} | {row.get('median_net_event_return')} | {row.get('hit_rate')} | {row.get('cumulative_net_return')} | {row.get('max_drawdown')} |"
        )
    lines.extend(
        [
            "",
            "## Next-Open Execution Stress",
            "",
            "| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("next_open_stress", []):
        lines.append(
            f"| {row.get('all_in_cost_bps')} | {row.get('n_trades')} | {row.get('n_long')} | {row.get('n_short')} | "
            f"{row.get('mean_net_event_return')} | {row.get('median_net_event_return')} | {row.get('hit_rate')} | {row.get('cumulative_net_return')} | {row.get('max_drawdown')} |"
        )
    liquidity = report.get("liquidity_summary", {}) or {}
    lines.extend(
        [
            "",
            "## Liquidity And Gap Risk",
            "",
            f"- events audited: {liquidity.get('events')}",
            f"- medium/high liquidity or execution risk rows: {liquidity.get('medium_or_high_liquidity_execution_risk')}",
            f"- high liquidity or execution risk rows: {liquidity.get('high_liquidity_execution_risk')}",
            f"- price under $5 rows: {liquidity.get('price_under_5_count')}",
            f"- price under $1 rows: {liquidity.get('price_under_1_count')}",
            f"- absolute opening gap >= 20% rows: {liquidity.get('gap_abs_ge_20pct_count')}",
            f"- low dollar-volume rows: {liquidity.get('low_dollar_volume_count')}",
            "",
            "Daily OHLC files do not identify exchange trading halts or executable intraday liquidity. Rows with clinical-hold language are risk flags, not proof of exchange trading halts.",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _mean_abs_h1(frame: pd.DataFrame, column: str = "car_sector_adj_h1") -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.abs().mean())


def _mean_h1(frame: pd.DataFrame, column: str = "car_sector_adj_h1") -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _decision(
    *,
    timestamp: pd.DataFrame,
    duplicate: pd.DataFrame,
    outlier: dict[str, object],
    liquidity: pd.DataFrame,
    execution: dict[str, object],
    matched_peer: pd.DataFrame,
    event_study: pd.DataFrame,
) -> str:
    if not timestamp.empty and (timestamp["timestamp_risk_level"] == "high").any():
        return "timestamp leakage found"
    top5 = outlier.get("top_5_abs_h1_share")
    top1 = outlier.get("top_1_abs_h1_share")
    top_ticker = outlier.get("top_ticker_abs_h1_share")
    if (top5 is not None and float(top5) >= 0.50) or (top1 is not None and float(top1) >= 0.30) or (top_ticker is not None and float(top_ticker) >= 0.40):
        return "outlier-driven"

    stress = execution.get("stress", [])
    stress_100 = next((row for row in stress if float(row.get("all_in_cost_bps", -1)) == 100.0), {})
    next_open = execution.get("next_open_stress", [])
    next_open_25 = next((row for row in next_open if float(row.get("all_in_cost_bps", -1)) == 25.0), {})
    high_liquidity_risk = int((liquidity.get("liquidity_execution_risk", pd.Series(dtype=object)) == "high").sum()) if not liquidity.empty else 0
    if stress_100 and stress_100.get("mean_net_event_return") is not None and float(stress_100["mean_net_event_return"]) <= 0:
        return "execution unrealistic"
    if next_open_25 and next_open_25.get("mean_net_event_return") is not None and float(next_open_25["mean_net_event_return"]) <= 0 and high_liquidity_risk > 0:
        return "execution unrealistic"

    duplicate_high = int((duplicate.get("duplicate_risk_level", pd.Series(dtype=object)) == "high").sum()) if not duplicate.empty else 0
    medium_timestamp = int((timestamp.get("timestamp_risk_level", pd.Series(dtype=object)) == "medium").sum()) if not timestamp.empty else 0
    peer_mean = _mean_h1(matched_peer, "peer_car_sector_adj_h1")
    main_mean = _mean_h1(event_study, "car_sector_adj_h1")
    if duplicate_high or high_liquidity_risk or medium_timestamp:
        return "result weakened but still promising"
    if peer_mean is not None and main_mean is not None and abs(peer_mean) >= abs(main_mean):
        return "result weakened but still promising"
    return "result survives audit"


def write_agent_3f_report(path: str | Path, report: dict[str, object]) -> Path:
    timestamp = report.get("timestamp_summary", {}) or {}
    duplicate = report.get("duplicate_summary", {}) or {}
    outlier = report.get("outlier_summary", {}) or {}
    liquidity = report.get("liquidity_summary", {}) or {}
    execution = report.get("execution_summary", {}) or {}
    peer = report.get("matched_peer_summary", {}) or {}
    lines = [
        "# Agent 3F Biotech Leakage, Timestamp, and Outlier Audit",
        "",
        f"Decision: {report.get('decision')}.",
        "",
        "This audit tries to break the Agent 3D result. It does not change parser labels, tune thresholds, or graduate the signal.",
        "",
        "## Timestamp Audit",
        "",
        f"- rows audited: {timestamp.get('rows')}",
        f"- high-risk timestamp rows: {timestamp.get('high_risk_rows')}",
        f"- medium-risk timestamp rows: {timestamp.get('medium_risk_rows')}",
        f"- session mismatches: {timestamp.get('session_mismatch_rows')}",
        f"- reaction start before expected first tradable window: {timestamp.get('reaction_start_before_expected_rows')}",
        "",
        "## Duplicate Audit",
        "",
        f"- rows audited: {duplicate.get('rows')}",
        f"- high-risk duplicate rows: {duplicate.get('high_risk_rows')}",
        f"- source mirror rows: {duplicate.get('source_mirror_rows')}",
        f"- prior-announcement language rows: {duplicate.get('prior_announcement_language_rows')}",
        f"- conference/publication language rows: {duplicate.get('conference_publication_language_rows')}",
        "",
        "## Outliers",
        "",
        f"- top 1 absolute h1 share: {outlier.get('top_1_abs_h1_share')}",
        f"- top 3 absolute h1 share: {outlier.get('top_3_abs_h1_share')}",
        f"- top 5 absolute h1 share: {outlier.get('top_5_abs_h1_share')}",
        f"- top ticker: {outlier.get('top_ticker')} ({outlier.get('top_ticker_abs_h1_share')})",
        f"- CRL / halt / failure absolute h1 share: {outlier.get('crl_halt_failure_abs_h1_share')}",
        "",
        "## Liquidity And Execution",
        "",
        f"- events audited: {liquidity.get('rows')}",
        f"- high-risk liquidity rows: {liquidity.get('high_risk_rows')}",
        f"- medium/high liquidity rows: {liquidity.get('medium_or_high_risk_rows')}",
        f"- price under $5 rows: {liquidity.get('price_under_5_rows')}",
        f"- gap >= 20% rows: {liquidity.get('gap_abs_ge_20pct_rows')}",
        f"- close-to-close 100 bps mean net: {execution.get('close_to_close_100bps_mean_net')}",
        f"- next-open 25 bps mean net: {execution.get('next_open_25bps_mean_net')}",
        "",
        "## Matched Peer Control",
        "",
        f"- matched peer rows: {peer.get('rows')}",
        f"- main h1 mean: {peer.get('main_h1_mean')}",
        f"- matched peer h1 mean: {peer.get('matched_peer_h1_mean')}",
        f"- main h1 mean abs: {peer.get('main_h1_mean_abs')}",
        f"- matched peer h1 mean abs: {peer.get('matched_peer_h1_mean_abs')}",
        "",
        "## Interpretation",
        "",
    ]
    for item in report.get("warnings", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "Do not graduate the biotech signal from this audit. Agent 3F is a break-the-result pass; fresh-data confirmation and a deeper timestamp/execution review remain separate requirements.",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def run_biotech_catalyst_audit_pass(
    *,
    event_study_path: str | Path = "artifacts/biotech_catalyst_event_study.csv",
    review_queue_path: str | Path = "data/events/biotech_catalyst_review_queue.csv",
    source_documents_path: str | Path = "data/events/biotech_catalyst_source_documents.csv",
    strategy_trades_path: str | Path = "artifacts/biotech_catalyst_strategy_trades.csv",
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_dir: str | Path = "artifacts",
) -> dict[str, object]:
    del review_queue_path  # Reserved for future manual-audit extensions; labels are intentionally not changed here.
    out = ensure_dir(out_dir)
    event_study = _read_csv(event_study_path)

    timestamp_path = out / "biotech_catalyst_timestamp_audit.csv"
    duplicate_path = out / "biotech_catalyst_duplicate_audit.csv"
    outlier_path = out / "biotech_catalyst_outlier_audit.md"
    liquidity_path = out / "biotech_catalyst_liquidity_risk_audit.csv"
    matched_peer_path = out / "biotech_catalyst_matched_peer_audit.csv"
    execution_path = out / "biotech_catalyst_execution_stress_report.md"
    next_open_path = out / "biotech_catalyst_next_open_execution_stress.csv"
    json_path = out / "biotech_catalyst_agent_3f_report.json"
    agent_report_path = out / "biotech_catalyst_agent_3f_report.md"

    timestamp = build_timestamp_audit(
        event_study,
        source_documents=source_documents_path,
        prices_dir=prices_dir,
        out_path=timestamp_path,
    )
    duplicate = build_duplicate_audit(event_study, source_documents=source_documents_path, out_path=duplicate_path)
    outlier = build_outlier_audit(event_study, strategy_trades=strategy_trades_path, out_path=outlier_path)
    liquidity = build_liquidity_risk_audit(event_study, prices_dir=prices_dir, out_path=liquidity_path)
    matched_peer = build_matched_peer_audit(event_study, prices_dir=prices_dir, out_path=matched_peer_path)
    execution = build_execution_stress_report(
        strategy_trades_path,
        liquidity_audit=liquidity,
        timestamp_audit=timestamp,
        prices_dir=prices_dir,
        out_path=execution_path,
        next_open_out_path=next_open_path,
    )

    timestamp_summary = {
        "rows": int(len(timestamp)),
        "high_risk_rows": int((timestamp.get("timestamp_risk_level", pd.Series(dtype=object)) == "high").sum()),
        "medium_risk_rows": int((timestamp.get("timestamp_risk_level", pd.Series(dtype=object)) == "medium").sum()),
        "session_mismatch_rows": int(timestamp.get("session_mismatch", pd.Series(dtype=bool)).map(_bool_value).sum()) if not timestamp.empty else 0,
        "reaction_start_before_expected_rows": int(timestamp.get("reaction_start_before_expected", pd.Series(dtype=bool)).map(_bool_value).sum()) if not timestamp.empty else 0,
    }
    duplicate_summary = {
        "rows": int(len(duplicate)),
        "high_risk_rows": int((duplicate.get("duplicate_risk_level", pd.Series(dtype=object)) == "high").sum()),
        "source_mirror_rows": int(duplicate.get("source_mirror_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not duplicate.empty else 0,
        "prior_announcement_language_rows": int(duplicate.get("prior_announcement_language_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not duplicate.empty else 0,
        "conference_publication_language_rows": int(duplicate.get("conference_publication_language_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not duplicate.empty else 0,
    }
    liquidity_summary = {
        "rows": int(len(liquidity)),
        "high_risk_rows": int((liquidity.get("liquidity_execution_risk", pd.Series(dtype=object)) == "high").sum()),
        "medium_or_high_risk_rows": int(liquidity.get("liquidity_execution_risk", pd.Series(dtype=object)).isin(["medium", "high"]).sum()) if not liquidity.empty else 0,
        "price_under_5_rows": int(liquidity.get("risk_flags", pd.Series(dtype=object)).fillna("").astype(str).str.contains("price_under_5", regex=False).sum()) if not liquidity.empty else 0,
        "gap_abs_ge_20pct_rows": int(liquidity.get("risk_flags", pd.Series(dtype=object)).fillna("").astype(str).str.contains("gap_abs_ge_20pct", regex=False).sum()) if not liquidity.empty else 0,
    }
    main_h1_mean = _mean_h1(event_study, "car_sector_adj_h1")
    matched_peer_h1_mean = _mean_h1(matched_peer, "peer_car_sector_adj_h1")
    peer_summary = {
        "rows": int(len(matched_peer)),
        "main_h1_mean": main_h1_mean,
        "matched_peer_h1_mean": matched_peer_h1_mean,
        "main_h1_mean_abs": _mean_abs_h1(event_study, "car_sector_adj_h1"),
        "matched_peer_h1_mean_abs": _mean_abs_h1(matched_peer, "peer_car_sector_adj_h1"),
    }
    stress_100 = next((row for row in execution.get("stress", []) if float(row.get("all_in_cost_bps", -1)) == 100.0), {})
    next_open_25 = next((row for row in execution.get("next_open_stress", []) if float(row.get("all_in_cost_bps", -1)) == 25.0), {})
    execution_summary = {
        "close_to_close_100bps_mean_net": stress_100.get("mean_net_event_return"),
        "next_open_25bps_mean_net": next_open_25.get("mean_net_event_return"),
        "next_open_trades": execution.get("next_open_trades"),
    }
    decision = _decision(
        timestamp=timestamp,
        duplicate=duplicate,
        outlier=outlier,
        liquidity=liquidity,
        execution=execution,
        matched_peer=matched_peer,
        event_study=event_study,
    )
    report = {
        "agent": "3F",
        "domain": "biotech_fda_clinical_catalyst",
        "decision": decision,
        "timestamp_audit_path": str(timestamp_path),
        "duplicate_audit_path": str(duplicate_path),
        "outlier_audit_path": str(outlier_path),
        "liquidity_risk_audit_path": str(liquidity_path),
        "matched_peer_audit_path": str(matched_peer_path),
        "execution_stress_report_path": str(execution_path),
        "next_open_execution_stress_path": str(next_open_path),
        "timestamp_summary": timestamp_summary,
        "duplicate_summary": duplicate_summary,
        "outlier_summary": {
            key: value
            for key, value in outlier.items()
            if key
            in {
                "event_rows",
                "top_1_abs_h1_share",
                "top_3_abs_h1_share",
                "top_5_abs_h1_share",
                "top_ticker_abs_h1_share",
                "top_ticker",
                "crl_halt_failure_abs_h1_share",
                "crl_halt_failure_mean_h1",
            }
        },
        "liquidity_summary": liquidity_summary,
        "execution_summary": execution_summary,
        "matched_peer_summary": peer_summary,
        "warnings": [
            "Daily OHLC cannot prove intraday executable prices or exchange trading halt status.",
            "SEC exhibit acceptance is used as the best available press-release timestamp when a separate wire timestamp is absent.",
            "Matched peer control is approximate: market-cap/stage/XBI-beta matching uses available local event and price data, not a hand-curated mechanism peer basket.",
            "This is not a graduated signal.",
        ],
    }
    _write_json(json_path, report)
    write_agent_3f_report(agent_report_path, report)
    return report
