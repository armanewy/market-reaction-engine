from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .events import make_event_template
from .ingestion import IngestionDiagnostics, build_sec_source_document_manifest
from .paths import ensure_parent
from .prices import load_price_csv
from .sec import SecClient
from .source_docs import SourceDocument, load_source_documents


ACTIVIST_13D_DOMAIN = "activist_13d_control_intent"

ACTIVIST_13D_FORMS = ("SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A")
ACTIVIST_13D_EVENT_TYPES = {
    "initial_activist_13d",
    "control_intent_13d",
    "strategic_alternatives_13d",
    "board_seat_campaign",
    "sale_pressure",
    "passive_or_ambiguous_13d",
    "ownership_increase_amendment",
    "ownership_decrease_amendment",
    "exit_amendment",
    "passive_13g_control",
}

ACTIVIST_13D_FACT_COLUMNS = [
    "source_doc_id",
    "event_id",
    "ticker",
    "event_time",
    "fact_name",
    "value",
    "unit",
    "evidence_text",
    "confidence",
    "parse_method",
    "source_type",
    "source_url",
]

ACTIVIST_13D_FEATURE_COLUMNS = [
    "event_id",
    "ticker",
    "event_time",
    "source_doc_ids",
    "source_type",
    "source_url",
    "source_evidence_text",
    "activist_13d_event_type",
    "beneficial_owner_name",
    "ownership_pct",
    "shares_owned",
    "filing_type",
    "initial_or_amendment",
    "item_4_purpose_text",
    "activist_language_flag",
    "board_language_flag",
    "sale_or_strategic_alternatives_flag",
    "control_intent_flag",
    "passive_language_flag",
    "ownership_change_pct",
    "financing_source_of_funds",
    "agreements_exhibits",
    "activist_known_name_flag",
    "confidence",
    "evidence_status",
    "parser_quality_flags",
    "label_quality",
    "review_status",
    "hard_negative_flag",
    "hard_negative_reason",
    "event_direction_pre_price",
    "materiality_pre_price",
    "market_cap_before_event",
    "pre_event_market_adjusted_return_20d",
    "pre_event_market_adjusted_return_60d",
    "company_size_bucket",
    "prior_13d_activity",
    "float_or_liquidity_context",
    "execution_survivability_class",
    "execution_survivability_reason",
    "first_realistic_entry",
    "tradeability_after_first_entry_rationale",
    "next_open_required_flag",
    "close_to_close_explanatory_only_flag",
    "sector_benchmark",
]

KNOWN_ACTIVIST_TERMS = {
    "elliott",
    "starboard",
    "valueact",
    "carl icahn",
    "icahn",
    "pershing square",
    "third point",
    "jana",
    "engine capital",
    "ancora",
    "legion partners",
    "land & buildings",
    "sachem head",
    "corvex",
}

BOARD_TERMS = (
    "board",
    "director",
    "nominate",
    "nomination",
    "proxy contest",
    "proxy solicitation",
    "board seat",
    "replace directors",
)
SALE_TERMS = (
    "strategic alternative",
    "strategic alternatives",
    "sale of the company",
    "sell the company",
    "merger",
    "business combination",
    "takeover",
    "acquisition proposal",
)
CONTROL_TERMS = (
    "influence control",
    "seek control",
    "change in control",
    "control of the issuer",
    "control intent",
    "effect changes",
    "enhance shareholder value",
    "maximize shareholder value",
    "engage with management",
)
PASSIVE_TERMS = (
    "investment purposes",
    "passive investment",
    "no present plan",
    "does not have any plans or proposals",
    "ordinary course",
)
NO_CHANGE_TERMS = (
    "no material change",
    "no change in intent",
    "amendment is being filed solely",
    "solely to report",
)
SOURCE_OF_FUNDS_RE = re.compile(
    r"item\s*3\.?\s*(?:source\s+and\s+amount\s+of\s+funds|source\s+of\s+funds).*?(?=item\s*[4-7]\.?)",
    re.I | re.S,
)


@dataclass(frozen=True)
class Activist13DFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: str | float | bool
    unit: str
    evidence_text: str
    confidence: float
    parse_method: str
    source_type: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return default
    return text or default


def _norm_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _contains_any(text: str, terms: tuple[str, ...] | set[str]) -> bool:
    low = text.lower()
    return any(term in low for term in terms)


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _segments(text: str) -> list[str]:
    out = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 8 <= len(seg) <= 900:
            out.append(seg)
    return out


def _first_segment(text: str, patterns: list[str]) -> str:
    for seg in _segments(text):
        if any(re.search(pattern, seg, flags=re.I) for pattern in patterns):
            return seg
    return ""


def _fact(doc: SourceDocument, name: str, value: str | float | bool, unit: str, evidence: str, confidence: float, method: str) -> Activist13DFact:
    return Activist13DFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        evidence_text=_norm_space(evidence),
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=method,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def infer_filing_type(doc: SourceDocument) -> str:
    subtype = _norm(doc.event_subtype).upper()
    title = _norm(doc.title).upper()
    text_head = _norm(doc.text[:4000]).upper()
    combined = " ".join([subtype, title, text_head])
    for form in ("SC 13D/A", "SC 13G/A", "SC 13D", "SC 13G"):
        if form in combined:
            return form
    if "SCHEDULE 13D" in combined:
        return "SC 13D/A" if "AMENDMENT" in combined else "SC 13D"
    if "SCHEDULE 13G" in combined:
        return "SC 13G/A" if "AMENDMENT" in combined else "SC 13G"
    return subtype if subtype.startswith("SC 13") else "unknown"


def extract_item_4(text: str) -> str:
    patterns = [
        r"item\s*4\.?\s*(?:purpose\s+of\s+transaction)?(?P<body>.*?)(?=item\s*5\.?\s*(?:interest|interest\s+in\s+securities)|item\s*6\.?|signature\b)",
        r"purpose\s+of\s+transaction(?P<body>.*?)(?=interest\s+in\s+securities|contracts|arrangements|signature\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.I | re.S)
        if match:
            return _norm_space(match.group("body"))
    return ""


def extract_reporting_owner(text: str, title: str = "") -> tuple[str, str, float]:
    candidates = [
        r"name\s+of\s+reporting\s+person(?:s)?\s*[:\-\n]\s*(?P<name>[A-Z0-9][A-Za-z0-9 .,&'/-]{2,120})",
        r"filed\s+by\s+(?P<name>[A-Z0-9][A-Za-z0-9 .,&'/-]{2,120})",
        r"beneficial\s+owner\s*[:\-\n]\s*(?P<name>[A-Z0-9][A-Za-z0-9 .,&'/-]{2,120})",
    ]
    search_text = "\n".join([title, str(text or "")[:8000]])
    for pattern in candidates:
        match = re.search(pattern, search_text, flags=re.I)
        if match:
            name = _norm_space(match.group("name"))
            name = re.split(r"\s{2,}|CUSIP|Item\s+\d", name, flags=re.I)[0].strip(" :-")
            return name, match.group(0), 0.82
    return "", "", 0.0


def extract_ownership_pct(text: str) -> tuple[float, str, float]:
    patterns = [
        r"(?:representing|constituting|represents)\s+(?P<pct>\d+(?:\.\d+)?)\s*%",
        r"percent\s+of\s+class\s+(?:represented\s+by\s+amount\s+in\s+row\s+11)?\s*[:\-\n]?\s*(?P<pct>\d+(?:\.\d+)?)\s*%",
        r"(?P<pct>\d+(?:\.\d+)?)\s*%\s+of\s+(?:the\s+)?(?:outstanding\s+)?(?:common\s+stock|shares)",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.I)
        if match:
            return float(match.group("pct")), match.group(0), 0.86
    return np.nan, "", 0.0


def extract_shares_owned(text: str) -> tuple[float, str, float]:
    patterns = [
        r"beneficially\s+own(?:s|ed)?\s+(?P<shares>\d{1,3}(?:,\d{3})+|\d+)\s+shares",
        r"aggregate\s+amount\s+beneficially\s+owned\s*[:\-\n]?\s*(?P<shares>\d{1,3}(?:,\d{3})+|\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.I)
        if match:
            return float(match.group("shares").replace(",", "")), match.group(0), 0.82
    return np.nan, "", 0.0


def extract_ownership_change_pct(text: str) -> tuple[float, str, float]:
    low_text = str(text or "")
    pair = re.search(r"(?:from|previously)\s+(?P<old>\d+(?:\.\d+)?)\s*%.*?(?:to|currently|now)\s+(?P<new>\d+(?:\.\d+)?)\s*%", low_text, flags=re.I | re.S)
    if pair:
        return float(pair.group("new")) - float(pair.group("old")), pair.group(0), 0.80
    increase = re.search(r"increased\s+by\s+(?P<chg>\d+(?:\.\d+)?)\s*(?:percentage\s+points|%)", low_text, flags=re.I)
    if increase:
        return float(increase.group("chg")), increase.group(0), 0.72
    decrease = re.search(r"decreased\s+by\s+(?P<chg>\d+(?:\.\d+)?)\s*(?:percentage\s+points|%)", low_text, flags=re.I)
    if decrease:
        return -float(decrease.group("chg")), decrease.group(0), 0.72
    return np.nan, "", 0.0


def extract_source_of_funds(text: str) -> tuple[str, str, float]:
    match = SOURCE_OF_FUNDS_RE.search(str(text or ""))
    body = _norm_space(match.group(0)) if match else ""
    if not body:
        body = _first_segment(text, [r"working\s+capital", r"personal\s+funds", r"margin\s+loan", r"borrowed\s+funds"])
    if not body:
        return "", "", 0.0
    low = body.lower()
    if "working capital" in low:
        value = "working_capital"
    elif "personal funds" in low or "personal fund" in low:
        value = "personal_funds"
    elif "margin" in low or "loan" in low or "borrow" in low:
        value = "financing_or_margin"
    else:
        value = "other_or_unclear"
    return value, body[:700], 0.70


def _known_activist(owner: str) -> bool:
    low = owner.lower()
    return any(term in low for term in KNOWN_ACTIVIST_TERMS)


def classify_execution_survivability(event_type: str, release_session: str = "unknown") -> dict[str, object]:
    event_type = _norm(event_type).lower()
    release_session = _norm(release_session, "unknown").lower()
    if event_type in {"board_seat_campaign", "sale_pressure", "strategic_alternatives_13d", "control_intent_13d"}:
        klass = "delayed-digestion"
        reason = "Control, board, or sale-pressure Item 4 language can require investors to digest campaign credibility, ownership, target vulnerability, and settlement odds beyond the first print."
    elif event_type in {"initial_activist_13d", "ownership_increase_amendment"}:
        klass = "slow-burn repricing"
        reason = "Initial active ownership and accumulation amendments may remain tradeable if the market underreacts to ownership scale, activist reputation, and follow-on engagement path."
    elif event_type in {"passive_13g_control", "passive_or_ambiguous_13d"}:
        klass = "explanation-only"
        reason = "Passive or ambiguous ownership filings may explain same-day moves but lack a pre-registered tradable catalyst unless next-open behavior independently survives."
    elif event_type in {"ownership_decrease_amendment", "exit_amendment"}:
        klass = "immediate-gap"
        reason = "Exit and ownership-decrease amendments are likely to be incorporated quickly at first tradable entry and should be treated as tradable only if next-open evidence survives stress."
    else:
        klass = "pre-event setup"
        reason = "The filing is a setup candidate requiring source review before any tradeability claim."
    first_entry = "next_open" if release_session == "after_close" else "same_day_open_or_next_open" if release_session == "before_open" else "first_liquid_trade_after_acceptance"
    return {
        "execution_survivability_class": klass,
        "execution_survivability_reason": reason,
        "first_realistic_entry": first_entry,
        "tradeability_after_first_entry_rationale": reason,
        "next_open_required_flag": True,
        "close_to_close_explanatory_only_flag": klass == "explanation-only",
    }


def classify_activist_13d(
    *,
    filing_type: str,
    initial_or_amendment: str,
    item_4: str,
    ownership_change_pct: float,
    ownership_pct: float,
    owner: str,
) -> tuple[str, dict[str, object]]:
    low = item_4.lower()
    is_13g = "13G" in filing_type.upper()
    activist = _contains_any(low, CONTROL_TERMS) or _known_activist(owner)
    board = _contains_any(low, BOARD_TERMS)
    board_campaign = bool(re.search(r"\b(nominate|nomination|proxy contest|proxy solicitation|board seat|replace directors)\b", low))
    sale = _contains_any(low, SALE_TERMS)
    passive = _contains_any(low, PASSIVE_TERMS)
    no_change = _contains_any(low, NO_CHANGE_TERMS)
    exit_flag = bool(re.search(r"cease(?:d|s)?\s+to\s+be\s+(?:the\s+|a\s+)?beneficial\s+owner|less\s+than\s+5\s*%|more\s+than\s+five\s+percent", low))
    founder_or_insider = bool(re.search(r"\bfounder\b|\bchief executive\b|\bceo\b|\bofficer\b|\bdirector\b", low)) and not (activist or sale or board)
    tiny_change = pd.notna(ownership_change_pct) and abs(float(ownership_change_pct)) < 0.5

    hard_negative_reason = ""
    if is_13g:
        event_type = "passive_13g_control"
        hard_negative_reason = "SC 13G passive/control filing is not an activist 13D signal"
    elif exit_flag:
        event_type = "exit_amendment"
        hard_negative_reason = "amendment reports exit or sub-5% beneficial ownership"
    elif initial_or_amendment == "amendment" and pd.notna(ownership_change_pct) and float(ownership_change_pct) < 0:
        event_type = "ownership_decrease_amendment"
        hard_negative_reason = "13D/A ownership decrease"
    elif initial_or_amendment == "amendment" and (no_change or tiny_change) and not (board or sale or activist):
        event_type = "passive_or_ambiguous_13d"
        hard_negative_reason = "amendment has no new control intent or only tiny ownership change"
    elif founder_or_insider:
        event_type = "passive_or_ambiguous_13d"
        hard_negative_reason = "founder/insider language without activist control intent"
    elif sale:
        event_type = "sale_pressure" if "sale" in low or "sell the company" in low else "strategic_alternatives_13d"
    elif board_campaign:
        event_type = "board_seat_campaign"
    elif activist and _contains_any(low, CONTROL_TERMS):
        event_type = "control_intent_13d"
    elif initial_or_amendment == "amendment" and pd.notna(ownership_change_pct) and float(ownership_change_pct) > 0:
        event_type = "ownership_increase_amendment"
    elif activist:
        event_type = "initial_activist_13d"
    else:
        event_type = "passive_or_ambiguous_13d"
        if passive or not item_4:
            hard_negative_reason = "passive or ambiguous 13D Item 4 language"

    flags = {
        "activist_language_flag": bool(activist),
        "board_language_flag": bool(board),
        "sale_or_strategic_alternatives_flag": bool(sale),
        "control_intent_flag": bool(activist and (_contains_any(low, CONTROL_TERMS) or board or sale)),
        "passive_language_flag": bool(passive),
        "hard_negative_flag": bool(event_type in {"passive_13g_control", "ownership_decrease_amendment", "exit_amendment"} or hard_negative_reason),
        "hard_negative_reason": hard_negative_reason,
    }
    return event_type, flags


def parse_activist_13d_document(doc: SourceDocument) -> list[Activist13DFact]:
    filing_type = infer_filing_type(doc)
    initial_or_amendment = "amendment" if filing_type.endswith("/A") or "amendment" in doc.text[:2000].lower() else "initial"
    item_4 = extract_item_4(doc.text)
    owner, owner_evidence, owner_conf = extract_reporting_owner(doc.text, doc.title)
    ownership_pct, pct_evidence, pct_conf = extract_ownership_pct(doc.text)
    shares_owned, shares_evidence, shares_conf = extract_shares_owned(doc.text)
    ownership_change_pct, change_evidence, change_conf = extract_ownership_change_pct(doc.text)
    source_of_funds, funds_evidence, funds_conf = extract_source_of_funds(doc.text)
    agreements = _first_segment(doc.text, [r"agreement", r"letter agreement", r"joint filing agreement", r"cooperation agreement"])
    event_type, flags = classify_activist_13d(
        filing_type=filing_type,
        initial_or_amendment=initial_or_amendment,
        item_4=item_4,
        ownership_change_pct=ownership_change_pct,
        ownership_pct=ownership_pct,
        owner=owner,
    )

    evidence = item_4[:900] or doc.text[:900]
    facts = [
        _fact(doc, "filing_type", filing_type, "category", doc.title or doc.text[:120], 0.92 if filing_type != "unknown" else 0.2, "form_inference"),
        _fact(doc, "initial_or_amendment", initial_or_amendment, "category", doc.title or doc.text[:120], 0.88, "form_inference"),
        _fact(doc, "activist_13d_event_type", event_type, "category", evidence, 0.78 if item_4 else 0.55, "item4_rule_classifier"),
        _fact(doc, "item_4_purpose_text", item_4, "text", item_4[:900], 0.90 if item_4 else 0.0, "item4_section_extract"),
        _fact(doc, "activist_language_flag", flags["activist_language_flag"], "boolean", evidence, 0.78, "item4_terms"),
        _fact(doc, "board_language_flag", flags["board_language_flag"], "boolean", evidence, 0.82, "item4_terms"),
        _fact(doc, "sale_or_strategic_alternatives_flag", flags["sale_or_strategic_alternatives_flag"], "boolean", evidence, 0.82, "item4_terms"),
        _fact(doc, "control_intent_flag", flags["control_intent_flag"], "boolean", evidence, 0.78, "item4_terms"),
        _fact(doc, "passive_language_flag", flags["passive_language_flag"], "boolean", evidence, 0.72, "item4_terms"),
        _fact(doc, "hard_negative_flag", flags["hard_negative_flag"], "boolean", evidence, 0.78, "hard_negative_taxonomy"),
        _fact(doc, "hard_negative_reason", flags["hard_negative_reason"], "text", evidence, 0.78 if flags["hard_negative_reason"] else 0.0, "hard_negative_taxonomy"),
    ]
    if owner:
        facts.append(_fact(doc, "beneficial_owner_name", owner, "text", owner_evidence, owner_conf, "reporting_owner_regex"))
        facts.append(_fact(doc, "activist_known_name_flag", _known_activist(owner), "boolean", owner_evidence, 0.70, "known_activist_terms"))
    if pd.notna(ownership_pct):
        facts.append(_fact(doc, "ownership_pct", ownership_pct, "percent", pct_evidence, pct_conf, "ownership_pct_regex"))
    if pd.notna(shares_owned):
        facts.append(_fact(doc, "shares_owned", shares_owned, "shares", shares_evidence, shares_conf, "shares_owned_regex"))
    if pd.notna(ownership_change_pct):
        facts.append(_fact(doc, "ownership_change_pct", ownership_change_pct, "percentage_points", change_evidence, change_conf, "ownership_change_regex"))
    if source_of_funds:
        facts.append(_fact(doc, "financing_source_of_funds", source_of_funds, "category", funds_evidence, funds_conf, "item3_terms"))
    if agreements:
        facts.append(_fact(doc, "agreements_exhibits", agreements, "text", agreements, 0.62, "agreement_terms"))
    return facts


def pivot_activist_13d_facts(facts: pd.DataFrame, out_path: str | Path | None = None, *, min_confidence: float = 0.60) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame(columns=ACTIVIST_13D_FEATURE_COLUMNS)
    else:
        usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
        rows = []
        for event_id, group in usable.groupby("event_id", sort=False):
            row = {
                "event_id": event_id,
                "ticker": group["ticker"].iloc[0],
                "event_time": group["event_time"].iloc[0],
                "source_doc_ids": ";".join(sorted(group["source_doc_id"].astype(str).unique())),
                "source_type": group["source_type"].iloc[0],
                "source_url": group["source_url"].iloc[0],
                "source_evidence_text": "",
                "confidence": float(pd.to_numeric(group["confidence"], errors="coerce").mean()),
                "evidence_status": "source_backed",
                "parser_quality_flags": "",
                "label_quality": "machine_candidate",
                "review_status": "unreviewed",
            }
            ranked = group.sort_values("confidence", ascending=False).drop_duplicates("fact_name")
            evidence_parts = []
            for _, fact in ranked.iterrows():
                name = str(fact["fact_name"])
                row[name] = fact["value"]
                row[f"{name}_confidence"] = fact["confidence"]
                row[f"{name}_evidence"] = fact["evidence_text"]
                if len(evidence_parts) < 4 and _norm(fact.get("evidence_text")):
                    evidence_parts.append(_norm(fact.get("evidence_text"))[:240])
            row["source_evidence_text"] = " | ".join(evidence_parts)
            hard_reason = _norm(row.get("hard_negative_reason"))
            flags = []
            if _bool_value(row.get("hard_negative_flag", False)):
                flags.append("hard_negative")
            if not _norm(row.get("item_4_purpose_text")) and "13G" not in _norm(row.get("filing_type")).upper():
                flags.append("missing_item4")
            if hard_reason:
                flags.append(hard_reason.replace(" ", "_")[:80])
            row["parser_quality_flags"] = ";".join(flags)
            event_type = _norm(row.get("activist_13d_event_type"), "passive_or_ambiguous_13d")
            row["event_direction_pre_price"] = "negative" if event_type in {"ownership_decrease_amendment", "exit_amendment"} else "unknown" if event_type in {"passive_or_ambiguous_13d", "passive_13g_control"} else "positive"
            row["materiality_pre_price"] = "high" if event_type in {"board_seat_campaign", "sale_pressure", "strategic_alternatives_13d", "control_intent_13d"} else "medium" if event_type == "initial_activist_13d" else "low"
            row.update(classify_execution_survivability(event_type, row.get("release_session", "unknown")))
            rows.append(row)
        out = pd.DataFrame(rows)
        for col in ACTIVIST_13D_FEATURE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.Series(dtype=object)
        out = out[ACTIVIST_13D_FEATURE_COLUMNS + [c for c in out.columns if c not in ACTIVIST_13D_FEATURE_COLUMNS]]
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def activist_13d_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows = []
    for _, row in features.iterrows():
        event_type = _norm(row.get("activist_13d_event_type"), "passive_or_ambiguous_13d")
        ticker = _norm(row.get("ticker")).upper()
        materiality = {"high": 0.75, "medium": 0.55, "low": 0.25}.get(_norm(row.get("materiality_pre_price"), "low"), 0.45)
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "event_time": row["event_time"],
                "event_type": "ownership",
                "summary": f"{ticker} {event_type.replace('_', ' ')} candidate from Schedule 13D/13G source document.",
                "event_subtype": event_type,
                "event_family": ACTIVIST_13D_DOMAIN,
                "source_type": row.get("source_type", "sec_filing"),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": row.get("event_direction_pre_price", "unknown"),
                "surprise_magnitude": row.get("materiality_pre_price", "unknown"),
                "materiality": materiality,
                "sector_benchmark": row.get("sector_benchmark", ""),
                "notes": "Activist 13D parser candidate; review Item 4 intent, passive/hard-negative status, exact acceptance timestamp, duplicate accession, ownership context, and prior run-up before modeling.",
                **{
                    c: row.get(c, "")
                    for c in features.columns
                    if c not in {"ticker", "event_id", "event_time", "source_type", "source_url", "sector_benchmark"}
                },
            }
        )
    make_event_template(out_path, rows)
    out = pd.read_csv(out_path)
    for col in ACTIVIST_13D_FEATURE_COLUMNS:
        if col not in out.columns:
            out[col] = pd.Series(dtype=object)
    out.to_csv(out_path, index=False)
    return out


def parse_activist_13d_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
    *,
    min_confidence: float = 0.0,
    usable_confidence: float = 0.60,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(documents_path)
    rows = []
    for doc in docs:
        for fact in parse_activist_13d_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows, columns=ACTIVIST_13D_FACT_COLUMNS if not rows else None)
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    features = pivot_activist_13d_facts(facts, features_out, min_confidence=usable_confidence)
    events = activist_13d_features_to_events(features, events_out)
    return facts, features, events


def _combine_diagnostics(target: IngestionDiagnostics, source: IngestionDiagnostics) -> None:
    target.rows_total += source.rows_total
    target.rows_written += source.rows_written
    target.rows_skipped += source.rows_skipped
    target.downloaded += source.downloaded
    target.local_files_read += source.local_files_read
    target.inline_rows_read += source.inline_rows_read
    target.text_chars_total += source.text_chars_total
    for reason, count in source.skipped_reasons.items():
        target.skipped_reasons[reason] = target.skipped_reasons.get(reason, 0) + int(count)


def build_activist_13d_sec_source_documents(
    client: SecClient,
    tickers: list[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    start: str | None = "2015-01-01",
    end: str | None = None,
    forms: list[str] | None = None,
    limit_per_ticker: int | None = None,
    sector_benchmark: str = "",
    overwrite: bool = False,
    min_text_chars: int = 80,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    forms = [f.upper().strip() for f in (forms or list(ACTIVIST_13D_FORMS)) if str(f).strip()]
    out_manifest = Path(out_manifest)
    frames: list[pd.DataFrame] = []
    combined = IngestionDiagnostics()
    for ticker in tickers:
        tmp = out_manifest.parent / f".{out_manifest.stem}_{ticker.upper()}_13d_tmp.csv"
        try:
            df, diag = build_sec_source_document_manifest(
                client,
                tickers=[ticker.upper()],
                out_manifest=tmp,
                docs_dir=docs_dir,
                forms=forms,
                start=start,
                end=end,
                item_filter=None,
                limit_per_ticker=limit_per_ticker,
                include_primary=True,
                include_exhibits=True,
                exhibit_pattern=r"(?i)(ex[-_]?99|exhibit|letter|agreement|proxy|presentation)",
                sector_benchmark=sector_benchmark,
                overwrite=overwrite,
                min_text_chars=min_text_chars,
            )
        except Exception as exc:  # pragma: no cover - live SEC failures vary
            combined.add_skip(f"13d ticker error: {type(exc).__name__}")
            continue
        frames.append(df)
        _combine_diagnostics(combined, diag)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    out = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out = out.drop_duplicates(["source_doc_id"]).sort_values(["ticker", "event_time", "source_doc_id"]).reset_index(drop=True)
        out["event_type"] = "ownership"
        out["event_subtype"] = out["event_subtype"].fillna("").replace("", "activist_13d_candidate")
        out["source_type"] = out["source_type"].fillna("").replace("", "sec_filing")
        out["notes"] = out["notes"].fillna("").astype(str) + " activist_13d_control_intent_candidate=true"
    ensure_parent(out_manifest)
    out.to_csv(out_manifest, index=False)
    combined.rows_written = int(len(out))
    return out, combined


def validate_activist_13d_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    *,
    out_errors: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    fact_lookup = {(str(r.get("event_id")), str(r.get("fact_name"))): r for _, r in facts.iterrows()}
    rows = []
    reviewed_mask = gold.get("gold_review_status", pd.Series(["reviewed"] * len(gold), index=gold.index)).fillna("").astype(str).str.lower()
    requires_review = bool(reviewed_mask.isin({"", "needs_human_review", "unreviewed", "machine_candidate"}).any())
    for _, g in gold.iterrows():
        event_id = str(g.get("event_id"))
        fact_name = str(g.get("fact_name"))
        expected_present = str(g.get("expected_present", "true")).strip().lower() not in {"false", "0", "no", "n"}
        expected = g.get("expected_value", "")
        actual_row = fact_lookup.get((event_id, fact_name))
        actual = actual_row.get("value", "") if actual_row is not None else ""
        status = "missing"
        if requires_review:
            status = "gold_not_reviewed"
        elif not expected_present:
            status = "false_positive" if _norm(actual) and str(actual).lower() not in {"false", "0"} else "ok"
        elif actual_row is not None:
            if str(g.get("unit", "")).lower() in {"percent", "percentage_points", "shares"}:
                tol = _to_float(g.get("tolerance", 0.01))
                status = "ok" if pd.notna(_to_float(actual)) and abs(_to_float(actual) - _to_float(expected)) <= tol else "wrong_value"
            else:
                status = "ok" if str(actual).strip().lower() == str(expected).strip().lower() else "wrong_value"
        rows.append(
            {
                "event_id": event_id,
                "fact_name": fact_name,
                "expected_value": expected,
                "actual_value": actual,
                "unit": g.get("unit", ""),
                "expected_present": expected_present,
                "gold_category": g.get("gold_category", ""),
                "status": status,
                "evidence_text": actual_row.get("evidence_text", "") if actual_row is not None else "",
            }
        )
    errors = pd.DataFrame(rows)
    ok_count = int(errors["status"].eq("ok").sum()) if not errors.empty else 0
    row_accuracy = ok_count / len(errors) if len(errors) else 0.0
    event_type_rows = errors[errors["fact_name"].eq("activist_13d_event_type")]
    event_type_precision = float(event_type_rows["status"].eq("ok").mean()) if len(event_type_rows) else 0.0
    actual_event_type = errors["actual_value"].fillna("").astype(str).str.lower() if "actual_value" in errors.columns else pd.Series(dtype=str)
    gold_category = errors["gold_category"].fillna("").astype(str).str.lower() if "gold_category" in errors.columns else pd.Series(dtype=str)
    passive_false_activist = bool((gold_category.str.contains("13g|passive|hard_negative", regex=True) & actual_event_type.isin({"initial_activist_13d", "control_intent_13d", "board_seat_campaign", "sale_pressure", "strategic_alternatives_13d"})).any())
    gates = {
        "gold_set_60_rows": len(errors) >= 60,
        "gold_set_human_reviewed": not requires_review,
        "row_accuracy_90": row_accuracy >= 0.90,
        "event_type_precision_95": event_type_precision >= 0.95,
        "no_passive_or_13g_false_activist": not passive_false_activist,
    }
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": ok_count,
        "row_accuracy": float(row_accuracy),
        "event_type_precision": float(event_type_precision),
        "gates": gates,
        "parser_audit_pass": bool(all(gates.values())),
        "status": "gold_set_requires_human_review" if requires_review else "ok",
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def audit_activist_13d_timestamps_and_duplicates(events: pd.DataFrame, out_path: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    out = events.copy()
    if out.empty:
        summary = {"rows": 0, "duplicate_rows": 0, "clear_timestamp_rows": 0, "audit_pass": False}
        if out_path:
            ensure_parent(out_path)
            out.to_csv(out_path, index=False)
        return out, summary
    for col in ["beneficial_owner_name", "filing_type", "source_url", "release_session"]:
        if col not in out.columns:
            out[col] = ""
    key_cols = ["ticker", "beneficial_owner_name", "filing_type", "source_url"]
    duplicate_mask = out.duplicated(key_cols, keep="first")
    out["duplicate_status"] = np.where(duplicate_mask, "duplicate", "primary")
    ts = pd.to_datetime(out.get("event_time", pd.Series(index=out.index, dtype=str)), errors="coerce")
    session = out["release_session"].fillna("").astype(str).str.lower()
    out["timestamp_audit_status"] = np.where(ts.notna() & session.isin({"before_open", "intraday", "after_close"}), "clear", "needs_timestamp_review")
    clear_rows = int(out["timestamp_audit_status"].eq("clear").sum())
    summary = {
        "rows": int(len(out)),
        "duplicate_rows": int(duplicate_mask.sum()),
        "clear_timestamp_rows": clear_rows,
        "audit_pass": bool(int(duplicate_mask.sum()) == 0 and clear_rows == len(out)),
    }
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out, summary


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    include_same_day = str(release_session).lower() in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), _to_float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    matches = prices.index[prices["date"] == anchor_date].tolist()
    if not matches or matches[-1] - int(window) < 0:
        return np.nan
    idx = matches[-1]
    start = _to_float(prices.iloc[idx - int(window)]["adj_close"])
    end = _to_float(prices.iloc[idx]["adj_close"])
    return end / start - 1.0 if pd.notna(start) and pd.notna(end) and start else np.nan


def _load_optional(path: str | Path | None) -> pd.DataFrame:
    if not path or not Path(path).exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _context_lookup(row: pd.Series, context: pd.DataFrame, value_col: str) -> object:
    if context.empty or value_col not in context.columns:
        return np.nan
    event_id = _norm(row.get("event_id"))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str).eq(event_id)]
        if not matched.empty:
            return matched.iloc[0].get(value_col, np.nan)
    if "ticker" not in context.columns:
        return np.nan
    subset = context[context["ticker"].astype(str).str.upper().eq(_norm(row.get("ticker")).upper())].copy()
    if subset.empty:
        return np.nan
    if "asof_date" in subset.columns:
        subset["asof_date"] = pd.to_datetime(subset["asof_date"], errors="coerce")
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            subset = subset[subset["asof_date"] <= event_time]
        subset = subset.sort_values("asof_date", ascending=False)
    return subset.iloc[0].get(value_col, np.nan) if not subset.empty else np.nan


def _size_bucket(market_cap: object) -> str:
    mc = _to_float(market_cap)
    if pd.isna(mc):
        return "unknown"
    if mc < 2_000_000_000:
        return "small_cap"
    if mc < 10_000_000_000:
        return "mid_cap"
    return "large_cap"


def enrich_activist_13d_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
    prior_activity_path: str | Path | None = None,
    liquidity_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = _load_optional(market_caps_path)
    prior = _load_optional(prior_activity_path)
    liquidity = _load_optional(liquidity_path)
    try:
        benchmark = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark = pd.DataFrame()
    cache: dict[str, pd.DataFrame] = {}
    rows = []
    for _, row in events.iterrows():
        out = row.to_dict()
        ticker = _norm(row.get("ticker")).upper()
        status = []
        try:
            prices = cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")
        if benchmark.empty:
            status.append("missing_benchmark_prices")
        anchor_date, last_close = _anchor_price(prices, row.get("event_time"), row.get("release_session")) if not prices.empty else (None, np.nan)
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close
        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap):
            market_cap = _to_float(_context_lookup(row, market_caps, "market_cap_before_event"))
        out["market_cap_before_event"] = market_cap
        out["company_size_bucket"] = _size_bucket(market_cap)
        out["prior_13d_activity"] = _context_lookup(row, prior, "prior_13d_activity") if not prior.empty else row.get("prior_13d_activity", "")
        out["float_or_liquidity_context"] = _context_lookup(row, liquidity, "float_or_liquidity_context") if not liquidity.empty else row.get("float_or_liquidity_context", "")
        bench_anchor, _ = _anchor_price(benchmark, row.get("event_time"), row.get("release_session")) if not benchmark.empty else (None, np.nan)
        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_ret = _window_return(benchmark, bench_anchor, window) if not benchmark.empty else np.nan
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        if pd.isna(market_cap):
            status.append("missing_market_cap")
        if pd.isna(out["pre_event_market_adjusted_return_20d"]) and pd.isna(out["pre_event_market_adjusted_return_60d"]):
            status.append("missing_pre_event_runup")
        out["activist_13d_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        rows.append(out)
    enriched = pd.DataFrame(rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def activist_13d_readiness_summary(
    events: pd.DataFrame,
    *,
    min_train: int = 40,
    source_documents: pd.DataFrame | None = None,
    parser_errors: pd.DataFrame | None = None,
) -> dict[str, object]:
    source_rows = int(len(source_documents)) if source_documents is not None else int(events.get("source_doc_ids", pd.Series(dtype=str)).fillna("").astype(str).str.len().gt(0).sum())
    if events.empty:
        gates = {
            "source_documents_recovered_100": False,
            "reviewed_usable_events_80_min": False,
            "initial_active_or_control_events_50": False,
            "hard_negative_controls_30": False,
            "ownership_pct_rows_60": False,
            "market_cap_context_rows_40": False,
            "pre_event_runup_rows_40": False,
            "clear_timestamps_80": False,
            "duplicate_audit_pass": False,
            "likely_oos_predictions_30": False,
            "parser_audit_pass": False,
        }
        return {
            "source_documents_recovered": source_rows,
            "parsed_event_rows": 0,
            "reviewed_usable_rows": 0,
            "gates": gates,
            "top_missing_fields_blocking_modeling": list(gates),
            "decision": "continue corpus buildout",
            "reason": "no parsed event rows; stop before parser audit/context/modeling",
        }
    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review_status.isin({"rejected", "drop", "dropped"})].copy()
    usable_status = usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower()
    reviewed = usable[usable_status.isin({"reviewed", "curated", "approved"})].copy()
    event_type = reviewed.get("activist_13d_event_type", reviewed.get("event_subtype", pd.Series(dtype=str))).fillna("").astype(str).str.lower()
    active_types = {"initial_activist_13d", "control_intent_13d", "strategic_alternatives_13d", "board_seat_campaign", "sale_pressure"}
    hard_negative_types = {"passive_13g_control", "ownership_decrease_amendment", "exit_amendment", "passive_or_ambiguous_13d"}
    timestamp_audit = reviewed.get("timestamp_audit_status", pd.Series([""] * len(reviewed), index=reviewed.index)).fillna("").astype(str).str.lower()
    release_session = reviewed.get("release_session", pd.Series([""] * len(reviewed), index=reviewed.index)).fillna("").astype(str).str.lower()
    clear_ts = timestamp_audit.eq("clear") | release_session.isin({"before_open", "intraday", "after_close"})
    duplicate_status = reviewed.get("duplicate_status", pd.Series(["primary"] * len(reviewed), index=reviewed.index)).fillna("primary").astype(str).str.lower()

    metrics: dict[str, object] = {
        "source_documents_recovered": source_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "initial_active_or_control_rows": int(event_type.isin(active_types).sum()),
        "hard_negative_control_rows": int(event_type.isin(hard_negative_types).sum()),
        "rows_with_ownership_pct": int(pd.to_numeric(reviewed.get("ownership_pct", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_market_cap_context": int(pd.to_numeric(reviewed.get("market_cap_before_event", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_pre_event_runup_context": int(
            (
                pd.to_numeric(reviewed.get("pre_event_market_adjusted_return_20d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna()
                | pd.to_numeric(reviewed.get("pre_event_market_adjusted_return_60d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna()
            ).sum()
        ),
        "rows_with_clear_timestamps": int(clear_ts.sum()),
        "duplicate_rows": int(duplicate_status.eq("duplicate").sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
    }
    gates = {
        "source_documents_recovered_100": metrics["source_documents_recovered"] >= 100,
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_rows"] >= 100,
        "initial_active_or_control_events_50": metrics["initial_active_or_control_rows"] >= 50,
        "hard_negative_controls_30": metrics["hard_negative_control_rows"] >= 30,
        "ownership_pct_rows_60": metrics["rows_with_ownership_pct"] >= 60,
        "market_cap_context_rows_40": metrics["rows_with_market_cap_context"] >= 40,
        "pre_event_runup_rows_40": metrics["rows_with_pre_event_runup_context"] >= 40,
        "clear_timestamps_80": metrics["rows_with_clear_timestamps"] >= 80,
        "duplicate_audit_pass": metrics["duplicate_rows"] == 0 and metrics["reviewed_usable_rows"] > 0,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
    }
    if parser_errors is not None:
        ok_count = int(parser_errors.get("status", pd.Series(dtype=str)).astype(str).eq("ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_accuracy = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_accuracy"] = float(audit_accuracy)
        gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_accuracy >= 0.90)
    else:
        metrics["parser_audit_accuracy"] = "missing"
        gates["parser_audit_pass"] = False
    hard_gates = [g for g in gates if g != "reviewed_usable_events_100_preferred"]
    blockers = [g for g in hard_gates if not gates[g]]
    metrics["gates"] = {k: bool(v) for k, v in gates.items()}
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if all(gates[g] for g in hard_gates):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "all pre-modeling readiness gates pass; first falsification may be run next"
    elif not gates["source_documents_recovered_100"] or not gates["reviewed_usable_events_80_min"]:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "source discovery/reviewed corpus gate fails; stop before parser audit/context/modeling"
    elif not gates["parser_audit_pass"]:
        metrics["decision"] = "parser not trusted"
        metrics["reason"] = "parser audit is missing or below gate; stop before modeling"
    elif not gates["clear_timestamps_80"] or not gates["duplicate_audit_pass"]:
        metrics["decision"] = "timestamp/duplicate audit insufficient"
        metrics["reason"] = "public timestamp or duplicate control gate fails; stop before modeling"
    elif not gates["market_cap_context_rows_40"] or not gates["pre_event_runup_rows_40"]:
        metrics["decision"] = "context insufficient"
        metrics["reason"] = "market cap or pre-event run-up controls are under-covered"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_activist_13d_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    min_train: int = 40,
    source_documents_path: str | Path | None = None,
    parser_errors_path: str | Path | None = None,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    source_documents = pd.read_csv(source_documents_path) if source_documents_path else None
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    summary = activist_13d_readiness_summary(events, min_train=min_train, source_documents=source_documents, parser_errors=parser_errors)
    out = ensure_parent(out_path)
    lines = [
        "# Activist 13D Control-Intent Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## Verdict",
        "",
        f"- decision: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Counts",
        "",
    ]
    for key, value in summary.items():
        if key in {"gates", "top_missing_fields_blocking_modeling", "decision", "reason"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields Blocking Modeling", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "",
            "## Execution Survivability Gate",
            "",
            "- required_before_modeling: PASS if every modeled slice is classified as immediate-gap, delayed-digestion, slow-burn repricing, pre-event setup, or explanation-only before returns are inspected.",
            "- current_status: NOT EVALUATED FOR MODELING because readiness gates fail before modeling.",
            "- first_realistic_entry_policy: use next open for after-close SEC acceptances; use same-day open or next open for before-open acceptances; use the first liquid trade after acceptance for intraday filings.",
            "- tradeability_rule: close-to-close effects are explanatory only unless next-open behavior survives realistic implementation costs.",
            "- if_modeling_becomes_eligible: report close-to-close and next-open behavior under 25 bps, 50 bps, and 100 bps stress; do not treat close-to-close explanatory effect as tradable if next-open fails.",
            "- domain_prior: board, control, strategic-alternatives, and sale-pressure filings are delayed-digestion candidates; generic initial activist 13D and ownership increases are slow-burn repricing candidates; passive/ambiguous 13D and 13G rows are explanation-only controls; ownership decrease and exit amendments are immediate-gap or negative-control candidates.",
        ]
    )
    lines.extend(
        [
            "",
            "## Pre-Registered Candidate Hypotheses",
            "",
            "1. Initial 13D with activist/control language is positive.",
            "2. Board, strategic-alternatives, or sale language is stronger than generic investment language.",
            "3. Ownership decreases and exit amendments are negative or weak.",
            "4. Passive 13G filings are weaker controls.",
            "",
            "Do not model until parser audit, timestamp/duplicate audit, context enrichment, and reviewed-corpus gates pass.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
