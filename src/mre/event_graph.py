from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, fields, is_dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .paths import ensure_parent


def _clean_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _jsonable(value: Any) -> Any:
    value = _clean_value(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "to_dict"):
        return row.to_dict()
    if is_dataclass(row):
        return {k: _jsonable(v) for k, v in asdict(row).items()}
    if isinstance(row, Mapping):
        return {str(k): _jsonable(v) for k, v in row.items()}
    raise TypeError(f"Unsupported row type: {type(row).__name__}")


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps([_jsonable(part) for part in parts], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(prefix).strip()) or "id"
    return f"{safe_prefix}_{digest}"


def claim_id(event_id: object, field_name: object, evidence_text_or_value: object) -> str:
    return stable_id("claim", event_id, field_name, evidence_text_or_value)


def evidence_span_id(source_doc_id: object, start_char: object, end_char: object) -> str:
    return stable_id("span", source_doc_id, int(start_char), int(end_char))


@dataclass(frozen=True)
class Issuer:
    issuer_id: str
    cik: str = ""
    ticker: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class Filing:
    filing_id: str
    issuer_id: str
    cik: str = ""
    ticker: str = ""
    form: str = ""
    accession: str = ""
    filing_date: str = ""
    accepted_at: str = ""
    source_url: str = ""
    primary_doc_url: str = ""
    item_numbers: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class Event:
    event_id: str
    issuer_id: str
    filing_id: str
    event_type: str
    event_subtype: str = ""
    event_family: str = ""
    event_time: str = ""
    release_session: str = "unknown"
    summary: str = ""
    review_status: str = "needs_review"
    timestamp_readiness_status: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class Claim:
    claim_id: str
    event_id: str
    field_name: str
    value: Any
    value_type: str = "string"
    confidence: float = 0.0
    method: str = ""
    review_status: str = "needs_review"
    evidence_span_id: str = ""
    source_doc_id: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class EvidenceSpan:
    evidence_span_id: str
    source_doc_id: str
    claim_id: str
    evidence_text: str
    start_char: int
    end_char: int
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    target_type: str
    target_id: str
    reviewer: str = ""
    status: str = "needs_review"
    notes: str = ""
    reviewed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


@dataclass(frozen=True)
class RunReference:
    run_id: str
    manifest_path: str = ""
    manifest_hash: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _row_dict(asdict(self))


def dataclasses_to_frame(rows: Iterable[Any]) -> pd.DataFrame:
    return pd.DataFrame([_row_dict(row) for row in rows])


def _records_for_dataclass(df: pd.DataFrame, cls: type) -> list[dict[str, Any]]:
    dataclass_fields = fields(cls)
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {}
        for field in dataclass_fields:
            if field.name in df.columns:
                record[field.name] = _clean_value(row.get(field.name))
            elif field.default is not MISSING:
                record[field.name] = field.default
            elif field.default_factory is not MISSING:  # type: ignore[attr-defined]
                record[field.name] = field.default_factory()  # type: ignore[misc]
            else:
                record[field.name] = ""
        records.append(record)
    return records


def frame_to_claims(df: pd.DataFrame) -> list[Claim]:
    records = _records_for_dataclass(df, Claim)
    return [Claim(**record) for record in records]


def frame_to_evidence_spans(df: pd.DataFrame) -> list[EvidenceSpan]:
    records = _records_for_dataclass(df, EvidenceSpan)
    for record in records:
        record["start_char"] = int(record.get("start_char") or 0)
        record["end_char"] = int(record.get("end_char") or 0)
    return [EvidenceSpan(**record) for record in records]


def write_csv(path: str | Path, rows: Iterable[Any]) -> Path:
    p = ensure_parent(path)
    dataclasses_to_frame(rows).to_csv(p, index=False)
    return p


def read_csv(path: str | Path, kind: str) -> list[Any]:
    df = pd.read_csv(path)
    normalized_kind = str(kind).lower().strip()
    if normalized_kind in {"claim", "claims"}:
        return frame_to_claims(df)
    if normalized_kind in {"evidence", "evidence_span", "evidence_spans"}:
        return frame_to_evidence_spans(df)
    raise ValueError(f"Unsupported event graph CSV kind: {kind}")
