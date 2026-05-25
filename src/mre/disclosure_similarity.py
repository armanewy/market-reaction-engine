from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


BOOLEAN_FIELDS = [
    "ransomware_mentioned",
    "customer_data_exposure_mentioned",
    "operational_disruption_mentioned",
    "third_party_vendor_mentioned",
    "no_material_impact_language",
    "impact_unknown_or_not_determined",
]


def _load(value) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.read_csv(value)


def _norm(value: object) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value if value is not None else "").strip()


def build_event_text(events_df, claims_df, evidence_df) -> pd.DataFrame:
    events = _load(events_df)
    claims = _load(claims_df)
    evidence = _load(evidence_df)
    evidence_by_claim = {}
    if not evidence.empty and "claim_id" in evidence.columns:
        evidence_by_claim = evidence.groupby("claim_id")["evidence_text"].apply(lambda s: " ".join(_norm(v) for v in s if _norm(v))).to_dict()
    rows = []
    for _, event in events.iterrows():
        event_id = _norm(event.get("event_id"))
        parts = [_norm(event.get("summary"))]
        event_claims = claims[claims["event_id"].astype(str) == event_id] if not claims.empty and "event_id" in claims.columns else pd.DataFrame()
        for _, claim in event_claims.iterrows():
            parts.append(f"{_norm(claim.get('field_name'))}: {_norm(claim.get('value'))}")
            evidence_text = evidence_by_claim.get(_norm(claim.get("claim_id")))
            if evidence_text:
                parts.append(evidence_text)
        rows.append({"event_id": event_id, "text": " ".join(p for p in parts if p)})
    return pd.DataFrame(rows)


def find_similar_events(
    events_df,
    claims_df,
    evidence_df,
    event_id,
    *,
    k: int = 10,
    exclude_same_issuer: bool = True,
    sector_col: str = "sector",
) -> pd.DataFrame:
    events = _load(events_df)
    claims = _load(claims_df)
    evidence = _load(evidence_df)
    text_frame = build_event_text(events, claims, evidence)
    if text_frame.empty or str(event_id) not in set(text_frame["event_id"].astype(str)) or len(text_frame) < 2:
        return pd.DataFrame(columns=["similarity", "event_id", "ticker", "cik", "company_name", "event_time", "summary", "top_matching_fields", "evidence_preview", "amended_later"])
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(text_frame["text"].fillna(""))
    target_idx = text_frame.index[text_frame["event_id"].astype(str) == str(event_id)][0]
    scores = cosine_similarity(matrix[target_idx], matrix).ravel()
    target_event = events[events["event_id"].astype(str) == str(event_id)].iloc[0]
    target_issuer = _norm(target_event.get("ticker")) or _norm(target_event.get("cik"))
    rows = []
    for idx, score in enumerate(scores):
        candidate_id = text_frame.iloc[idx]["event_id"]
        if str(candidate_id) == str(event_id):
            continue
        event = events[events["event_id"].astype(str) == str(candidate_id)].iloc[0]
        candidate_issuer = _norm(event.get("ticker")) or _norm(event.get("cik"))
        if exclude_same_issuer and target_issuer and candidate_issuer == target_issuer:
            continue
        candidate_claims = claims[claims["event_id"].astype(str) == str(candidate_id)] if not claims.empty and "event_id" in claims.columns else pd.DataFrame()
        fields = ";".join(candidate_claims.get("field_name", pd.Series(dtype=str)).fillna("").astype(str).head(5))
        claim_ids = set(candidate_claims.get("claim_id", pd.Series(dtype=str)).fillna("").astype(str))
        snippets = evidence[evidence.get("claim_id", pd.Series(dtype=str)).fillna("").astype(str).isin(claim_ids)] if not evidence.empty and "claim_id" in evidence.columns else pd.DataFrame()
        preview = _norm(snippets.iloc[0].get("evidence_text"))[:240] if not snippets.empty else ""
        rows.append(
            {
                "similarity": float(score),
                "event_id": candidate_id,
                "ticker": _norm(event.get("ticker")),
                "cik": _norm(event.get("cik")),
                "company_name": _norm(event.get("company_name")),
                "event_time": _norm(event.get("event_time")),
                "summary": _norm(event.get("summary")),
                "top_matching_fields": fields,
                "evidence_preview": preview,
                "amended_later": bool(event.get("amended_later", False)),
                sector_col: _norm(event.get(sector_col)),
            }
        )
    return pd.DataFrame(rows).sort_values("similarity", ascending=False).head(k).reset_index(drop=True) if rows else pd.DataFrame()


def peer_field_benchmark(events_df, claims_df, *, group_col: str = "sector") -> pd.DataFrame:
    events = _load(events_df)
    claims = _load(claims_df)
    if events.empty:
        return pd.DataFrame()
    rows = []
    for group_value, group in events.groupby(group_col if group_col in events.columns else lambda _: "all"):
        event_ids = set(group["event_id"].astype(str))
        group_claims = claims[claims["event_id"].astype(str).isin(event_ids)] if not claims.empty and "event_id" in claims.columns else pd.DataFrame()
        row = {group_col: group_value, "n_events": int(len(group))}
        for field in BOOLEAN_FIELDS:
            matched_events = set(group_claims[group_claims.get("field_name", pd.Series(dtype=str)).astype(str) == field]["event_id"].astype(str)) if not group_claims.empty else set()
            row[f"{field}_count"] = int(len(matched_events))
            row[f"{field}_rate"] = float(len(matched_events) / len(group)) if len(group) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)
