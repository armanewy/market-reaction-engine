from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS, REQUIRED_EVENT_COLUMNS, load_events
from .paths import ensure_parent

REVIEW_COLUMNS = [
    "review_status",
    "label_quality",
    "evidence_status",
    "reviewer",
    "reviewed_at",
    "review_notes",
    "drop_reason",
]

REVIEW_DEFAULTS = {
    "review_status": "needs_review",
    "label_quality": "unreviewed",
    "evidence_status": "unknown",
    "reviewer": "",
    "reviewed_at": "",
    "review_notes": "",
    "drop_reason": "",
}


@dataclass
class ReviewDiagnostics:
    rows_total: int = 0
    rows_with_evidence: int = 0
    rows_missing_evidence: int = 0
    rows_auto_accepted: int = 0
    issues: dict[str, int] = field(default_factory=dict)

    def add_issue(self, issue: str, n: int = 1) -> None:
        self.issues[issue] = self.issues.get(issue, 0) + int(n)

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_str(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip()


def _fact_counts_by_event(facts: pd.DataFrame) -> pd.DataFrame:
    if facts.empty or "event_id" not in facts.columns:
        return pd.DataFrame(columns=["event_id", "extracted_fact_count", "extracted_fact_names", "evidence_text_count", "mean_fact_confidence"])
    tmp = facts.copy()
    tmp["event_id"] = tmp["event_id"].astype(str)
    if "confidence" in tmp.columns:
        tmp["confidence"] = pd.to_numeric(tmp["confidence"], errors="coerce")
    else:
        tmp["confidence"] = np.nan
    if "fact_name" not in tmp.columns:
        tmp["fact_name"] = ""
    if "evidence_text" not in tmp.columns:
        tmp["evidence_text"] = ""
    grouped = tmp.groupby("event_id", dropna=False)
    out = grouped.agg(
        extracted_fact_count=("fact_name", "size"),
        evidence_text_count=("evidence_text", lambda s: int((s.fillna("").astype(str).str.strip() != "").sum())),
        mean_fact_confidence=("confidence", "mean"),
    ).reset_index()
    names = grouped["fact_name"].apply(lambda s: ",".join(sorted({v for v in s.fillna("").astype(str) if v}))).reset_index(name="extracted_fact_names")
    out = out.merge(names, on="event_id", how="left")
    return out


def make_review_queue(
    events_path: str | Path,
    out_path: str | Path,
    *,
    facts_path: str | Path | None = None,
    auto_accept_min_confidence: float | None = None,
    auto_accept_min_facts: int = 1,
) -> tuple[pd.DataFrame, ReviewDiagnostics]:
    """Create a human-review queue from event candidates and optional extracted facts.

    This intentionally does not infer materiality or correctness from returns. It only
    adds review metadata and evidence coverage fields so a human can accept, edit,
    or reject rows before they enter a trusted corpus.
    """
    events = load_events(events_path)
    diag = ReviewDiagnostics(rows_total=int(len(events)))
    out = events.copy()
    for col, default in REVIEW_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default
        else:
            out[col] = out[col].fillna(default).replace({"nan": default})
    if facts_path:
        facts = pd.read_csv(facts_path)
        counts = _fact_counts_by_event(facts)
        out = out.merge(counts, on="event_id", how="left")
        out["extracted_fact_count"] = pd.to_numeric(out["extracted_fact_count"], errors="coerce").fillna(0).astype(int)
        out["evidence_text_count"] = pd.to_numeric(out["evidence_text_count"], errors="coerce").fillna(0).astype(int)
        out["mean_fact_confidence"] = pd.to_numeric(out["mean_fact_confidence"], errors="coerce")
        out["extracted_fact_names"] = out["extracted_fact_names"].fillna("")
        has_evidence = out["evidence_text_count"] > 0
        out.loc[has_evidence, "evidence_status"] = "has_evidence"
        out.loc[~has_evidence, "evidence_status"] = "missing_evidence"
        diag.rows_with_evidence = int(has_evidence.sum())
        diag.rows_missing_evidence = int((~has_evidence).sum())
        if auto_accept_min_confidence is not None:
            conf = pd.to_numeric(out["mean_fact_confidence"], errors="coerce").fillna(0.0)
            fact_count = pd.to_numeric(out["extracted_fact_count"], errors="coerce").fillna(0).astype(int)
            mask = has_evidence & (fact_count >= int(auto_accept_min_facts)) & (conf >= float(auto_accept_min_confidence))
            out.loc[mask, "review_status"] = "reviewed"
            out.loc[mask, "label_quality"] = "auto_reviewed_candidate"
            out.loc[mask, "review_notes"] = out.loc[mask, "review_notes"].astype(str).where(
                out.loc[mask, "review_notes"].astype(str).str.strip() != "",
                "Auto-accepted by threshold; verify manually before serious research.",
            )
            diag.rows_auto_accepted = int(mask.sum())
    else:
        out["extracted_fact_count"] = 0
        out["evidence_text_count"] = 0
        out["mean_fact_confidence"] = np.nan
        out["extracted_fact_names"] = ""
        out["evidence_status"] = "not_checked"
        diag.add_issue("facts_path_not_supplied")

    # Useful triage hints.  These are not labels.
    out["review_priority"] = "normal"
    materiality = pd.to_numeric(out.get("materiality", 0.5), errors="coerce").fillna(0.5)
    out.loc[materiality >= 0.75, "review_priority"] = "high_materiality"
    out.loc[out["evidence_status"].isin(["missing_evidence", "not_checked"]), "review_priority"] = "evidence_needed"

    preferred = REQUIRED_EVENT_COLUMNS + list(OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS.keys()) + REVIEW_COLUMNS + [
        "review_priority",
        "extracted_fact_count",
        "evidence_text_count",
        "mean_fact_confidence",
        "extracted_fact_names",
    ]
    ordered = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
    out = out[ordered]
    p = ensure_parent(out_path)
    out.to_csv(p, index=False)
    return out, diag


def reviewed_rows(events: str | Path | pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    if "review_status" not in df.columns:
        return df.iloc[0:0].copy()
    status = df["review_status"].fillna("").astype(str).str.lower().str.strip()
    drop_reason = df.get("drop_reason", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    return df[(status.isin(["reviewed", "accepted", "approved"])) & (drop_reason == "")].copy()
