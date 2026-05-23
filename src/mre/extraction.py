from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import make_event_template
from .expectations import compute_expectation_features
from .paths import ensure_parent
from .source_docs import SourceDocument, load_source_documents

FACT_NAMES = {
    "actual_eps",
    "consensus_eps",
    "consensus_forward_eps",
    "guidance_eps_low",
    "guidance_eps_high",
    "guidance_eps_mid",
    "actual_revenue",
    "consensus_revenue",
    "consensus_forward_revenue",
    "guidance_revenue_low",
    "guidance_revenue_high",
    "guidance_revenue_mid",
    "actual_gross_margin",
    "consensus_gross_margin",
    "consensus_forward_gross_margin",
    "guidance_gross_margin_low",
    "guidance_gross_margin_high",
    "guidance_gross_margin_mid",
}

EXPECTATION_FACT_NAMES = sorted(FACT_NAMES)

MONEY_PATTERN = re.compile(
    r"\$?\s*(?P<num>-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m)?",
    flags=re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(?P<num>-?\d+(?:\.\d+)?)\s*%")
EPS_PATTERN = re.compile(r"\$?\s*(?P<num>-?\d+(?:\.\d+)?)")


@dataclass
class ExtractedFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: float
    unit: str
    confidence: float
    method: str
    evidence_text: str
    start_char: int
    end_char: int
    source_type: str = ""
    source_url: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionDiagnostics:
    documents_total: int = 0
    documents_with_facts: int = 0
    facts_total: int = 0
    fact_counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def add_fact(self, fact_name: str) -> None:
        self.facts_total += 1
        self.fact_counts[fact_name] = self.fact_counts.get(fact_name, 0) + 1

    def add_skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _segments(text: str) -> Iterable[tuple[str, int, int]]:
    # Split on sentence-ish boundaries and lines while preserving original offsets.
    # Decimal points inside numbers (2.45, 58.2%) are not treated as boundaries.
    boundary = re.compile(r"(?<!\d)[\.;!?](?!\d)|\n")
    start = 0
    for match in boundary.finditer(text):
        end = match.end()
        raw = text[start:end]
        seg = raw.strip()
        if len(seg) >= 6:
            offset = len(raw) - len(raw.lstrip())
            yield seg, start + offset, end
        start = end
    raw = text[start:]
    seg = raw.strip()
    if len(seg) >= 6:
        offset = len(raw) - len(raw.lstrip())
        yield seg, start + offset, len(text)


def _money_matches(segment: str) -> list[tuple[float, str, int, int]]:
    out = []
    for m in MONEY_PATTERN.finditer(segment):
        num = float(m.group("num"))
        unit = (m.group("unit") or "").lower()
        if unit in {"billion", "bn", "b"}:
            val = num * 1000.0
            normalized_unit = "usd_millions"
        elif unit in {"million", "mn", "m"}:
            val = num
            normalized_unit = "usd_millions"
        else:
            # Ambiguous raw dollars are retained as raw numeric values. For
            # revenue/guidance rows, callers should prefer amounts with units.
            val = num
            normalized_unit = "numeric"
        out.append((val, normalized_unit, m.start(), m.end()))
    return out


def _percent_matches(segment: str) -> list[tuple[float, str, int, int]]:
    return [(float(m.group("num")) / 100.0, "fraction", m.start(), m.end()) for m in PERCENT_PATTERN.finditer(segment)]


def _eps_matches(segment: str) -> list[tuple[float, str, int, int]]:
    """Return EPS-like numbers, preferring numbers after an EPS phrase."""
    low = segment.lower()
    keyword_positions = [m.start() for m in re.finditer(r"\beps\b|earnings per share|diluted earnings per share", low)]
    search_ranges: list[tuple[int, str]]
    if keyword_positions:
        search_ranges = [(pos, segment[pos : pos + 120]) for pos in keyword_positions]
    else:
        search_ranges = [(0, segment)]
    out = []
    for base, chunk in search_ranges:
        for m in EPS_PATTERN.finditer(chunk):
            try:
                val = float(m.group("num"))
            except ValueError:
                continue
            out.append((val, "usd_per_share", base + m.start(), base + m.end()))
        if out:
            break
    return out


def _contains_any(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _confidence(base: float, segment: str, *, primary: bool = False) -> float:
    score = base
    low = segment.lower()
    if primary:
        score += 0.08
    if any(w in low for w in ["consensus", "analysts", "analyst", "estimate", "estimated", "expected"]):
        score += 0.04
    if any(w in low for w in ["guidance", "outlook", "expects", "forecast"]):
        score += 0.04
    if len(segment) < 220:
        score += 0.03
    return float(np.clip(score, 0.05, 0.98))


def _fact(
    doc: SourceDocument,
    fact_name: str,
    value: float,
    unit: str,
    confidence: float,
    method: str,
    segment: str,
    start: int,
    end: int,
    notes: str = "",
) -> ExtractedFact:
    return ExtractedFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=fact_name,
        value=float(value),
        unit=unit,
        confidence=float(confidence),
        method=method,
        evidence_text=_norm_space(segment),
        start_char=int(start),
        end_char=int(end),
        source_type=doc.source_type,
        source_url=doc.source_url,
        notes=notes,
    )


def _add_money_fact(
    facts: list[ExtractedFact],
    doc: SourceDocument,
    fact_name: str,
    segment: str,
    start: int,
    match: tuple[float, str, int, int],
    confidence: float,
    method: str,
) -> None:
    val, unit, a, b = match
    facts.append(_fact(doc, fact_name, val, unit, confidence, method, segment, start + a, start + b))


def _best_money_amount(segment: str, *, prefer_unit: bool = True) -> tuple[float, str, int, int] | None:
    matches = _money_matches(segment)
    if not matches:
        return None
    if prefer_unit:
        with_units = [m for m in matches if m[1] == "usd_millions"]
        if with_units:
            return with_units[0]
    return matches[0]


def _range_or_mid_money(segment: str) -> tuple[tuple[float, str, int, int] | None, tuple[float, str, int, int] | None, tuple[float, str, int, int] | None]:
    matches = [m for m in _money_matches(segment) if m[1] == "usd_millions"]
    if len(matches) >= 2:
        lo, hi = matches[0], matches[1]
        if lo[0] > hi[0]:
            lo, hi = hi, lo
        mid = ((lo[0] + hi[0]) / 2.0, lo[1], lo[2], hi[3])
        return lo, hi, mid
    if len(matches) == 1:
        return None, None, matches[0]
    return None, None, None


def _range_or_mid_percent(segment: str) -> tuple[tuple[float, str, int, int] | None, tuple[float, str, int, int] | None, tuple[float, str, int, int] | None]:
    matches = _percent_matches(segment)
    if len(matches) >= 2:
        lo, hi = matches[0], matches[1]
        if lo[0] > hi[0]:
            lo, hi = hi, lo
        mid = ((lo[0] + hi[0]) / 2.0, "fraction", lo[2], hi[3])
        return lo, hi, mid
    if len(matches) == 1:
        return None, None, matches[0]
    return None, None, None


def _range_or_mid_eps(segment: str) -> tuple[tuple[float, str, int, int] | None, tuple[float, str, int, int] | None, tuple[float, str, int, int] | None]:
    matches = _eps_matches(segment)
    # Ignore large revenue-like values if sentence also contains revenue/sales.
    matches = [m for m in matches if abs(m[0]) < 100]
    if len(matches) >= 2:
        lo, hi = matches[0], matches[1]
        if lo[0] > hi[0]:
            lo, hi = hi, lo
        mid = ((lo[0] + hi[0]) / 2.0, "usd_per_share", lo[2], hi[3])
        return lo, hi, mid
    if len(matches) == 1:
        return None, None, matches[0]
    return None, None, None


def extract_facts_from_document(doc: SourceDocument) -> list[ExtractedFact]:
    """Deterministic, evidence-grounded extraction for earnings/guidance docs.

    This extractor is deliberately conservative. It is not a substitute for a
    high-quality LLM or vendor feed; it provides a transparent baseline and
    produces evidence spans that can be audited or corrected later.
    """
    facts: list[ExtractedFact] = []
    for segment, start, _end in _segments(doc.text):
        low = segment.lower()
        is_expectation = _contains_any(low, ["consensus", "analysts expected", "analyst expected", "analysts estimate", "estimate", "estimated", "expected"])
        is_guidance = _contains_any(low, ["guidance", "outlook", "expects", "forecast", "projects"])
        is_forward = _contains_any(low, ["next quarter", "current quarter", "fiscal", "full year", "fy", "q1", "q2", "q3", "q4"])

        # Revenue / net sales.
        if _contains_any(low, ["revenue", "net sales", "sales"]):
            if is_guidance:
                lo, hi, mid = _range_or_mid_money(segment)
                conf = _confidence(0.72, segment, primary=doc.source_type in {"company_press_release", "sec_filing"})
                if lo:
                    _add_money_fact(facts, doc, "guidance_revenue_low", segment, start, lo, conf, "regex_guidance_revenue")
                if hi:
                    _add_money_fact(facts, doc, "guidance_revenue_high", segment, start, hi, conf, "regex_guidance_revenue")
                if mid:
                    _add_money_fact(facts, doc, "guidance_revenue_mid", segment, start, mid, conf - 0.02, "regex_guidance_revenue")
            elif is_expectation:
                amount = _best_money_amount(segment)
                if amount:
                    name = "consensus_forward_revenue" if is_forward else "consensus_revenue"
                    _add_money_fact(facts, doc, name, segment, start, amount, _confidence(0.74, segment), "regex_consensus_revenue")
            else:
                amount = _best_money_amount(segment)
                if amount:
                    _add_money_fact(facts, doc, "actual_revenue", segment, start, amount, _confidence(0.76, segment, primary=doc.source_type in {"company_press_release", "sec_filing"}), "regex_actual_revenue")

        # EPS / earnings per share.
        if _contains_any(low, ["eps", "earnings per share", "diluted earnings per share"]):
            if is_guidance:
                lo, hi, mid = _range_or_mid_eps(segment)
                conf = _confidence(0.70, segment, primary=doc.source_type in {"company_press_release", "sec_filing"})
                if lo:
                    facts.append(_fact(doc, "guidance_eps_low", lo[0], lo[1], conf, "regex_guidance_eps", segment, start + lo[2], start + lo[3]))
                if hi:
                    facts.append(_fact(doc, "guidance_eps_high", hi[0], hi[1], conf, "regex_guidance_eps", segment, start + hi[2], start + hi[3]))
                if mid:
                    facts.append(_fact(doc, "guidance_eps_mid", mid[0], mid[1], conf - 0.02, "regex_guidance_eps", segment, start + mid[2], start + mid[3]))
            elif is_expectation:
                matches = [m for m in _eps_matches(segment) if abs(m[0]) < 100]
                if matches:
                    name = "consensus_forward_eps" if is_forward else "consensus_eps"
                    m = matches[0]
                    facts.append(_fact(doc, name, m[0], m[1], _confidence(0.72, segment), "regex_consensus_eps", segment, start + m[2], start + m[3]))
            else:
                matches = [m for m in _eps_matches(segment) if abs(m[0]) < 100]
                if matches:
                    m = matches[0]
                    facts.append(_fact(doc, "actual_eps", m[0], m[1], _confidence(0.75, segment, primary=doc.source_type in {"company_press_release", "sec_filing"}), "regex_actual_eps", segment, start + m[2], start + m[3]))

        # Gross margin.
        if "gross margin" in low:
            if is_guidance:
                lo, hi, mid = _range_or_mid_percent(segment)
                conf = _confidence(0.71, segment, primary=doc.source_type in {"company_press_release", "sec_filing"})
                if lo:
                    facts.append(_fact(doc, "guidance_gross_margin_low", lo[0], lo[1], conf, "regex_guidance_gross_margin", segment, start + lo[2], start + lo[3]))
                if hi:
                    facts.append(_fact(doc, "guidance_gross_margin_high", hi[0], hi[1], conf, "regex_guidance_gross_margin", segment, start + hi[2], start + hi[3]))
                if mid:
                    facts.append(_fact(doc, "guidance_gross_margin_mid", mid[0], mid[1], conf - 0.02, "regex_guidance_gross_margin", segment, start + mid[2], start + mid[3]))
            elif is_expectation:
                pcts = _percent_matches(segment)
                if pcts:
                    name = "consensus_forward_gross_margin" if is_forward else "consensus_gross_margin"
                    m = pcts[0]
                    facts.append(_fact(doc, name, m[0], m[1], _confidence(0.72, segment), "regex_consensus_gross_margin", segment, start + m[2], start + m[3]))
            else:
                pcts = _percent_matches(segment)
                if pcts:
                    m = pcts[0]
                    facts.append(_fact(doc, "actual_gross_margin", m[0], m[1], _confidence(0.75, segment, primary=doc.source_type in {"company_press_release", "sec_filing"}), "regex_actual_gross_margin", segment, start + m[2], start + m[3]))

    return _dedupe_facts(facts)


def _dedupe_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    best: dict[tuple[str, str, float], ExtractedFact] = {}
    for fact in facts:
        key = (fact.event_id, fact.fact_name, round(float(fact.value), 8))
        old = best.get(key)
        if old is None or fact.confidence > old.confidence:
            best[key] = fact
    return list(best.values())


def extract_facts_from_documents(docs: Iterable[SourceDocument]) -> tuple[pd.DataFrame, ExtractionDiagnostics]:
    diagnostics = ExtractionDiagnostics()
    rows: list[dict] = []
    for doc in docs:
        diagnostics.documents_total += 1
        facts = extract_facts_from_document(doc)
        if facts:
            diagnostics.documents_with_facts += 1
        else:
            diagnostics.add_skip("no_supported_facts_extracted")
        for fact in facts:
            diagnostics.add_fact(fact.fact_name)
            rows.append(fact.to_dict())
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "source_doc_id",
                "event_id",
                "ticker",
                "event_time",
                "fact_name",
                "value",
                "unit",
                "confidence",
                "method",
                "evidence_text",
                "start_char",
                "end_char",
                "source_type",
                "source_url",
                "notes",
            ]
        )
    return df, diagnostics


def _choose_best_fact(group: pd.DataFrame) -> pd.Series:
    tmp = group.copy()
    tmp["confidence"] = pd.to_numeric(tmp["confidence"], errors="coerce").fillna(0.0)
    tmp["evidence_len"] = tmp["evidence_text"].fillna("").astype(str).str.len()
    tmp = tmp.sort_values(["confidence", "evidence_len"], ascending=[False, True])
    return tmp.iloc[0]


def facts_to_expectations(facts: pd.DataFrame) -> pd.DataFrame:
    """Pivot extracted fact rows into expectation-feature rows by event_id."""
    if facts.empty:
        return pd.DataFrame(columns=["event_id"] + EXPECTATION_FACT_NAMES)
    required = {"event_id", "ticker", "event_time", "fact_name", "value"}
    missing = sorted(required - set(facts.columns))
    if missing:
        raise ValueError(f"Facts frame missing required columns: {missing}")
    rows = []
    for event_id, group in facts.groupby("event_id", dropna=False):
        row: dict[str, object] = {
            "event_id": str(event_id),
            "ticker": str(group["ticker"].iloc[0]).upper(),
            "asof_time": str(group["event_time"].iloc[0]),
            "expectation_source_type": "extracted_source_document",
            "expectation_source_url": ";".join(sorted(set(group.get("source_url", pd.Series(dtype=str)).dropna().astype(str))))[:1000],
            "expectation_notes": "Derived from deterministic evidence-grounded extraction. Review before trading use.",
            "source_doc_ids": ";".join(sorted(set(group["source_doc_id"].astype(str)))),
            "extraction_fact_count": int(len(group)),
            "extraction_confidence_mean": float(pd.to_numeric(group["confidence"], errors="coerce").mean()),
        }
        for fact_name, fact_group in group.groupby("fact_name"):
            if fact_name not in FACT_NAMES:
                continue
            chosen = _choose_best_fact(fact_group)
            row[fact_name] = float(chosen["value"])
            row[f"{fact_name}_evidence"] = chosen.get("evidence_text", "")
            row[f"{fact_name}_source_doc_id"] = chosen.get("source_doc_id", "")
            row[f"{fact_name}_confidence"] = float(chosen.get("confidence", np.nan))
        rows.append(row)
    out = pd.DataFrame(rows)
    return compute_expectation_features(out)


def facts_to_events(docs: Iterable[SourceDocument], facts: pd.DataFrame) -> pd.DataFrame:
    counts = facts.groupby("event_id").size().to_dict() if not facts.empty else {}
    rows = []
    for doc in docs:
        fact_count = int(counts.get(doc.event_id, 0))
        summary = doc.title or f"Extracted {doc.event_type} source document for {doc.ticker}"
        rows.append(
            {
                "event_id": doc.event_id,
                "ticker": doc.ticker,
                "event_time": doc.event_time.isoformat(),
                "event_type": doc.event_type or "earnings",
                "summary": summary,
                "event_subtype": doc.event_subtype or "document_extracted",
                "source_type": doc.source_type or "source_document",
                "source_url": doc.source_url,
                "release_session": doc.release_session or "unknown",
                "expectedness": "unknown",
                "surprise_direction": "unknown",
                "surprise_magnitude": "unknown",
                "materiality": 0.7 if fact_count else 0.4,
                "sector_benchmark": doc.sector_benchmark,
                "notes": doc.notes or "Generated from source-document manifest; review extraction facts before modeling.",
                "event_family": "earnings_guidance" if doc.event_type in {"earnings", "guidance"} else doc.event_type,
                "fiscal_period_end": doc.fiscal_period_end,
                "source_doc_id": doc.source_doc_id,
                "extraction_fact_count": fact_count,
            }
        )
    return pd.DataFrame(rows)


def run_document_extraction(
    documents_manifest: str | Path,
    *,
    facts_out: str | Path | None = None,
    expectations_out: str | Path | None = None,
    events_out: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, ExtractionDiagnostics]:
    docs = load_source_documents(documents_manifest)
    facts, diagnostics = extract_facts_from_documents(docs)
    expectations = facts_to_expectations(facts)
    events = facts_to_events(docs, facts)
    if facts_out:
        facts.to_csv(ensure_parent(facts_out), index=False)
    if expectations_out:
        expectations.to_csv(ensure_parent(expectations_out), index=False)
    if events_out:
        make_event_template(events_out, rows=events.to_dict(orient="records"))
    return facts, expectations, events, diagnostics


def build_extraction_packets(
    documents_manifest: str | Path,
    out_path: str | Path,
    *,
    max_chars: int = 12000,
) -> int:
    """Create JSONL packets for a future LLM extractor.

    The packets require the model to return fact rows with exact evidence_text.
    This function does not call an LLM; it prepares auditable work units.
    """
    docs = load_source_documents(documents_manifest)
    p = ensure_parent(out_path)
    instructions = (
        "Extract only facts that are explicitly supported by the text. Return JSON with a `facts` list. "
        "Each fact must include fact_name, value, unit, evidence_text, and confidence. "
        "Allowed fact_name values: " + ", ".join(EXPECTATION_FACT_NAMES) + ". "
        "Do not infer from stock-price reaction or outside knowledge."
    )
    with p.open("w", encoding="utf-8") as f:
        for doc in docs:
            packet = {
                "schema_version": "mre.extraction_packet.v1",
                "source_doc_id": doc.source_doc_id,
                "event_id": doc.event_id,
                "ticker": doc.ticker,
                "event_time": doc.event_time.isoformat(),
                "source_type": doc.source_type,
                "source_url": doc.source_url,
                "title": doc.title,
                "allowed_fact_names": EXPECTATION_FACT_NAMES,
                "instructions": instructions,
                "text": doc.text[:max_chars],
            }
            f.write(json.dumps(packet, ensure_ascii=False) + "\n")
    return len(docs)


def _doc_text_map(docs: Iterable[SourceDocument]) -> dict[str, str]:
    return {d.source_doc_id: d.text for d in docs}


def validate_llm_facts_jsonl(
    documents_manifest: str | Path,
    llm_jsonl: str | Path,
    out_path: str | Path,
    *,
    require_evidence_in_text: bool = True,
) -> pd.DataFrame:
    """Validate JSONL LLM extraction output and convert it to fact CSV rows.

    Expected JSONL shape per line:
    {"source_doc_id": "...", "event_id": "...", "facts": [{"fact_name": "actual_revenue", "value": 1234, "unit": "usd_millions", "evidence_text": "...", "confidence": 0.8}]}
    """
    docs = load_source_documents(documents_manifest)
    doc_by_id = {d.source_doc_id: d for d in docs}
    text_by_id = _doc_text_map(docs)
    rows: list[dict] = []
    with Path(llm_jsonl).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_id = str(payload.get("source_doc_id", ""))
            if doc_id not in doc_by_id:
                raise ValueError(f"Line {line_no}: unknown source_doc_id {doc_id!r}")
            doc = doc_by_id[doc_id]
            for fact in payload.get("facts", []):
                name = str(fact.get("fact_name", ""))
                if name not in FACT_NAMES:
                    raise ValueError(f"Line {line_no}: invalid fact_name {name!r}")
                evidence = _norm_space(str(fact.get("evidence_text", "")))
                source_text = text_by_id[doc_id]
                start = source_text.find(evidence) if evidence else -1
                if require_evidence_in_text and start < 0:
                    raise ValueError(f"Line {line_no}: evidence_text not found in source_doc_id={doc_id}")
                try:
                    value = float(fact.get("value"))
                except Exception as exc:
                    raise ValueError(f"Line {line_no}: fact value must be numeric") from exc
                rows.append(
                    ExtractedFact(
                        source_doc_id=doc.source_doc_id,
                        event_id=str(payload.get("event_id") or doc.event_id),
                        ticker=doc.ticker,
                        event_time=doc.event_time.isoformat(),
                        fact_name=name,
                        value=value,
                        unit=str(fact.get("unit", "numeric")),
                        confidence=float(fact.get("confidence", 0.5)),
                        method="llm_validated_jsonl",
                        evidence_text=evidence,
                        start_char=max(start, 0),
                        end_char=max(start + len(evidence), 0),
                        source_type=doc.source_type,
                        source_url=doc.source_url,
                        notes=str(fact.get("notes", "")),
                    ).to_dict()
                )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["event_time", "ticker", "event_id", "fact_name"]).reset_index(drop=True)
    df.to_csv(ensure_parent(out_path), index=False)
    return df
