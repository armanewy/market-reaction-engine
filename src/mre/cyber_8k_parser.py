from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .event_graph import Claim, EvidenceSpan, claim_id as make_claim_id, dataclasses_to_frame, evidence_span_id as make_evidence_span_id
from .paths import ensure_parent
from .source_docs import SourceDocument, load_source_documents


CYBER_8K_BOOLEAN_PATTERNS: dict[str, tuple[str, str, float]] = {
    "item_105_flag": (r"\bItem\s+1\.05\b|material cybersecurity incident", "regex_cyber_item_105", 0.96),
    "amendment_flag": (r"\b8-K/A\b|\bamendment\b|\bupdates?\b|\bupdated\b", "regex_cyber_amendment", 0.86),
    "ransomware_mentioned": (r"\bransomware\b|\bransom\b|\bextortion\b|\bencrypt(?:ed|ion)\b", "regex_cyber_ransomware", 0.90),
    "customer_data_exposure_mentioned": (
        r"customer data|client data|consumer data|personal information|personally identifiable|data breach|exfiltrat(?:ed|ion)",
        "regex_cyber_customer_data",
        0.86,
    ),
    "operational_disruption_mentioned": (
        r"operational disruption|business interruption|systems? offline|disrupt(?:ed|ion)|operations? (?:were )?(?:affected|interrupted)",
        "regex_cyber_operational_disruption",
        0.88,
    ),
    "third_party_vendor_mentioned": (
        r"third[- ]party|vendor|supplier|service provider|third party provider",
        "regex_cyber_third_party_vendor",
        0.84,
    ),
    "impact_unknown_or_not_determined": (
        r"impact (?:has )?not (?:yet )?been determined|unable to determine|cannot determine|continues? to assess|still assessing|not yet determined",
        "regex_cyber_impact_unknown",
        0.88,
    ),
    "no_material_impact_language": (
        r"did not have a material impact|not (?:reasonably )?likely to materially impact|no material impact|not expected to have a material",
        "regex_cyber_no_material_impact",
        0.91,
    ),
    "reasonably_likely_material_impact_language": (
        r"reasonably likely to materially impact|reasonably likely to have a material impact|materially impact(?:ed)?",
        "regex_cyber_reasonably_likely_material",
        0.84,
    ),
}

CYBER_8K_LANGUAGE_PATTERNS: dict[str, tuple[str, str, float]] = {
    "financial_impact_language": (
        r"financial impact|results of operations|financial condition|revenue|costs?|expenses?|material impact",
        "regex_cyber_financial_impact_language",
        0.80,
    ),
    "materiality_language": (
        r"determined .*?material|material cybersecurity incident|material impact|materially impact",
        "regex_cyber_materiality_language",
        0.82,
    ),
}

CYBER_8K_DATE_PATTERNS: dict[str, tuple[str, str, float]] = {
    "incident_discovery_date": (
        r"(?:on|as of)\s+([A-Z][a-z]+ \d{1,2}, \d{4}).{0,80}?(?:became aware|discovered|identified|detected)",
        "regex_cyber_incident_discovery_date",
        0.78,
    ),
    "materiality_determination_date": (
        r"(?:on|as of)\s+([A-Z][a-z]+ \d{1,2}, \d{4}).{0,120}?(?:determined|concluded).{0,80}?material",
        "regex_cyber_materiality_determination_date",
        0.82,
    ),
}


@dataclass
class Cyber8KParseDiagnostics:
    documents_total: int = 0
    documents_with_claims: int = 0
    claims_total: int = 0
    counts_by_field: dict[str, int] = field(default_factory=dict)
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_claim(self, field_name: str) -> None:
        self.claims_total += 1
        self.counts_by_field[field_name] = self.counts_by_field.get(field_name, 0) + 1

    def add_skip(self, reason: str) -> None:
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def _get(doc: SourceDocument | Mapping[str, Any], key: str, default: object = "") -> object:
    if isinstance(doc, SourceDocument):
        return getattr(doc, key, default)
    return doc.get(key, default)


def _norm(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left_candidates = [text.rfind(ch, 0, start) for ch in ".!?\n"]
    left = max(left_candidates)
    left = 0 if left < 0 else left + 1
    right_candidates = [idx for ch in ".!?\n" if (idx := text.find(ch, end)) != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return left, right


def _evidence_for_match(text: str, match: re.Match[str]) -> tuple[str, int, int]:
    start, end = _sentence_bounds(text, match.start(), match.end())
    evidence = re.sub(r"\s+", " ", text[start:end]).strip()
    leading_ws = len(text[start:end]) - len(text[start:end].lstrip())
    trailing_ws = len(text[start:end]) - len(text[start:end].rstrip())
    return evidence, start + leading_ws, end - trailing_ws


def _date_value(raw: str) -> str:
    parsed = pd.to_datetime(raw, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def _make_claim_and_span(
    *,
    doc: SourceDocument | Mapping[str, Any],
    field_name: str,
    value: object,
    value_type: str,
    confidence: float,
    method: str,
    evidence_text: str,
    start_char: int,
    end_char: int,
) -> tuple[Claim, EvidenceSpan]:
    event_id = _norm(_get(doc, "event_id"))
    source_doc_id = _norm(_get(doc, "source_doc_id"))
    cid = make_claim_id(event_id, field_name, evidence_text or value)
    sid = make_evidence_span_id(source_doc_id, start_char, end_char)
    claim = Claim(
        claim_id=cid,
        event_id=event_id,
        field_name=field_name,
        value=value,
        value_type=value_type,
        confidence=confidence,
        method=method,
        evidence_span_id=sid,
        source_doc_id=source_doc_id,
    )
    span = EvidenceSpan(
        evidence_span_id=sid,
        source_doc_id=source_doc_id,
        claim_id=cid,
        evidence_text=evidence_text,
        start_char=start_char,
        end_char=end_char,
        source_url=_norm(_get(doc, "source_url")),
    )
    return claim, span


def parse_cyber_8k_document(doc: SourceDocument | Mapping[str, Any]) -> tuple[list[Claim], list[EvidenceSpan]]:
    text = _norm(_get(doc, "text"))
    if not text:
        return [], []
    claims: list[Claim] = []
    spans: list[EvidenceSpan] = []

    for field_name, (pattern, method, confidence) in CYBER_8K_BOOLEAN_PATTERNS.items():
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        evidence_text, start_char, end_char = _evidence_for_match(text, match)
        claim, span = _make_claim_and_span(
            doc=doc,
            field_name=field_name,
            value=True,
            value_type="boolean",
            confidence=confidence,
            method=method,
            evidence_text=evidence_text,
            start_char=start_char,
            end_char=end_char,
        )
        claims.append(claim)
        spans.append(span)

    for field_name, (pattern, method, confidence) in CYBER_8K_LANGUAGE_PATTERNS.items():
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        evidence_text, start_char, end_char = _evidence_for_match(text, match)
        claim, span = _make_claim_and_span(
            doc=doc,
            field_name=field_name,
            value=evidence_text,
            value_type="string",
            confidence=confidence,
            method=method,
            evidence_text=evidence_text,
            start_char=start_char,
            end_char=end_char,
        )
        claims.append(claim)
        spans.append(span)

    for field_name, (pattern, method, confidence) in CYBER_8K_DATE_PATTERNS.items():
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        date_value = _date_value(match.group(1))
        if not date_value:
            continue
        evidence_text, start_char, end_char = _evidence_for_match(text, match)
        claim, span = _make_claim_and_span(
            doc=doc,
            field_name=field_name,
            value=date_value,
            value_type="date",
            confidence=confidence,
            method=method,
            evidence_text=evidence_text,
            start_char=start_char,
            end_char=end_char,
        )
        claims.append(claim)
        spans.append(span)

    return claims, spans


def parse_cyber_8k_documents(docs: Iterable[SourceDocument]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    diagnostics = Cyber8KParseDiagnostics()
    claim_rows: list[Claim] = []
    evidence_rows: list[EvidenceSpan] = []
    for doc in docs:
        diagnostics.documents_total += 1
        claims, spans = parse_cyber_8k_document(doc)
        if claims:
            diagnostics.documents_with_claims += 1
        else:
            diagnostics.add_skip("no_claims_with_evidence")
        claim_rows.extend(claims)
        evidence_rows.extend(spans)
        for claim in claims:
            diagnostics.add_claim(claim.field_name)

    claims_df = dataclasses_to_frame(claim_rows)
    evidence_df = dataclasses_to_frame(evidence_rows)
    return claims_df, evidence_df, diagnostics.to_dict()


def run_cyber_8k_parse_manifest(
    documents_manifest,
    *,
    claims_out=None,
    evidence_out=None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    docs = load_source_documents(documents_manifest)
    claims_df, evidence_df, diagnostics = parse_cyber_8k_documents(docs)
    if claims_out is not None:
        ensure_parent(claims_out)
        claims_df.to_csv(claims_out, index=False)
    if evidence_out is not None:
        ensure_parent(evidence_out)
        evidence_df.to_csv(evidence_out, index=False)
    return claims_df, evidence_df, diagnostics
