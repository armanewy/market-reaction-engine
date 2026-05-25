from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


KNOWN_RELEASE_SESSIONS = {"before_open", "intraday", "after_close"}
OK_TIMESTAMP_AUDIT_STATUSES = {"clear", "ok", "pass", "passed", "audited", "timestamp_audited"}
BAD_TIMESTAMP_AUDIT_STATUSES = {"fail", "failed", "needs_timestamp_review", "rejected"}
LOW_CONFIDENCE_VALUES = {"low", "weak", "estimated", "manual_review_required", "unknown"}
BAD_SOURCE_TYPES = {"market_data", "price_reaction", "post_event_price", "post_price"}


def _get(row: Mapping[str, Any] | pd.Series, key: str, default: object = "") -> object:
    try:
        return row.get(key, default)
    except AttributeError:
        return default


def _norm(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return "" if text in {"nan", "none", "null"} else text


def classify_release_session_readiness(row: Mapping[str, Any] | pd.Series) -> dict[str, object]:
    """Classify whether a row is timestamp-ready for realistic execution analysis.

    This is intentionally separate from event-study measurement.  A row with an
    unknown session can still be useful for explanatory close-to-close analysis,
    but it should be visibly excluded from execution-sensitive modeling or
    tradability claims.
    """
    issues: list[str] = []
    fail = False
    explanatory_only = False

    release_session = _norm(_get(row, "release_session"))
    if not release_session:
        issues.append("missing_release_session")
        fail = True
        explanatory_only = True
    elif release_session == "unknown":
        issues.append("unknown_release_session")
        fail = True
        explanatory_only = True
    elif release_session not in KNOWN_RELEASE_SESSIONS:
        issues.append(f"invalid_release_session:{release_session}")
        fail = True
        explanatory_only = True

    audit_status = _norm(_get(row, "timestamp_audit_status"))
    if audit_status:
        if audit_status in BAD_TIMESTAMP_AUDIT_STATUSES or audit_status.startswith("needs_"):
            issues.append(f"timestamp_audit_not_clear:{audit_status}")
            fail = True
            explanatory_only = True
        elif audit_status not in OK_TIMESTAMP_AUDIT_STATUSES:
            issues.append(f"timestamp_audit_uncertain:{audit_status}")

    release_time_status = _norm(_get(row, "release_time_status"))
    if release_time_status in {"missing", "unknown", "manual_review_required"}:
        issues.append(f"release_time_status_uncertain:{release_time_status}")

    confidence = _norm(_get(row, "release_time_confidence"))
    if confidence in LOW_CONFIDENCE_VALUES:
        issues.append(f"release_time_confidence_low:{confidence}")

    source_type = _norm(_get(row, "release_time_source_type"))
    if source_type in BAD_SOURCE_TYPES:
        issues.append(f"release_time_source_not_point_in_time:{source_type}")
        fail = True
        explanatory_only = True

    first_entry = _norm(_get(row, "first_realistic_entry"))
    if first_entry in {"none", "not_tradable", "not-tradable", "explanation_only", "explanatory_only"}:
        issues.append(f"first_realistic_entry_not_tradable:{first_entry}")
        fail = True
        explanatory_only = True

    status = "fail" if fail else "warning" if issues else "ok"
    return {
        "timestamp_readiness_status": status,
        "timestamp_readiness_issues": ";".join(issues),
        "explanatory_only": bool(explanatory_only),
    }


def classify_release_session_readiness_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rows = [classify_release_session_readiness(row) for _, row in out.iterrows()]
    classified = pd.DataFrame(rows, index=out.index)
    for col in classified.columns:
        out[col] = classified[col]
    return out
