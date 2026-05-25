from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


def _norm(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _safe_id(value: object, default: str = "chain") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", _norm(value, default=default)).strip("_")
    return cleaned[:180] or default


def _issuer_value(row: pd.Series, issuer_col: str) -> str:
    if issuer_col in row.index:
        return _norm(row.get(issuer_col))
    return _norm(row.get("issuer_id")) or _norm(row.get("ticker"))


def build_amendment_chains(
    filings_df,
    events_df=None,
    *,
    issuer_col: str = "cik",
    accession_col: str = "accession",
    form_col: str = "form",
    accepted_col: str = "accepted_at",
    event_type_col: str = "event_type",
) -> pd.DataFrame:
    filings = pd.read_csv(filings_df) if isinstance(filings_df, (str, Path)) else filings_df.copy()
    events = pd.read_csv(events_df) if isinstance(events_df, (str, Path)) else events_df.copy() if events_df is not None else None
    if filings.empty:
        return pd.DataFrame(
            columns=[
                "amendment_chain_id",
                "issuer_id_or_cik",
                "original_accession",
                "amendment_accession",
                "original_accepted_at",
                "amendment_accepted_at",
                "days_after_original",
                "form",
                "event_type",
                "link_confidence",
                "link_method",
                "notes",
            ]
        )

    out_rows: list[dict] = []
    work = filings.copy()
    work["_accepted"] = pd.to_datetime(work.get(accepted_col, work.get("filing_date", "")), errors="coerce")
    work["_issuer"] = work.apply(lambda row: _issuer_value(row, issuer_col), axis=1)
    if events is not None and "accession" in events.columns and event_type_col in events.columns:
        event_types = events[["accession", event_type_col]].dropna().drop_duplicates()
        work = work.merge(event_types, left_on=accession_col, right_on="accession", how="left", suffixes=("", "_event"))
    if event_type_col not in work.columns:
        work[event_type_col] = ""

    originals = work[~work[form_col].fillna("").astype(str).str.upper().str.endswith("/A")].copy()
    amendments = work[work[form_col].fillna("").astype(str).str.upper().str.endswith("/A")].copy()
    for _, amendment in amendments.sort_values("_accepted").iterrows():
        issuer = amendment["_issuer"]
        prior = originals[(originals["_issuer"] == issuer) & (originals["_accepted"] < amendment["_accepted"])].copy()
        item_numbers = _norm(amendment.get("item_numbers"))
        if item_numbers and "item_numbers" in prior.columns:
            matching_items = prior[prior["item_numbers"].fillna("").astype(str).str.contains(re.escape(item_numbers), case=False, regex=True)]
            if not matching_items.empty:
                prior = matching_items
        event_type = _norm(amendment.get(event_type_col))
        if event_type and event_type_col in prior.columns:
            matching_event_type = prior[prior[event_type_col].fillna("").astype(str) == event_type]
            if not matching_event_type.empty:
                prior = matching_event_type
        if prior.empty:
            out_rows.append(
                {
                    "amendment_chain_id": _safe_id(f"unmatched_{issuer}_{amendment.get(accession_col)}"),
                    "issuer_id_or_cik": issuer,
                    "original_accession": "",
                    "amendment_accession": _norm(amendment.get(accession_col)),
                    "original_accepted_at": "",
                    "amendment_accepted_at": _norm(amendment.get(accepted_col)),
                    "days_after_original": "",
                    "form": _norm(amendment.get(form_col)),
                    "event_type": event_type,
                    "link_confidence": 0.0,
                    "link_method": "unmatched_amendment",
                    "notes": "No prior matching original filing found.",
                }
            )
            continue
        original = prior.sort_values("_accepted").iloc[-1]
        days = (pd.Timestamp(amendment["_accepted"]) - pd.Timestamp(original["_accepted"])).total_seconds() / 86400
        confidence = 0.85
        method = "same_issuer_closest_prior_original"
        if item_numbers:
            confidence = 0.92
            method += "_same_item"
        out_rows.append(
            {
                "amendment_chain_id": _safe_id(f"{issuer}_{original.get(accession_col)}_{amendment.get(accession_col)}"),
                "issuer_id_or_cik": issuer,
                "original_accession": _norm(original.get(accession_col)),
                "amendment_accession": _norm(amendment.get(accession_col)),
                "original_accepted_at": _norm(original.get(accepted_col)),
                "amendment_accepted_at": _norm(amendment.get(accepted_col)),
                "days_after_original": round(days, 4),
                "form": _norm(amendment.get(form_col)),
                "event_type": event_type,
                "link_confidence": confidence,
                "link_method": method,
                "notes": "",
            }
        )
    return pd.DataFrame(out_rows)


def add_amendment_flags(events_df, amendment_chains_df) -> pd.DataFrame:
    events = pd.read_csv(events_df) if isinstance(events_df, (str, Path)) else events_df.copy()
    chains = pd.read_csv(amendment_chains_df) if isinstance(amendment_chains_df, (str, Path)) else amendment_chains_df.copy()
    out = events.copy()
    out["amended_later"] = False
    out["amendment_count"] = 0
    out["first_amendment_days"] = pd.Series([pd.NA] * len(out), index=out.index, dtype="Float64")
    if out.empty or chains.empty or "accession" not in out.columns:
        return out
    linked = chains[chains["original_accession"].fillna("").astype(str) != ""].copy()
    for accession, group in linked.groupby("original_accession"):
        mask = out["accession"].fillna("").astype(str) == str(accession)
        out.loc[mask, "amended_later"] = True
        out.loc[mask, "amendment_count"] = int(len(group))
        days = pd.to_numeric(group["days_after_original"], errors="coerce").dropna()
        out.loc[mask, "first_amendment_days"] = pd.NA if days.empty else float(days.min())
    return out
