from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_REGISTRY_PATH = Path("docs/DOMAIN_RESEARCH_REGISTRY.md")


@dataclass(frozen=True)
class DomainRecord:
    domain: str
    status: str
    stage_reached: str
    stop_reason: str
    last_known_commit: str
    revisit_trigger: str


@dataclass(frozen=True)
class IntakeScore:
    scores: dict[str, int]
    missing_dimensions: list[str]
    total: int
    recommendation: str
    critical_failures: list[str]


REGISTRY_COLUMNS = [
    "domain",
    "status",
    "stage_reached",
    "stop_reason",
    "last_known_commit",
    "revisit_trigger",
]

INTAKE_DIMENSIONS = [
    "official source quality",
    "public timestamp clarity",
    "delayed-digestion plausibility",
    "hard-negative clarity",
    "materiality-field clarity",
    "sample-size likelihood",
    "ticker/entity mapping feasibility",
    "liquidity/execution feasibility",
    "parser/audit feasibility",
    "fresh-data availability",
]

CRITICAL_DIMENSIONS = [
    "public timestamp clarity",
    "delayed-digestion plausibility",
    "materiality-field clarity",
    "sample-size likelihood",
]


def _clean_cell(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _markdown_rows(text: str) -> Iterable[list[str]]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [_clean_cell(cell) for cell in stripped.strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells):
            continue
        yield cells


def load_domain_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> list[DomainRecord]:
    registry_path = Path(path)
    text = registry_path.read_text(encoding="utf-8")
    rows = list(_markdown_rows(text))
    records: list[DomainRecord] = []
    for cells in rows:
        normalized = [cell.lower().replace(" ", "_") for cell in cells]
        if normalized[: len(REGISTRY_COLUMNS)] == REGISTRY_COLUMNS:
            continue
        if len(cells) < len(REGISTRY_COLUMNS):
            continue
        if cells[0].lower() == "domain":
            continue
        records.append(
            DomainRecord(
                domain=cells[0],
                status=cells[1],
                stage_reached=cells[2],
                stop_reason=cells[3],
                last_known_commit=cells[4],
                revisit_trigger=cells[5],
            )
        )
    return records


def records_to_json(records: Iterable[DomainRecord]) -> str:
    return json.dumps([asdict(record) for record in records], indent=2)


def format_domain_status(records: Iterable[DomainRecord]) -> str:
    rows = list(records)
    headers = ["domain", "status", "revisit_trigger"]
    data = [[row.domain, row.status, row.revisit_trigger] for row in rows]
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in data)) if data else len(headers[idx])
        for idx in range(len(headers))
    ]
    lines = ["  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))]
    lines.append("  ".join("-" * width for width in widths))
    for row in data:
        lines.append("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))
    return "\n".join(lines)


def _score_from_cell(cell: str) -> int | None:
    match = re.search(r"\b([0-3])\b", cell)
    if not match:
        return None
    return int(match.group(1))


def score_intake(path: str | Path) -> IntakeScore:
    text = Path(path).read_text(encoding="utf-8")
    scores: dict[str, int] = {}
    for cells in _markdown_rows(text):
        if len(cells) < 2:
            continue
        dimension = cells[0].strip().lower()
        if dimension in {"dimension", "---"}:
            continue
        if dimension not in INTAKE_DIMENSIONS:
            continue
        score = _score_from_cell(cells[1])
        if score is not None:
            scores[dimension] = score

    missing = [dimension for dimension in INTAKE_DIMENSIONS if dimension not in scores]
    total = sum(scores.values())
    critical_failures = [dimension for dimension in CRITICAL_DIMENSIONS if scores.get(dimension, 0) < 2]

    if missing:
        recommendation = "incomplete"
    elif critical_failures:
        recommendation = "backlog or source-feasibility only"
    elif total >= 24:
        recommendation = "full lifecycle agent allowed"
    elif total >= 18:
        recommendation = "source-feasibility only"
    elif total >= 12:
        recommendation = "backlog, do not assign yet"
    else:
        recommendation = "skip unless new data/source appears"

    return IntakeScore(
        scores=scores,
        missing_dimensions=missing,
        total=total,
        recommendation=recommendation,
        critical_failures=critical_failures,
    )


def intake_score_to_json(score: IntakeScore) -> str:
    return json.dumps(asdict(score), indent=2)


def format_intake_score(score: IntakeScore) -> str:
    lines = ["Domain intake score", ""]
    for dimension in INTAKE_DIMENSIONS:
        value = score.scores.get(dimension)
        rendered = "missing" if value is None else str(value)
        lines.append(f"- {dimension}: {rendered}")
    lines.extend(
        [
            "",
            f"Total: {score.total}/30",
            f"Recommendation: {score.recommendation}",
        ]
    )
    if score.critical_failures:
        lines.append("Critical failures: " + ", ".join(score.critical_failures))
    if score.missing_dimensions:
        lines.append("Missing dimensions: " + ", ".join(score.missing_dimensions))
    return "\n".join(lines)


def monitor_records(records: Iterable[DomainRecord]) -> list[DomainRecord]:
    monitors: list[DomainRecord] = []
    for record in records:
        haystack = f"{record.status} {record.revisit_trigger}".lower()
        if "monitor" in haystack or "underpowered" in haystack:
            monitors.append(record)
    return monitors


def format_revisit_triggers(records: Iterable[DomainRecord]) -> str:
    rows = monitor_records(records)
    if not rows:
        return "No monitor or underpowered domains found in registry."
    lines = ["Revisit triggers", ""]
    for record in rows:
        lines.append(f"- {record.domain}: {record.status}; {record.revisit_trigger}")
    return "\n".join(lines)


def _read_excerpt(path: str | Path | None, *, max_chars: int = 1200) -> str:
    if not path:
        return "Not provided."
    file_path = Path(path)
    if not file_path.exists():
        return f"Missing: {file_path}"
    text = file_path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text or "Empty file."
    return text[:max_chars].rstrip() + "\n\n...[truncated]"


def write_domain_final_report(
    *,
    domain: str,
    out_path: str | Path,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    readiness_report: str | Path | None = None,
    parser_audit: str | Path | None = None,
    timestamp_audit: str | Path | None = None,
    falsification_report: str | Path | None = None,
    fresh_confirmation_report: str | Path | None = None,
    execution_audit: str | Path | None = None,
) -> DomainRecord:
    records = load_domain_registry(registry_path)
    normalized_domain = domain.strip().lower()
    matches = [record for record in records if record.domain.lower() == normalized_domain]
    if not matches:
        known = ", ".join(record.domain for record in records)
        raise ValueError(f"Domain '{domain}' not found in registry. Known domains: {known}")
    record = matches[0]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = f"""# {record.domain} Domain Final Report

## Registry Verdict

- Status: {record.status}
- Stage reached: {record.stage_reached}
- Stop reason: {record.stop_reason}
- Last known commit: {record.last_known_commit}
- Revisit trigger: {record.revisit_trigger}

## Readiness Report

{_read_excerpt(readiness_report)}

## Parser Audit

{_read_excerpt(parser_audit)}

## Timestamp / Duplicate Audit

{_read_excerpt(timestamp_audit)}

## Falsification Report

{_read_excerpt(falsification_report)}

## Fresh Confirmation Report

{_read_excerpt(fresh_confirmation_report)}

## Execution / Leakage Audit

{_read_excerpt(execution_audit)}

## Final Note

This report is generated from the domain registry plus available supporting
reports. The registry remains the source of truth for domain status and revisit
triggers.
"""
    out.write_text(body, encoding="utf-8")
    return record

