from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_parent
from .sec_common import clean_text, read_csv_rows, truthy
from .sec_context import CONTEXT_FIELDS

DECISIONS = {
    "model-ready",
    "continue corpus buildout",
    "parser not trusted",
    "context insufficient",
    "timestamp insufficient",
    "underpowered",
    "freeze domain",
}


def _load_optional(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    rows, _ = read_csv_rows(p)
    return rows


def _count_reviewed_usable(rows: list[dict[str, str]]) -> int:
    good_status = {"reviewed", "approved", "curated", "usable"}
    bad_status = {"rejected", "drop", "dropped"}
    count = 0
    for row in rows:
        status = clean_text(row.get("review_status")).lower()
        drop_reason = clean_text(row.get("drop_reason"))
        if status in bad_status or drop_reason:
            continue
        if status in good_status:
            count += 1
    return count


def _count_model_eligible(rows: list[dict[str, str]]) -> int:
    return sum(1 for row in rows if truthy(row.get("model_eligible")))


def _parser_status(rows: list[dict[str, str]]) -> tuple[str, str]:
    if not rows:
        return "missing", "no parser audit file supplied"
    status_values = [clean_text(row.get("status")).lower() for row in rows if "status" in row]
    if status_values and all(status in {"ok", "pass", "passed"} for status in status_values):
        return "pass", f"{len(rows)} parser audit rows pass"
    failures = sum(1 for status in status_values if status not in {"ok", "pass", "passed"})
    if failures:
        return "fail", f"{failures} parser audit rows are not ok"
    pass_values = [truthy(row.get("parser_audit_pass")) for row in rows if clean_text(row.get("parser_audit_pass"))]
    if pass_values and all(pass_values):
        return "pass", "parser audit pass flag present"
    return "missing", "parser audit status could not be determined"


def _timestamp_status(rows: list[dict[str, str]]) -> tuple[str, float, str]:
    if not rows:
        return "missing", 0.0, "no timestamp audit file supplied"
    ok = sum(1 for row in rows if clean_text(row.get("timestamp_status")).lower() == "ok")
    coverage = ok / len(rows) if rows else 0.0
    if coverage >= 0.80:
        return "pass", coverage, f"{ok}/{len(rows)} timestamp rows are ok"
    return "fail", coverage, f"{ok}/{len(rows)} timestamp rows are ok"


def _context_coverage(rows: list[dict[str, str]]) -> tuple[float, str]:
    if not rows:
        return 0.0, "no context file supplied"
    required = CONTEXT_FIELDS
    present = 0
    possible = len(rows) * len(required)
    for row in rows:
        for field in required:
            if clean_text(row.get(field)):
                present += 1
    coverage = present / possible if possible else 0.0
    return coverage, f"{present}/{possible} required context cells populated"


def build_readiness(
    *,
    domain: str,
    sources_path: str | Path | None = None,
    parsed_path: str | Path | None = None,
    review_path: str | Path | None = None,
    parser_audit_path: str | Path | None = None,
    timestamp_audit_path: str | Path | None = None,
    context_path: str | Path | None = None,
    min_train: int = 40,
) -> dict[str, Any]:
    sources = _load_optional(sources_path)
    parsed = _load_optional(parsed_path)
    review = _load_optional(review_path)
    parser_audit = _load_optional(parser_audit_path)
    timestamp_audit = _load_optional(timestamp_audit_path)
    context = _load_optional(context_path)
    eligibility_rows = context or timestamp_audit or review or parsed

    source_rows = len(sources)
    parsed_rows = len(parsed)
    reviewed_usable_rows = _count_reviewed_usable(review or parsed)
    model_eligible_rows = _count_model_eligible(eligibility_rows)
    likely_oos = max(0, model_eligible_rows - int(min_train))
    parser_status, parser_notes = _parser_status(parser_audit)
    timestamp_status, timestamp_coverage, timestamp_notes = _timestamp_status(timestamp_audit)
    context_coverage, context_notes = _context_coverage(context)

    missing: list[str] = []
    if source_rows == 0:
        missing.append("source rows")
    if parsed_rows == 0:
        missing.append("parsed rows")
    if reviewed_usable_rows == 0:
        missing.append("reviewed usable rows")
    if model_eligible_rows == 0:
        missing.append("model eligible rows")
    if parser_status != "pass":
        missing.append("parser audit status")
    if timestamp_status != "pass":
        missing.append("timestamp audit status")
    if context_coverage < 0.80:
        missing.append("context coverage")
    if likely_oos <= 0:
        missing.append(f"likely OOS predictions with min_train={min_train}")

    if source_rows == 0 or parsed_rows == 0 or reviewed_usable_rows == 0:
        decision = "continue corpus buildout"
    elif parser_status != "pass":
        decision = "parser not trusted"
    elif timestamp_status != "pass":
        decision = "timestamp insufficient"
    elif context_coverage < 0.80:
        decision = "context insufficient"
    elif model_eligible_rows <= min_train:
        decision = "underpowered"
    else:
        decision = "model-ready"

    return {
        "domain": domain,
        "source_rows": source_rows,
        "parsed_rows": parsed_rows,
        "reviewed_usable_rows": reviewed_usable_rows,
        "model_eligible_rows": model_eligible_rows,
        "parser_audit_status": parser_status,
        "parser_audit_notes": parser_notes,
        "timestamp_audit_status": timestamp_status,
        "timestamp_audit_coverage": round(timestamp_coverage, 4),
        "timestamp_audit_notes": timestamp_notes,
        "context_coverage": round(context_coverage, 4),
        "context_coverage_notes": context_notes,
        "likely_oos_predictions": likely_oos,
        "min_train": int(min_train),
        "top_missing_gates": missing[:8],
        "decision": decision,
    }


def write_readiness_report(out_path: str | Path, readiness: dict[str, Any]) -> Path:
    lines = [
        f"# SEC Domain Readiness Report: {readiness.get('domain', '')}",
        "",
        f"Decision: {readiness.get('decision')}",
        "",
        "## Counts",
        "",
        f"- source rows: {readiness.get('source_rows')}",
        f"- parsed rows: {readiness.get('parsed_rows')}",
        f"- reviewed usable rows: {readiness.get('reviewed_usable_rows')}",
        f"- model eligible rows: {readiness.get('model_eligible_rows')}",
        f"- likely OOS predictions with min_train={readiness.get('min_train')}: {readiness.get('likely_oos_predictions')}",
        "",
        "## Gate Status",
        "",
        f"- parser audit status: {readiness.get('parser_audit_status')} ({readiness.get('parser_audit_notes')})",
        f"- timestamp audit status: {readiness.get('timestamp_audit_status')} ({readiness.get('timestamp_audit_notes')})",
        f"- context coverage: {readiness.get('context_coverage')} ({readiness.get('context_coverage_notes')})",
        "",
        "## Top Missing Gates",
        "",
    ]
    missing = readiness.get("top_missing_gates") or []
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- none")
    lines.extend(["", "No prediction model, event study, or backtest was run by this report."])
    out = ensure_parent(out_path)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
