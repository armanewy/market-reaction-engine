from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


REVIEWED_STATUSES = {"reviewed", "curated", "approved"}
REJECTED_STATUSES = {"rejected", "drop", "dropped"}
MODEL_LABEL_QUALITIES = {"high", "medium", "reviewed", "curated", "approved"}
EVIDENCE_STATUSES = {"verified", "source_backed", "evidence_backed", "has_evidence"}
KNOWN_RELEASE_SESSIONS = {"before_open", "intraday", "after_close"}
OK_DUPLICATE_STATUSES = {"", "primary", "unique", "deduped", "deduplicated", "not_duplicate", "clear", "ok"}
OK_TIMESTAMP_AUDIT_STATUSES = {"clear", "ok", "pass", "passed", "audited", "timestamp_audited"}
BAD_EXECUTION_CLASSES = {"", "unknown", "unclassified", "explanation-only", "explanatory-only", "not-tradable"}


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    value: Any
    threshold_or_expected: Any
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PromotionReport:
    decision: str
    checks: list[GateCheck]
    failed_gates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "checks": [check.to_dict() for check in self.checks],
            "failed_gates": list(self.failed_gates),
            "warnings": list(self.warnings),
            "summary": dict(self.summary),
        }


def _norm(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return "" if text in {"nan", "none", "null"} else text


def _text_series(df: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column in df.columns:
        return df[column].map(_norm)
    return pd.Series([default] * len(df), index=df.index, dtype="object")


def _nonempty(series: pd.Series) -> pd.Series:
    return ~series.map(_norm).isin({"", "unknown"})


def _truthy(series: pd.Series) -> pd.Series:
    return series.map(_norm).isin({"1", "true", "yes", "y", "eligible", "ok", "pass", "passed"})


def _has_evidence(df: pd.DataFrame) -> pd.Series:
    evidence = _text_series(df, "evidence_status")
    source_doc_ids = _text_series(df, "source_doc_ids")
    return evidence.isin(EVIDENCE_STATUSES) | _nonempty(source_doc_ids)


def _duplicate_ok(series: pd.Series) -> pd.Series:
    values = series.map(_norm)
    return values.isin(OK_DUPLICATE_STATUSES)


def _timestamp_ok(series: pd.Series) -> pd.Series:
    values = series.map(_norm)
    return values.isin(OK_TIMESTAMP_AUDIT_STATUSES)


def _execution_ok(series: pd.Series) -> pd.Series:
    values = series.map(_norm)
    return ~values.isin(BAD_EXECUTION_CLASSES)


def _likely_oos_predictions(df: pd.DataFrame, eligible_count: int, min_model_eligible_rows: int, min_likely_oos_predictions: int) -> tuple[int, str]:
    if "likely_oos_prediction" in df.columns:
        return int(_truthy(df["likely_oos_prediction"]).sum()), "counted from likely_oos_prediction"
    train_reserve = max(0, int(min_model_eligible_rows) - int(min_likely_oos_predictions))
    return max(0, int(eligible_count) - train_reserve), f"estimated after reserving {train_reserve} rows for initial training"


def evaluate_model_readiness(
    events_df: pd.DataFrame,
    *,
    min_reviewed_rows: int = 80,
    min_model_eligible_rows: int = 60,
    min_likely_oos_predictions: int = 30,
    require_known_release_session: bool = True,
    require_evidence: bool = True,
) -> dict[str, Any]:
    """Evaluate whether a source-grounded corpus is ready for modeling.

    The function is intentionally pure: callers can run it on candidate corpora,
    review queues, or event-study frames without changing existing validation
    behavior.  Rows are model-eligible only when they are reviewed, source
    grounded, timestamp usable, not duplicates, and otherwise marked usable by
    the columns present in the frame.
    """
    df = events_df.copy()
    checks: list[GateCheck] = []
    warnings: list[str] = []

    if df.empty:
        report = PromotionReport(
            decision="reject_modeling",
            checks=[
                GateCheck(
                    name="non_empty_corpus",
                    passed=False,
                    value=0,
                    threshold_or_expected="> 0",
                    notes="No rows were provided.",
                )
            ],
            failed_gates=["non_empty_corpus"],
            summary={"n_rows": 0},
        )
        return report.to_dict()

    review = _text_series(df, "review_status")
    label_quality = _text_series(df, "label_quality")
    release_session = _text_series(df, "release_session")
    event_status = _text_series(df, "event_status", default="ok")
    corpus_status = _text_series(df, "corpus_validation_status", default="ok")

    event_ok = event_status.eq("ok")
    usable_mask = ~review.isin(REJECTED_STATUSES) & event_ok
    reviewed_mask = ~review.isin(REJECTED_STATUSES) & review.isin(REVIEWED_STATUSES)
    label_ok = label_quality.isin(MODEL_LABEL_QUALITIES)
    evidence_ok = _has_evidence(df)
    release_ok = release_session.isin(KNOWN_RELEASE_SESSIONS)

    duplicate_ok = pd.Series([True] * len(df), index=df.index)
    if "duplicate_status" in df.columns:
        duplicate_ok = _duplicate_ok(df["duplicate_status"])
    else:
        warnings.append("duplicate_status column is absent; duplicate-event risk was not audited.")

    timestamp_ok = pd.Series([True] * len(df), index=df.index)
    if "timestamp_audit_status" in df.columns:
        timestamp_ok = _timestamp_ok(df["timestamp_audit_status"])
    else:
        warnings.append("timestamp_audit_status column is absent; timestamp audit state is unknown.")

    execution_ok = pd.Series([True] * len(df), index=df.index)
    if "execution_survivability_class" in df.columns:
        execution_ok = _execution_ok(df["execution_survivability_class"])
    else:
        warnings.append("execution_survivability_class column is absent; realistic execution suitability was not classified.")

    corpus_ok = ~corpus_status.isin({"fail", "failed"})
    eligible = reviewed_mask & event_ok & label_ok & corpus_ok & duplicate_ok & timestamp_ok & execution_ok
    if require_evidence:
        eligible &= evidence_ok
    if require_known_release_session:
        eligible &= release_ok

    n_rows = int(len(df))
    n_usable = int(usable_mask.sum())
    n_reviewed = int(reviewed_mask.sum())
    n_model_eligible = int(eligible.sum())
    n_likely_oos, oos_notes = _likely_oos_predictions(df.loc[eligible], n_model_eligible, min_model_eligible_rows, min_likely_oos_predictions)

    checks.extend(
        [
            GateCheck("min_reviewed_rows", n_reviewed >= int(min_reviewed_rows), n_reviewed, int(min_reviewed_rows)),
            GateCheck("min_model_eligible_rows", n_model_eligible >= int(min_model_eligible_rows), n_model_eligible, int(min_model_eligible_rows)),
            GateCheck("min_likely_oos_predictions", n_likely_oos >= int(min_likely_oos_predictions), n_likely_oos, int(min_likely_oos_predictions), oos_notes),
            GateCheck("reviewed_labels", bool((reviewed_mask & label_ok).sum() == n_reviewed and n_reviewed > 0), int((reviewed_mask & label_ok).sum()), f"all {n_reviewed} reviewed rows"),
        ]
    )

    if require_evidence:
        checks.append(
            GateCheck(
                "evidence",
                bool((reviewed_mask & evidence_ok).sum() == n_reviewed and n_reviewed > 0),
                int((reviewed_mask & evidence_ok).sum()),
                f"all {n_reviewed} reviewed rows",
            )
        )
    if require_known_release_session:
        checks.append(
            GateCheck(
                "known_release_session",
                bool((reviewed_mask & release_ok).sum() == n_reviewed and n_reviewed > 0),
                int((reviewed_mask & release_ok).sum()),
                f"all {n_reviewed} reviewed rows in {sorted(KNOWN_RELEASE_SESSIONS)}",
            )
        )

    if "duplicate_status" in df.columns:
        checks.append(
            GateCheck(
                "duplicate_status",
                bool((reviewed_mask & duplicate_ok).sum() == n_reviewed and n_reviewed > 0),
                int((reviewed_mask & duplicate_ok).sum()),
                f"all {n_reviewed} reviewed rows primary/unique",
            )
        )
    if "timestamp_audit_status" in df.columns:
        checks.append(
            GateCheck(
                "timestamp_audit",
                bool((reviewed_mask & timestamp_ok).sum() == n_reviewed and n_reviewed > 0),
                int((reviewed_mask & timestamp_ok).sum()),
                f"all {n_reviewed} reviewed rows clear/audited",
            )
        )
    if "execution_survivability_class" in df.columns:
        checks.append(
            GateCheck(
                "execution_survivability",
                bool((reviewed_mask & execution_ok).sum() == n_reviewed and n_reviewed > 0),
                int((reviewed_mask & execution_ok).sum()),
                f"all {n_reviewed} reviewed rows execution-classified",
            )
        )
    if "event_status" in df.columns:
        checks.append(
            GateCheck(
                "event_status",
                bool((reviewed_mask & event_ok).sum() == n_reviewed),
                int((reviewed_mask & event_ok).sum()),
                f"all {n_reviewed} reviewed rows ok",
            )
        )
    if "corpus_validation_status" in df.columns:
        checks.append(GateCheck("corpus_validation_status", bool((reviewed_mask & corpus_ok).sum() == n_reviewed), int((reviewed_mask & corpus_ok).sum()), f"all {n_reviewed} reviewed rows not failed"))

    failed_gates = [check.name for check in checks if not check.passed]
    quality_gates = {
        "reviewed_labels",
        "evidence",
        "known_release_session",
        "duplicate_status",
        "timestamp_audit",
        "execution_survivability",
        "event_status",
        "corpus_validation_status",
    }
    threshold_gates = {"min_reviewed_rows", "min_model_eligible_rows", "min_likely_oos_predictions"}
    if any(gate in quality_gates for gate in failed_gates):
        decision = "reject_modeling"
    elif any(gate in threshold_gates for gate in failed_gates):
        decision = "monitor_only"
    elif warnings:
        decision = "needs_review"
    else:
        decision = "model_ready"

    summary = {
        "n_rows": n_rows,
        "n_usable_rows": n_usable,
        "n_reviewed_rows": n_reviewed,
        "n_model_eligible_rows": n_model_eligible,
        "n_likely_oos_predictions": n_likely_oos,
        "reviewed_statuses": {str(k): int(v) for k, v in review.value_counts(dropna=False).items()},
        "release_sessions": {str(k): int(v) for k, v in release_session.value_counts(dropna=False).items()},
    }
    return PromotionReport(decision=decision, checks=checks, failed_gates=failed_gates, warnings=warnings, summary=summary).to_dict()
