from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd

from .paths import ensure_parent
from .source_docs import SourceDocument, load_source_documents


AMOUNT_RE = re.compile(
    r"\$?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m)?",
    flags=re.IGNORECASE,
)
PCT_RE = re.compile(r"(?P<num>-?\d+(?:\.\d+)?)\s*(?:%|percent|percentage points?)", flags=re.IGNORECASE)

GUIDANCE_WORDS = ("expect", "expects", "expected", "forecast", "forecasting", "outlook", "guidance", "project")
FUTURE_GUIDANCE_WORDS = ("expect", "expects", "expected", "forecast", "forecasting", "outlook", "project", "planning")
ACTUAL_EXCLUDE_WORDS = GUIDANCE_WORDS + ("range of", "plus or minus", "+/-", "±", "between")
SEGMENT_WORDS = ("segment", "business group", "data center", "client", "gaming", "automotive", "industrial")


@dataclass(frozen=True)
class ParsedExhibitFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: float
    unit: str
    period_role: str
    evidence_text: str
    start_char: int
    end_char: int
    confidence: float
    parse_method: str
    quality_flags: str = ""
    source_type: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _sentences(text: str) -> Iterable[tuple[str, int, int]]:
    boundary = re.compile(r"(?<!\d)[\.;!?](?!\d)|\n{2,}")
    start = 0
    for match in boundary.finditer(text):
        end = match.end()
        raw = text[start:end]
        seg = _norm_space(raw)
        if len(seg) >= 8:
            offset = len(raw) - len(raw.lstrip())
            yield seg, start + offset, end
        start = end
    raw = text[start:]
    seg = _norm_space(raw)
    if len(seg) >= 8:
        offset = len(raw) - len(raw.lstrip())
        yield seg, start + offset, len(text)


def _line_segments(text: str) -> Iterable[tuple[str, int, int]]:
    start = 0
    for raw in str(text or "").splitlines(keepends=True):
        end = start + len(raw)
        seg = _norm_space(raw)
        if 8 <= len(seg) <= 320:
            offset = len(raw) - len(raw.lstrip())
            yield seg, start + offset, end
        start = end


def normalize_money_to_usd(match: re.Match[str], default_unit: str = "") -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or default_unit or "").lower()
    if unit in {"billion", "bn", "b"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    return num


def _money_values(segment: str) -> list[tuple[float, int, int, str]]:
    values = []
    for match in AMOUNT_RE.finditer(segment):
        values.append((normalize_money_to_usd(match), match.start(), match.end(), match.group(0)))
    return values


def _contains_any(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _period_role(segment: str, default: str) -> str:
    low = segment.lower()
    if _contains_any(low, GUIDANCE_WORDS):
        if "full year" in low or "fiscal year" in low:
            return "full_year_guidance"
        return "next_quarter_guidance"
    if "year ago" in low or "prior year" in low or "year-over-year" in low or "year over year" in low:
        return "current_quarter_actual"
    return default


def _fact(
    doc: SourceDocument,
    fact_name: str,
    value: float,
    unit: str,
    period_role: str,
    evidence: str,
    start: int,
    end: int,
    confidence: float,
    parse_method: str,
    flags: Iterable[str] = (),
) -> ParsedExhibitFact:
    return ParsedExhibitFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=fact_name,
        value=float(value),
        unit=unit,
        period_role=period_role,
        evidence_text=_norm_space(evidence),
        start_char=int(start),
        end_char=int(end),
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=parse_method,
        quality_flags=";".join(sorted(set(f for f in flags if f))),
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def _parse_guidance_revenue(doc: SourceDocument, segment: str, start: int, end: int) -> list[ParsedExhibitFact]:
    low = segment.lower()
    if not (("revenue" in low or "net sales" in low or "sales" in low) and _contains_any(low, FUTURE_GUIDANCE_WORDS)):
        return []
    if any(w in low for w in SEGMENT_WORDS) and not any(w in low for w in ["total revenue", "net sales", "revenue is expected"]):
        return []

    out: list[ParsedExhibitFact] = []
    role = _period_role(segment, "next_quarter_guidance")
    flags: list[str] = []
    if role == "full_year_guidance":
        flags.append("full_year_guidance")

    # "revenue of $2.60 billion +/- $100 million"
    plusminus = re.search(
        r"(?:revenue|net sales|sales).*?(?:approximately|about|of|be|to be)?\s*"
        r"(?P<mid>\$?\s*-?\d+(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m)?)"
        r".{0,40}?(?:plus or minus|\+/-|±)\s*"
        r"(?P<delta>\$?\s*-?\d+(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m)?|(?:\d+(?:\.\d+)?)\s*%)",
        segment,
        flags=re.IGNORECASE,
    )
    if plusminus:
        mid_match = AMOUNT_RE.search(plusminus.group("mid"))
        delta_text = plusminus.group("delta")
        if mid_match:
            mid = normalize_money_to_usd(mid_match)
            if "%" in delta_text or "percent" in delta_text.lower():
                pct = float(re.search(r"-?\d+(?:\.\d+)?", delta_text).group(0)) / 100.0  # type: ignore[union-attr]
                delta = abs(mid * pct)
            else:
                delta_match = AMOUNT_RE.search(delta_text)
                delta = normalize_money_to_usd(delta_match) if delta_match else np.nan
            if pd.notna(delta):
                out.extend(
                    [
                        _fact(doc, "guidance_revenue_mid", mid, "usd", role, segment, start, end, 0.92, "guidance_revenue_plus_minus", flags),
                        _fact(doc, "guidance_revenue_low", mid - delta, "usd", role, segment, start, end, 0.90, "guidance_revenue_plus_minus", flags),
                        _fact(doc, "guidance_revenue_high", mid + delta, "usd", role, segment, start, end, 0.90, "guidance_revenue_plus_minus", flags),
                    ]
                )
                return out

    # "revenue ... range of $6.5 billion to $6.8 billion" or "between X and Y"
    range_match = re.search(
        r"(?:revenue|net sales|sales).*?(?:range of|between)\s*(?:approximately|about)?\s*"
        r"(?P<low>\$?\s*-?\d+(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m)?)"
        r"\s*(?:to|and|-)\s*"
        r"(?P<high>\$?\s*-?\d+(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m)?)",
        segment,
        flags=re.IGNORECASE,
    )
    if range_match:
        low_match = AMOUNT_RE.search(range_match.group("low"))
        high_match = AMOUNT_RE.search(range_match.group("high"))
        if low_match and high_match:
            inferred_unit = (high_match.group("unit") or low_match.group("unit") or "").lower()
            low_val = normalize_money_to_usd(low_match, default_unit=inferred_unit)
            high_val = normalize_money_to_usd(high_match, default_unit=inferred_unit)
            if high_val < low_val:
                low_val, high_val = high_val, low_val
            mid = (low_val + high_val) / 2.0
            out.extend(
                [
                    _fact(doc, "guidance_revenue_low", low_val, "usd", role, segment, start, end, 0.88, "guidance_revenue_range", flags),
                    _fact(doc, "guidance_revenue_high", high_val, "usd", role, segment, start, end, 0.88, "guidance_revenue_range", flags),
                    _fact(doc, "guidance_revenue_mid", mid, "usd", role, segment, start, end, 0.90, "guidance_revenue_range", flags),
                ]
            )
            return out

    # Midpoint-only guidance.
    mid_match = re.search(
        r"(?:revenue|net sales|sales).*?(?:approximately|about|of|be|to be)\s*"
        r"(?P<mid>\$?\s*-?\d+(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m))",
        segment,
        flags=re.IGNORECASE,
    )
    if mid_match:
        money = AMOUNT_RE.search(mid_match.group("mid"))
        if money:
            out.append(_fact(doc, "guidance_revenue_mid", normalize_money_to_usd(money), "usd", role, segment, start, end, 0.82, "guidance_revenue_midpoint", flags))
    return out


def _parse_guidance_eps(doc: SourceDocument, segment: str, start: int, end: int) -> list[ParsedExhibitFact]:
    low = segment.lower()
    if "eps" not in low and "earnings per share" not in low:
        return []
    if not _contains_any(low, FUTURE_GUIDANCE_WORDS):
        return []
    role = _period_role(segment, "next_quarter_guidance")
    flags = ["full_year_guidance"] if role == "full_year_guidance" else []
    m = re.search(
        r"(?:eps|earnings per share).*?(?:range of|between)\s*\$?\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|and|-)\s*\$?\s*(?P<high>-?\d+(?:\.\d+)?)",
        segment,
        flags=re.IGNORECASE,
    )
    if not m:
        return []
    low_val = float(m.group("low"))
    high_val = float(m.group("high"))
    if high_val < low_val:
        low_val, high_val = high_val, low_val
    mid = (low_val + high_val) / 2.0
    return [
        _fact(doc, "guidance_eps_low", low_val, "usd_per_share", role, segment, start, end, 0.86, "guidance_eps_range", flags),
        _fact(doc, "guidance_eps_high", high_val, "usd_per_share", role, segment, start, end, 0.86, "guidance_eps_range", flags),
        _fact(doc, "guidance_eps_mid", mid, "usd_per_share", role, segment, start, end, 0.88, "guidance_eps_range", flags),
    ]


def _parse_actuals(doc: SourceDocument, segment: str, start: int, end: int) -> list[ParsedExhibitFact]:
    low = segment.lower()
    if _contains_any(low, ACTUAL_EXCLUDE_WORDS):
        return []
    if re.search(r"\brevenue\s+of\s+(?:more than|over)\b", low):
        return []
    flags: list[str] = []
    if any(w in low for w in SEGMENT_WORDS):
        flags.append("possible_segment_metric")

    out: list[ParsedExhibitFact] = []
    if "revenue" in low or "net sales" in low:
        starts_with_consolidated_revenue = low.strip().lstrip("•-* ").startswith(("revenue of", "revenues of"))
        if not flags or starts_with_consolidated_revenue or "total revenue" in low or "quarterly revenue" in low or "generated revenue" in low or "net sales" in low:
            m = re.search(
                r"(?:quarterly\s+)?(?:net\s+)?(?:revenue|revenues|net sales|sales|generated revenue)\s*(?:of|were|was|totaled|reached|:)?\s*"
                r"(?P<amount>\$?\s*-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:billion|bn|b|million|mn|m))",
                segment,
                flags=re.IGNORECASE,
            )
            if m:
                money = AMOUNT_RE.search(m.group("amount"))
                if money:
                    out.append(_fact(doc, "actual_revenue", normalize_money_to_usd(money), "usd", "current_quarter_actual", segment, start, end, 0.88, "actual_revenue_sentence", flags))

    if "gross margin" in low:
        m = PCT_RE.search(segment)
        if m:
            out.append(_fact(doc, "actual_gross_margin", float(m.group("num")) / 100.0, "fraction", "current_quarter_actual", segment, start, end, 0.82, "actual_gross_margin_sentence", flags))

    if "eps" in low or "earnings per share" in low:
        if any(w in low for w in ["defined as", "excluding:", "described further below", "tax related items"]) and not any(
            w in low for w in ["eps of $", "eps was", "earnings per share of", "diluted eps of"]
        ):
            return out
        # Prefer GAAP EPS when a sentence includes both GAAP and non-GAAP.
        m = re.search(r"(?:gaap\s+)?(?:diluted\s+)?(?:eps|earnings per share).*?\$\s*(?P<num>-?\d+(?:\.\d+)?)", segment, flags=re.IGNORECASE)
        if m:
            out.append(_fact(doc, "actual_eps", float(m.group("num")), "usd_per_share", "current_quarter_actual", segment, start, end, 0.82, "actual_eps_sentence", flags))
    return out


def _dedupe_facts(facts: list[ParsedExhibitFact]) -> list[ParsedExhibitFact]:
    best: dict[tuple[str, str], ParsedExhibitFact] = {}
    for fact in facts:
        key = (fact.fact_name, fact.period_role)
        current = best.get(key)
        # Prefer high confidence, then concise evidence. Penalize possible segment
        # metrics when a cleaner consolidated fact exists.
        score = fact.confidence - (0.08 if "possible_segment_metric" in fact.quality_flags else 0.0) - min(len(fact.evidence_text), 500) / 100000.0
        current_score = -1.0
        if current is not None:
            current_score = current.confidence - (0.08 if "possible_segment_metric" in current.quality_flags else 0.0) - min(len(current.evidence_text), 500) / 100000.0
        if current is None or score > current_score:
            best[key] = fact
    return sorted(best.values(), key=lambda f: (f.period_role, f.fact_name))


def parse_exhibit99_document(doc: SourceDocument) -> list[ParsedExhibitFact]:
    facts: list[ParsedExhibitFact] = []
    seen_segments: set[tuple[int, int, str]] = set()
    for segment, start, end in list(_sentences(doc.text)) + list(_line_segments(doc.text)):
        key = (start, end, segment)
        if key in seen_segments:
            continue
        seen_segments.add(key)
        facts.extend(_parse_guidance_revenue(doc, segment, start, end))
        facts.extend(_parse_guidance_eps(doc, segment, start, end))
        facts.extend(_parse_actuals(doc, segment, start, end))
    return _dedupe_facts(facts)


def parse_exhibit99_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    *,
    min_confidence: float = 0.0,
) -> pd.DataFrame:
    docs = load_source_documents(documents_path)
    rows: list[dict] = []
    for doc in docs:
        for fact in parse_exhibit99_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["ticker", "event_time", "event_id", "period_role", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    out.to_csv(facts_out, index=False)
    return out


def pivot_parsed_facts(facts: pd.DataFrame, out_path: str | Path | None = None, min_confidence: float = 0.80) -> pd.DataFrame:
    usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
    if usable.empty:
        out = pd.DataFrame()
    else:
        usable = usable.sort_values(["event_id", "fact_name", "period_role", "confidence"], ascending=[True, True, True, False])
        usable = usable.drop_duplicates(["event_id", "fact_name", "period_role"], keep="first")
        rows = []
        for event_id, group in usable.groupby("event_id", sort=False):
            row = {
                "event_id": event_id,
                "ticker": group["ticker"].iloc[0],
                "event_time": group["event_time"].iloc[0],
                "source_doc_ids": ";".join(sorted(group["source_doc_id"].astype(str).unique())),
                "usable_fact_count": int(len(group)),
            }
            for _, fact in group.iterrows():
                prefix = fact["fact_name"]
                role = fact["period_role"]
                if role == "next_quarter_guidance":
                    prefix = fact["fact_name"]
                elif role == "current_quarter_actual":
                    prefix = fact["fact_name"]
                else:
                    prefix = f"{role}_{fact['fact_name']}"
                row[prefix] = fact["value"]
                row[f"{prefix}_confidence"] = fact["confidence"]
                row[f"{prefix}_evidence"] = fact["evidence_text"]
            rows.append(row)
        out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def validate_parser_against_gold(facts: pd.DataFrame, gold: pd.DataFrame, out_errors: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame()
        report = {"gold_rows": 0, "status": "no_gold_rows"}
        return errors, report

    pred = facts.copy()
    pred["confidence"] = pd.to_numeric(pred["confidence"], errors="coerce")
    pred = pred.sort_values("confidence", ascending=False).drop_duplicates(["event_id", "fact_name", "period_role"], keep="first")
    key_cols = ["event_id", "fact_name", "period_role"]
    merged = gold.merge(pred, on=key_cols, how="left", suffixes=("_gold", "_pred"))
    rows = []
    tolerance_by_unit = {"usd": 1_000_000.0, "usd_per_share": 0.01, "fraction": 0.0025}
    for _, row in merged.iterrows():
        expected = pd.to_numeric(pd.Series([row.get("expected_value")]), errors="coerce").iloc[0]
        actual = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
        unit = str(row.get("unit_gold") or row.get("unit_pred") or "").strip()
        tolerance = float(row.get("tolerance") or tolerance_by_unit.get(unit, 0.0))
        if pd.isna(actual):
            status = "missed"
            abs_error = np.nan
        else:
            abs_error = abs(float(actual) - float(expected))
            status = "ok" if abs_error <= tolerance else "wrong_value"
        rows.append({**{c: row.get(c) for c in key_cols}, "expected_value": expected, "actual_value": actual, "unit": unit, "tolerance": tolerance, "abs_error": abs_error, "status": status, "evidence_text": row.get("evidence_text_pred", "")})
    errors = pd.DataFrame(rows)

    metrics = {}
    for fact_name, group in errors.groupby("fact_name"):
        total = int(len(group))
        ok = int((group["status"] == "ok").sum())
        metrics[fact_name] = {"gold_rows": total, "correct": ok, "recall_on_gold": ok / total if total else 0.0}
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": int((errors["status"] == "ok").sum()),
        "row_accuracy": float((errors["status"] == "ok").mean()) if len(errors) else 0.0,
        "by_fact": metrics,
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report
