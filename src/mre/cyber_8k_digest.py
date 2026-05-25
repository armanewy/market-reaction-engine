from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import ensure_parent


NOTABLE_FIELDS = [
    "operational_disruption_mentioned",
    "customer_data_exposure_mentioned",
    "third_party_vendor_mentioned",
    "impact_unknown_or_not_determined",
    "no_material_impact_language",
    "reasonably_likely_material_impact_language",
]


def _load(path) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        return path.copy()
    return pd.read_csv(path)


def _norm(value: object, default: str = "") -> str:
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value if value is not None else "").strip()
    return default if text.lower() in {"nan", "none", "null"} else text


def _truth(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _filter_events(events: pd.DataFrame, start_date=None, end_date=None) -> pd.DataFrame:
    if events.empty or "event_time" not in events.columns:
        return events.copy()
    out = events.copy()
    event_dates = pd.to_datetime(out["event_time"], errors="coerce")
    if start_date:
        out = out[event_dates >= pd.to_datetime(start_date)].copy()
        event_dates = pd.to_datetime(out["event_time"], errors="coerce")
    if end_date:
        out = out[event_dates <= pd.to_datetime(end_date)].copy()
    return out


def build_cyber_8k_digest(
    events_csv,
    claims_csv,
    evidence_spans_csv,
    *,
    start_date=None,
    end_date=None,
    out_path=None,
    title: str = "Cyber 8-K Watch Digest",
) -> str:
    events_all = _load(events_csv)
    claims = _load(claims_csv)
    evidence = _load(evidence_spans_csv)
    events = _filter_events(events_all, start_date, end_date)
    event_ids = set(events.get("event_id", pd.Series(dtype=str)).fillna("").astype(str))
    claims = claims[claims.get("event_id", pd.Series(dtype=str)).fillna("").astype(str).isin(event_ids)] if not claims.empty else claims
    evidence = evidence[evidence.get("claim_id", pd.Series(dtype=str)).fillna("").astype(str).isin(set(claims.get("claim_id", pd.Series(dtype=str)).fillna("").astype(str)))] if not evidence.empty else evidence

    companies = set(events.get("ticker", pd.Series(dtype=str)).fillna("").astype(str)) - {""}
    reviewed = int(claims.get("review_status", pd.Series(dtype=str)).fillna("").astype(str).str.lower().isin({"reviewed", "approved"}).sum()) if not claims.empty else 0
    amendments = int(events.get("amendment_flag", events.get("amended_later", pd.Series(False, index=events.index))).map(_truth).sum()) if not events.empty else 0
    lines = [
        f"# {title}",
        "",
        "## Summary",
        "",
        f"- new events: {len(events)}",
        f"- companies: {len(companies)}",
        f"- amendments: {amendments}",
        f"- reviewed claims: {reviewed}",
        f"- unreviewed claims: {max(len(claims) - reviewed, 0)}",
        "",
        "## Notable Disclosures",
        "",
    ]
    if events.empty:
        lines.append("No Cyber 8-K events found for this period.")
    else:
        for field in NOTABLE_FIELDS:
            ids = set()
            if field in events.columns:
                ids = set(events[events[field].map(_truth)]["event_id"].astype(str))
            if not claims.empty and "field_name" in claims.columns:
                ids |= set(claims[claims["field_name"].astype(str) == field]["event_id"].astype(str))
            for _, event in events[events["event_id"].astype(str).isin(ids)].iterrows():
                lines.append(f"- **{_norm(event.get('ticker'), 'UNKNOWN')}** `{field}`: {_norm(event.get('summary'), _norm(event.get('event_id')))}")
    lines.extend(["", "## New Amendments", ""])
    amendment_events = events[events.get("amendment_flag", events.get("amended_later", pd.Series(False, index=events.index))).map(_truth)] if not events.empty else pd.DataFrame()
    if amendment_events.empty:
        lines.append("No amendments found for this period.")
    else:
        for _, event in amendment_events.iterrows():
            lines.append(f"- **{_norm(event.get('ticker'), 'UNKNOWN')}** {_norm(event.get('event_time'))}: {_norm(event.get('summary'))}")
    lines.extend(["", "## Evidence-Backed Snippets", ""])
    if evidence.empty:
        lines.append("No evidence spans supplied.")
    else:
        merged = evidence.merge(claims[["claim_id", "event_id", "field_name"]], on="claim_id", how="left") if not claims.empty and "claim_id" in claims.columns else evidence
        for _, row in merged.head(20).iterrows():
            source = _norm(row.get("source_url"))
            suffix = f" ([source]({source}))" if source else ""
            lines.append(f"- `{_norm(row.get('field_name'))}`: {_norm(row.get('evidence_text'))[:280]}{suffix}")
    digest = "\n".join(lines).rstrip() + "\n"
    if out_path is not None:
        out = ensure_parent(out_path)
        out.write_text(digest, encoding="utf-8")
    return digest
