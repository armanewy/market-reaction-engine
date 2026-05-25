from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import pandas as pd

from .event_graph import Claim, EvidenceSpan, claim_id as make_claim_id, evidence_span_id as make_evidence_span_id
from .source_docs import SourceDocument


CYBER_8K_BOOLEAN_PATTERNS: dict[str, tuple[str, str, float]] = {
    "item_105_flag": (r"\bItem\s+1\.05\b|material cybersecurity incident", "regex_cyber_item_105", 0.96),
    "ransomware_mentioned": (r"\bransomware\b|\bransom\b|\bextortion\b|\bencrypt(?:ed|ion)\b", "regex_cyber_ransomware", 0.90),
    "customer_data_exposure_mentioned": (
        r"customer (?:data|information|records)|client (?:data|information|records)|consumer (?:data|information|records)|"
        r"patient (?:data|information|records)|member (?:data|information|records)|protected health information|\bPHI\b|"
        r"personally identifiable information|\bPII\b|personal information",
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
        r"did not have a material impact|has not had.{0,80}?material impact|has not materially impacted|"
        r"not (?:reasonably )?likely to materially impact|not reasonably likely to have a material impact|"
        r"not expected to have a material|does not currently expect.{0,80}?material impact|no material impact",
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
        r"determined .*?material|material impact|materially impact",
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


def _metadata_text(doc: SourceDocument | Mapping[str, Any]) -> str:
    keys = ("form", "title", "source_doc_id", "source_url", "path", "notes", "source_type")
    return " ".join(_norm(_get(doc, key)) for key in keys)


def _amendment_evidence(doc: SourceDocument | Mapping[str, Any], text: str) -> tuple[str, int, int] | None:
    form = _norm(_get(doc, "form")).upper()
    metadata = _metadata_text(doc)
    text_match = re.search(r"\bFORM\s+8-K/A\b|\b8-K/A\b", text, flags=re.I)
    metadata_has_amendment = bool(
        form == "8-K/A"
        or re.search(r"\bFORM\s+8-K/A\b|\b8-K/A\b|_8-K_A_|-8-K-A-|8ka\b", metadata, flags=re.I)
        or text_match
    )
    if not metadata_has_amendment:
        return None

    if text_match:
        return _evidence_for_match(text, text_match)

    metadata_match = re.search(r"\bFORM\s+8-K/A\b|\b8-K/A\b|_8-K_A_|-8-K-A-|8ka\b", metadata, flags=re.I)
    evidence = metadata_match.group(0) if metadata_match else "form=8-K/A"
    return evidence, 0, 0


def _is_customer_data_evidence(evidence_text: str) -> bool:
    lowered = evidence_text.lower()
    explicit_customer_terms = (
        "customer",
        "client",
        "consumer",
        "patient",
        "member",
        "protected health information",
        "personally identifiable information",
        " phi",
        "pii",
        "personal information",
    )
    if not any(term in lowered for term in explicit_customer_terms):
        return False
    if "employee" in lowered and not any(
        term in lowered
        for term in (
            "customer",
            "client",
            "consumer",
            "patient",
            "member",
            "protected health information",
            "personally identifiable information",
            " phi",
            "pii",
        )
    ):
        return False
    return True


def _is_no_or_unknown_material_impact(evidence_text: str) -> bool:
    lowered = re.sub(r"\s+", " ", evidence_text.lower())
    return bool(
        re.search(
            r"not (?:yet )?determined (?:whether|that)?.{0,120}?(?:reasonably likely|materially impact|material impact)|"
            r"not reasonably likely.{0,80}?(?:materially impact|material impact)|"
            r"not expected.{0,80}?material impact|"
            r"does not currently expect.{0,80}?material impact|"
            r"has not had.{0,80}?material impact|"
            r"did not have.{0,80}?material impact|"
            r"has not materially impacted|"
            r"no material impact",
            lowered,
        )
    )


def _is_heading_only_materiality(evidence_text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9. ]+", " ", evidence_text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    normalized = re.sub(r"^item\s+1\.05\s+", "", normalized).strip(" .")
    return normalized in {"material cybersecurity incident", "material cybersecurity incidents"}


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

    amendment_evidence = _amendment_evidence(doc, text)
    if amendment_evidence is not None:
        evidence_text, start_char, end_char = amendment_evidence
        claim, span = _make_claim_and_span(
            doc=doc,
            field_name="amendment_flag",
            value=True,
            value_type="boolean",
            confidence=0.86,
            method="regex_cyber_amendment",
            evidence_text=evidence_text,
            start_char=start_char,
            end_char=end_char,
        )
        claims.append(claim)
        spans.append(span)

    for field_name, (pattern, method, confidence) in CYBER_8K_BOOLEAN_PATTERNS.items():
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        evidence_text, start_char, end_char = _evidence_for_match(text, match)
        if field_name == "customer_data_exposure_mentioned" and not _is_customer_data_evidence(evidence_text):
            continue
        if field_name == "reasonably_likely_material_impact_language" and _is_no_or_unknown_material_impact(evidence_text):
            continue
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
        if field_name == "materiality_language" and _is_heading_only_materiality(evidence_text):
            continue
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
