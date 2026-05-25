from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from .paths import ensure_dir


BOOLEAN_FIELDS = [
    "ransomware_mentioned",
    "customer_data_exposure_mentioned",
    "operational_disruption_mentioned",
    "third_party_vendor_mentioned",
    "no_material_impact_language",
    "impact_unknown_or_not_determined",
    "reasonably_likely_material_impact_language",
]


def _load(path) -> pd.DataFrame:
    return pd.read_csv(path)


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(col): _clean(row.get(col)) for col in df.columns} for _, row in df.iterrows()]


def _write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _truth(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def export_cyber_8k_api(
    events_csv,
    claims_csv,
    evidence_spans_csv,
    out_dir,
    *,
    include_evidence: bool = True,
) -> dict:
    events = _load(events_csv)
    claims = _load(claims_csv)
    evidence = _load(evidence_spans_csv)
    out = ensure_dir(out_dir)

    evidence_by_claim = {}
    if not evidence.empty and "claim_id" in evidence.columns:
        for _, span in evidence.iterrows():
            item = {str(col): _clean(span.get(col)) for col in evidence.columns}
            if not include_evidence:
                item.pop("evidence_text", None)
            evidence_by_claim.setdefault(str(span.get("claim_id")), []).append(item)

    event_records = []
    compact_records = []
    for _, event in events.iterrows():
        event_id = str(event.get("event_id"))
        event_claims = claims[claims["event_id"].astype(str) == event_id] if not claims.empty and "event_id" in claims.columns else pd.DataFrame()
        nested_claims = []
        for _, claim in event_claims.iterrows():
            item = {str(col): _clean(claim.get(col)) for col in claims.columns}
            item["evidence"] = evidence_by_claim.get(str(claim.get("claim_id")), [])
            nested_claims.append(item)
        event_item = {str(col): _clean(event.get(col)) for col in events.columns}
        event_item["claims"] = nested_claims
        event_records.append(event_item)
        compact_records.append(
            {
                "event_id": _clean(event.get("event_id")),
                "ticker": _clean(event.get("ticker")),
                "cik": _clean(event.get("cik")),
                "company_name": _clean(event.get("company_name")),
                "event_time": _clean(event.get("event_time")),
                "summary": _clean(event.get("summary")),
                "n_claims": int(len(nested_claims)),
                "review_status": _clean(event.get("event_review_status")),
            }
        )

    companies = []
    if not events.empty:
        key_cols = [col for col in ["ticker", "cik", "company_name"] if col in events.columns]
        group_key = "ticker" if "ticker" in events.columns else "cik" if "cik" in events.columns else key_cols[0] if key_cols else "event_id"
        for key, group in events.groupby(group_key, dropna=False):
            companies.append(
                {
                    group_key: _clean(key),
                    "ticker": _clean(group.iloc[0].get("ticker")),
                    "cik": _clean(group.iloc[0].get("cik")),
                    "company_name": _clean(group.iloc[0].get("company_name")),
                    "event_count": int(len(group)),
                    "event_ids": sorted(group["event_id"].fillna("").astype(str).tolist()) if "event_id" in group.columns else [],
                }
            )

    field_rows = []
    for field in BOOLEAN_FIELDS:
        if field in events.columns:
            count = int(events[field].map(_truth).sum())
        elif not claims.empty and "field_name" in claims.columns:
            count = int(claims[claims["field_name"].astype(str) == field]["event_id"].nunique())
        else:
            count = 0
        field_rows.append({"field_name": field, "count": count, "rate": float(count / len(events)) if len(events) else 0.0})

    files = {
        "events": out / "events.json",
        "claims": out / "claims.json",
        "evidence_spans": out / "evidence_spans.json",
        "events_compact": out / "events_compact.json",
        "companies": out / "companies.json",
        "fields_summary": out / "fields_summary.json",
    }
    _write(files["events"], event_records)
    _write(files["claims"], _records(claims))
    _write(files["evidence_spans"], _records(evidence) if include_evidence else [{k: v for k, v in record.items() if k != "evidence_text"} for record in _records(evidence)])
    _write(files["events_compact"], compact_records)
    _write(files["companies"], companies)
    _write(files["fields_summary"], field_rows)
    return {key: str(value) for key, value in files.items()}
