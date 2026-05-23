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


SEC_DISTRESS_DOMAIN = "sec_distress_events"
SEC_DISTRESS_8K_ITEMS = "1.03,2.04,2.06,3.01"
SEC_DISTRESS_EXHIBIT_PATTERN = r"(?i)(8-k|ex[-_]?99|exhibit[-_ ]?99|delist|listing|nasdaq|nyse|bankrupt|default|impair)"

NEGATIVE_DISTRESS_TYPES = {
    "delisting_notice",
    "failure_to_satisfy_listing_rule",
    "bid_price_deficiency",
    "equity_deficiency",
    "bankruptcy_receivership",
    "debt_acceleration",
    "covenant_default",
    "material_impairment",
}
HARD_NEGATIVE_TYPES = {"compliance_cure", "extension_or_appeal", "reverse_split_plan"}
EXECUTION_CLASSES = {"immediate-gap", "delayed-digestion", "slow-burn repricing", "pre-event setup", "explanation-only"}

AMOUNT_RE = re.compile(
    r"\$?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m|thousand|k)?",
    re.I,
)
DATE_RE = re.compile(
    r"\b(?P<date>(?:20|19)\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(?:20|19)\d{2})\b",
    re.I,
)


@dataclass(frozen=True)
class SecDistressFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: str | float | bool
    unit: str
    source_evidence_text: str
    confidence: float
    parse_method: str
    parser_quality_flags: str = ""
    source_type: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out["evidence_text"] = self.source_evidence_text
        return out


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return default
    return text or default


def _norm_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _segments(text: str) -> list[str]:
    out = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 8 <= len(seg) <= 1000:
            out.append(seg)
    return out


def _contains_any(text: str, terms: list[str] | tuple[str, ...] | set[str]) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms)


def _first_segment(text: str, patterns: list[str]) -> str:
    for seg in _segments(text):
        for pattern in patterns:
            if re.search(pattern, seg, flags=re.I):
                return seg
    return ""


def _money(match: re.Match[str]) -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or "").lower()
    if unit in {"billion", "bn", "b"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    if unit in {"thousand", "k"}:
        return num * 1_000.0
    return num


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _fact(
    doc: SourceDocument,
    name: str,
    value: str | float | bool,
    unit: str,
    evidence: str,
    confidence: float,
    method: str,
    flags: list[str] | tuple[str, ...] | set[str] | str = "",
) -> SecDistressFact:
    flag_text = flags if isinstance(flags, str) else ";".join(sorted({str(f) for f in flags if str(f).strip()}))
    return SecDistressFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        source_evidence_text=_norm_space(evidence),
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=method,
        parser_quality_flags=flag_text,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def infer_sec_8k_item(text: str, notes: str = "") -> tuple[str, str, float]:
    combined = f"{notes}\n{text[:6000]}"
    found = []
    for item in ("1.03", "2.04", "2.06", "3.01"):
        if re.search(rf"\bItem\s+{re.escape(item)}\b|items.+{re.escape(item)}", combined, flags=re.I):
            found.append(item)
    if found:
        return ",".join(dict.fromkeys(found)), _first_segment(combined, [rf"Item\s+{re.escape(found[0])}", re.escape(found[0])]), 0.95
    low = combined.lower()
    if _contains_any(low, ["minimum bid price", "listing rule", "delisting notice"]):
        return "3.01", _first_segment(combined, ["listing", "delisting", "bid price"]), 0.72
    if _contains_any(low, ["chapter 11", "chapter 7", "bankruptcy", "receiver"]):
        return "1.03", _first_segment(combined, ["chapter", "bankruptcy", "receiver"]), 0.72
    if _contains_any(low, ["event of default", "accelerated", "acceleration", "covenant default"]):
        return "2.04", _first_segment(combined, ["default", "accelerat", "covenant"]), 0.70
    if "impairment" in low:
        return "2.06", _first_segment(combined, ["impairment"]), 0.70
    return "", "", 0.0


def infer_exchange(text: str) -> tuple[str, str, float]:
    seg = _first_segment(text, ["Nasdaq", "NYSE American", "NYSE MKT", "NYSE"])
    low = seg.lower()
    if "nasdaq" in low:
        return "NASDAQ", seg, 0.90
    if "nyse american" in low or "nyse mkt" in low:
        return "NYSE American", seg, 0.88
    if "nyse" in low:
        return "NYSE", seg, 0.88
    return "", "", 0.0


def infer_deficiency_type(text: str) -> tuple[str, str, float]:
    low_text = str(text or "").lower()
    if "minimum bid price" in low_text or "bid price requirement" in low_text:
        return "bid_price", _first_segment(text, ["minimum bid price|bid price requirement"]), 0.92
    if ("stockholders" in low_text or "shareholders" in low_text) and "equity" in low_text:
        return "equity", _first_segment(text, ["stockholders'? equity|shareholders'? equity|equity requirement"]), 0.90
    seg = _first_segment(
        text,
        [
            "minimum bid price|bid price requirement",
            "stockholders'? equity|shareholders'? equity|equity requirement",
            "market value of listed securities|market value",
            "audit committee|independent directors?|listing rule",
        ],
    )
    low = seg.lower()
    if "bid price" in low:
        return "bid_price", seg, 0.92
    if "stockholders" in low and "equity" in low or "shareholders" in low and "equity" in low or "equity requirement" in low:
        return "equity", seg, 0.90
    if "market value" in low:
        return "market_value", seg, 0.82
    if "audit committee" in low or "independent director" in low:
        return "governance", seg, 0.78
    if "listing rule" in low:
        return "other_listing_rule", seg, 0.65
    return "", "", 0.0


def infer_distress_event_type(text: str, item: str) -> tuple[str, str, float, list[str]]:
    low = text.lower()
    cure = _first_segment(text, ["regained compliance|now in compliance|compliance has been regained|deficiency has been cured"])
    if cure:
        return "compliance_cure", cure, 0.94, ["hard_negative_compliance_regained"]
    extension = _first_segment(text, ["extension.+granted|granted.+extension|appeal|hearing panel|additional time to regain compliance"])
    if extension:
        return "extension_or_appeal", extension, 0.88, ["hard_negative_extension_or_appeal"]
    reverse = _first_segment(text, ["reverse stock split|reverse split"])
    if reverse and not _contains_any(low, ["notice of delisting", "delisting determination", "will be delisted"]):
        return "reverse_split_plan", reverse, 0.86, ["hard_negative_reverse_split_plan_without_actual_delisting"]
    if "1.03" in item or _contains_any(low, ["chapter 11", "chapter 7", "filed for bankruptcy", "bankruptcy court", "receiver", "receivership"]):
        return "bankruptcy_receivership", _first_segment(text, ["chapter 11|chapter 7|bankruptcy|receiver|receivership"]), 0.93, []
    if "2.04" in item or _contains_any(low, ["event of default", "covenant default", "accelerated", "acceleration of", "demand for payment"]):
        accel = _first_segment(text, ["accelerated|acceleration|demand for payment"])
        if accel:
            return "debt_acceleration", accel, 0.90, []
        return "covenant_default", _first_segment(text, ["event of default|covenant default|default under"]), 0.88, []
    if "2.06" in item or _contains_any(low, ["impairment charge", "non-cash impairment", "goodwill impairment", "long-lived asset impairment"]):
        evidence = _first_segment(text, ["impairment charge|non-cash impairment|goodwill impairment|long-lived asset impairment|impairment"])
        flags = ["hard_negative_routine_or_previously_announced_impairment"] if _contains_any(evidence.lower(), ["previously announced", "previously disclosed"]) else []
        return "material_impairment", evidence, 0.88, flags
    if "3.01" in item or _contains_any(low, ["listing rule", "delisting", "minimum bid price", "stockholders' equity"]):
        deficiency, evidence, _ = infer_deficiency_type(text)
        if deficiency == "bid_price":
            return "bid_price_deficiency", evidence, 0.90, []
        if deficiency == "equity":
            return "equity_deficiency", evidence, 0.90, []
        delist = _first_segment(text, ["notice of delisting|delisting determination|will be delisted"])
        if delist:
            return "delisting_notice", delist, 0.88, []
        return "failure_to_satisfy_listing_rule", _first_segment(text, ["listing rule|continued listing|not in compliance"]), 0.82, []
    return "unknown", "", 0.0, ["no_distress_event_type_detected"]


def _amount_after(text: str, terms: list[str]) -> tuple[float, str, float]:
    for seg in _segments(text):
        if any(term in seg.lower() for term in terms):
            match = AMOUNT_RE.search(seg)
            if match:
                return _money(match), seg, 0.82
    return np.nan, "", 0.0


def _date_near(text: str, terms: list[str]) -> tuple[str, str, float]:
    for seg in _segments(text):
        if any(term in seg.lower() for term in terms):
            match = DATE_RE.search(seg)
            if match:
                ts = pd.to_datetime(match.group("date"), errors="coerce")
                if pd.notna(ts):
                    return pd.Timestamp(ts).date().isoformat(), seg, 0.80
    return "", "", 0.0


def _execution_class(event_type: str, release_session: str, dollar_volume: object = np.nan) -> tuple[str, str, bool, bool]:
    if event_type in {"compliance_cure", "extension_or_appeal", "reverse_split_plan", "unknown"}:
        return "explanation-only", "Hard-negative/control row or unclassified event; do not treat close-to-close association as tradable.", True, True
    dv = _to_float(dollar_volume)
    if pd.notna(dv) and dv < 1_000_000:
        return "explanation-only", "Pre-event dollar volume is too low for realistic next-open execution without large slippage.", True, True
    if release_session == "after_close":
        return "immediate-gap", "First realistic entry is next open; tradeability survives only if next-open and stress-cost behavior remain negative.", True, False
    if release_session in {"before_open", "intraday"}:
        return "delayed-digestion", "Public filing timestamp may leave an intraday or next-open digestion window, subject to halt and liquidity audit.", True, False
    return "explanation-only", "Release session is unknown, so observed close-to-close behavior cannot be treated as a tradable setup.", True, True


def parse_sec_distress_document(doc: SourceDocument) -> list[SecDistressFact]:
    item, item_evidence, item_conf = infer_sec_8k_item(doc.text, notes=doc.notes)
    event_type, event_evidence, event_conf, flags = infer_distress_event_type(doc.text, item)
    exchange, exchange_evidence, exchange_conf = infer_exchange(doc.text)
    deficiency, deficiency_evidence, deficiency_conf = infer_deficiency_type(doc.text)
    chapter_seg = _first_segment(doc.text, ["Chapter 11", "Chapter 7", "Chapter 15"])
    chapter_match = re.search(r"Chapter\s+(11|7|15)", chapter_seg, flags=re.I)
    chapter = chapter_match.group(1) if chapter_match else ""
    debt_amount, debt_evidence, debt_conf = _amount_after(doc.text, ["debt", "principal", "notes", "loan", "credit facility", "amount outstanding"])
    impairment_amount, impairment_evidence, impairment_conf = _amount_after(doc.text, ["impairment", "write-down", "writedown"])
    notice_date, notice_evidence, notice_conf = _date_near(doc.text, ["notice", "notification", "letter"])
    cure_deadline, cure_evidence, cure_conf = _date_near(doc.text, ["cure", "regain compliance", "deadline", "compliance period"])
    hard_negative = event_type in HARD_NEGATIVE_TYPES or any(flag.startswith("hard_negative") for flag in flags)
    hard_reason = event_type if event_type in HARD_NEGATIVE_TYPES else ";".join(f for f in flags if f.startswith("hard_negative"))
    return [
        _fact(doc, "sec_8k_item", item, "item", item_evidence, item_conf, "regex_8k_item", flags),
        _fact(doc, "sec_distress_event_type", event_type, "category", event_evidence, event_conf, "rule_event_type", flags),
        _fact(doc, "deficiency_type", deficiency, "category", deficiency_evidence, deficiency_conf, "rule_deficiency", flags),
        _fact(doc, "exchange", exchange, "exchange", exchange_evidence, exchange_conf, "rule_exchange", flags),
        _fact(doc, "notice_date", notice_date, "date", notice_evidence, notice_conf, "rule_notice_date", flags),
        _fact(doc, "cure_deadline", cure_deadline, "date", cure_evidence, cure_conf, "rule_cure_deadline", flags),
        _fact(doc, "appeal_flag", event_type == "extension_or_appeal" and _contains_any(event_evidence, ["appeal", "hearing"]), "boolean", event_evidence, event_conf, "rule_appeal", flags),
        _fact(doc, "bankruptcy_flag", event_type == "bankruptcy_receivership", "boolean", event_evidence, event_conf, "rule_bankruptcy", flags),
        _fact(doc, "chapter", chapter, "chapter", chapter_seg, 0.92 if chapter else 0.0, "rule_chapter", flags),
        _fact(doc, "debt_amount", debt_amount, "usd", debt_evidence, debt_conf, "rule_debt_amount", flags),
        _fact(doc, "covenant_default_flag", event_type == "covenant_default" or "default" in event_evidence.lower(), "boolean", event_evidence, event_conf, "rule_default", flags),
        _fact(doc, "acceleration_flag", event_type == "debt_acceleration", "boolean", event_evidence, event_conf, "rule_acceleration", flags),
        _fact(doc, "impairment_amount", impairment_amount, "usd", impairment_evidence, impairment_conf, "rule_impairment_amount", flags),
        _fact(doc, "impairment_reason", _norm_space(impairment_evidence), "text", impairment_evidence, impairment_conf, "rule_impairment_reason", flags),
        _fact(doc, "compliance_regained_flag", event_type == "compliance_cure", "boolean", event_evidence, event_conf, "rule_compliance", flags),
        _fact(doc, "extension_or_appeal_flag", event_type == "extension_or_appeal", "boolean", event_evidence, event_conf, "rule_extension", flags),
        _fact(doc, "reverse_split_plan_flag", event_type == "reverse_split_plan", "boolean", event_evidence, event_conf, "rule_reverse_split", flags),
        _fact(doc, "hard_negative_flag", hard_negative, "boolean", event_evidence, event_conf, "rule_hard_negative", flags),
        _fact(doc, "hard_negative_reason", hard_reason, "category", event_evidence, event_conf, "rule_hard_negative", flags),
    ]


def _facts_to_features(facts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for event_id, group in facts.groupby("event_id", sort=False):
        first = group.iloc[0]
        best = group.sort_values("confidence", ascending=False).drop_duplicates("fact_name").set_index("fact_name")

        def val(name: str, default: object = "") -> object:
            if name not in best.index:
                return default
            value = best.loc[name, "value"]
            return default if pd.isna(value) else value

        event_type = str(val("sec_distress_event_type", "unknown"))
        hard_negative = _bool_value(val("hard_negative_flag", False))
        direction = "positive" if event_type == "compliance_cure" else "neutral" if event_type in {"extension_or_appeal", "reverse_split_plan", "unknown"} else "negative"
        evidence = str(best.loc["sec_distress_event_type", "source_evidence_text"]) if "sec_distress_event_type" in best.index else ""
        exec_class, exec_reason, next_open_required, c2c_only = _execution_class(event_type, "unknown")
        rows.append(
            {
                "event_id": event_id,
                "ticker": first["ticker"],
                "event_time": first["event_time"],
                "source_doc_ids": ";".join(sorted(set(group["source_doc_id"].astype(str)))),
                "source_type": first.get("source_type", ""),
                "source_url": first.get("source_url", ""),
                "source_evidence_text": evidence,
                "sec_distress_event_type": event_type,
                "event_type": event_type,
                "sec_8k_item": val("sec_8k_item", ""),
                "deficiency_type": val("deficiency_type", ""),
                "exchange": val("exchange", ""),
                "notice_date": val("notice_date", ""),
                "cure_deadline": val("cure_deadline", ""),
                "appeal_flag": _bool_value(val("appeal_flag", False)),
                "bankruptcy_flag": _bool_value(val("bankruptcy_flag", False)),
                "chapter": val("chapter", ""),
                "debt_amount": val("debt_amount", np.nan),
                "covenant_default_flag": _bool_value(val("covenant_default_flag", False)),
                "acceleration_flag": _bool_value(val("acceleration_flag", False)),
                "impairment_amount": val("impairment_amount", np.nan),
                "impairment_reason": val("impairment_reason", ""),
                "compliance_regained_flag": _bool_value(val("compliance_regained_flag", False)),
                "extension_or_appeal_flag": _bool_value(val("extension_or_appeal_flag", False)),
                "reverse_split_plan_flag": _bool_value(val("reverse_split_plan_flag", False)),
                "hard_negative_flag": hard_negative,
                "hard_negative_reason": val("hard_negative_reason", ""),
                "distress_direction_pre_price": direction,
                "materiality_pre_price": "review_required" if event_type != "unknown" else "unknown",
                "evidence_status": "source_backed" if evidence else "missing",
                "parser_quality_flags": ";".join(sorted({str(f) for f in group["parser_quality_flags"].dropna() if str(f)})),
                "execution_survivability_class": exec_class,
                "first_realistic_entry": "next_open_required",
                "tradeability_after_first_entry_rationale": exec_reason,
                "next_open_required_flag": next_open_required,
                "close_to_close_explanatory_only_flag": c2c_only,
                "next_open_return_available_flag": False,
                "stress_cost_bps": "25;50;100",
            }
        )
    return pd.DataFrame(rows)


def parse_sec_distress_manifest(
    manifest_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(manifest_path)
    facts = pd.DataFrame([fact.to_dict() for doc in docs for fact in parse_sec_distress_document(doc)])
    features = _facts_to_features(facts)
    event_rows = []
    for _, row in features.iterrows():
        event_type = _norm(row.get("sec_distress_event_type"), "unknown")
        hard_negative = _bool_value(row.get("hard_negative_flag"))
        event_rows.append(
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "event_time": row["event_time"],
                "event_type": "distress",
                "summary": f"{row['ticker']} SEC distress disclosure candidate: {event_type}.",
                "event_subtype": event_type,
                "event_family": SEC_DISTRESS_DOMAIN,
                "source_type": row.get("source_type", ""),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": row.get("distress_direction_pre_price", "unknown"),
                "surprise_magnitude": "unknown",
                "materiality": 0.4 if hard_negative else 0.7 if event_type in NEGATIVE_DISTRESS_TYPES else 0.5,
                "sector_benchmark": "",
                "notes": "Do not model until reviewed, audited, and execution survivability passes.",
                "corpus_name": SEC_DISTRESS_DOMAIN,
                "review_status": "rejected" if hard_negative else "unreviewed",
                "label_quality": "parser_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "evidence_status": row.get("evidence_status", ""),
                **{col: row.get(col, "") for col in features.columns if col not in {"event_id", "ticker", "event_time", "source_type", "source_url"}},
            }
        )
    events = pd.DataFrame(event_rows)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    ensure_parent(features_out)
    features.to_csv(features_out, index=False)
    make_event_template(events_out, events.to_dict("records"))
    return facts, features, events


def build_sec_distress_source_documents(
    client: SecClient,
    tickers: list[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    start: str = "2015-01-01",
    end: str | None = None,
    limit_per_ticker: int | None = None,
    sector_benchmark: str = "",
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    return build_sec_source_document_manifest(
        client=client,
        tickers=tickers,
        out_manifest=out_manifest,
        docs_dir=docs_dir,
        forms=("8-K",),
        start=start,
        end=end,
        item_filter=SEC_DISTRESS_8K_ITEMS,
        limit_per_ticker=limit_per_ticker,
        include_primary=True,
        include_exhibits=True,
        exhibit_pattern=SEC_DISTRESS_EXHIBIT_PATTERN,
        sector_benchmark=sector_benchmark,
    )


def _ratio(numerator: object, denominator: object) -> float:
    num = _to_float(numerator)
    den = _to_float(denominator)
    return num / den if pd.notna(num) and pd.notna(den) and den else np.nan


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan, np.nan
    date = pd.Timestamp(ts).tz_localize(None).normalize() if getattr(pd.Timestamp(ts), "tzinfo", None) else pd.Timestamp(ts).normalize()
    include_same_day = str(release_session).lower() in {"after_close", "intraday", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan, np.nan
    last = eligible.iloc[-1]
    close = _to_float(last["adj_close"])
    volume = _to_float(last.get("volume", np.nan))
    dollar_volume = close * volume if pd.notna(close) and pd.notna(volume) else np.nan
    return pd.to_datetime(last["date"]), close, dollar_volume


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx = prices.index[prices["date"] == anchor_date].tolist()
    if not idx or idx[-1] - int(window) < 0:
        return np.nan
    start = _to_float(prices.iloc[idx[-1] - int(window)]["adj_close"])
    end = _to_float(prices.iloc[idx[-1]]["adj_close"])
    return end / start - 1.0 if pd.notna(start) and pd.notna(end) and start else np.nan


def enrich_sec_distress_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = pd.read_csv(market_caps_path) if market_caps_path and Path(market_caps_path).exists() else pd.DataFrame()
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()
    price_cache: dict[str, pd.DataFrame] = {}
    rows = []
    for _, row in events.iterrows():
        out = row.to_dict()
        status = []
        ticker = _norm(row.get("ticker")).upper()
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")
        if benchmark_prices.empty:
            status.append("missing_benchmark_prices")
        anchor_date, close, dollar_volume = _anchor_price(prices, row.get("event_time"), row.get("release_session")) if not prices.empty else (None, np.nan, np.nan)
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["share_price_before_event"] = close
        out["penny_stock_flag"] = bool(pd.notna(close) and close < 5.0)
        out["dollar_volume_before_event"] = dollar_volume
        if pd.isna(close):
            status.append("missing_pre_event_price")
        if pd.isna(dollar_volume):
            status.append("missing_dollar_volume")
        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap) and not market_caps.empty:
            matches = market_caps[market_caps.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().eq(ticker)].copy()
            if not matches.empty and "asof_date" in matches.columns:
                matches["asof_date"] = pd.to_datetime(matches["asof_date"], errors="coerce")
                event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
                if pd.notna(event_time):
                    matches = matches[matches["asof_date"] <= event_time]
                matches = matches.sort_values("asof_date", ascending=False)
            if not matches.empty:
                market_cap = _to_float(matches.iloc[0].get("market_cap_before_event"))
        out["market_cap_before_event"] = market_cap
        if pd.isna(market_cap):
            status.append("missing_market_cap")
        out["debt_amount_pct_market_cap"] = _ratio(row.get("debt_amount"), market_cap)
        out["impairment_pct_market_cap"] = _ratio(row.get("impairment_amount"), market_cap)
        bench_anchor = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session"))[0] if not benchmark_prices.empty else None
        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_ret = _window_return(benchmark_prices, bench_anchor, window) if not benchmark_prices.empty else np.nan
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        exec_class, reason, next_open_required, c2c_only = _execution_class(_norm(row.get("sec_distress_event_type"), _norm(row.get("event_subtype"))), _norm(row.get("release_session")), dollar_volume)
        out["execution_survivability_class"] = exec_class
        out["tradeability_after_first_entry_rationale"] = reason
        out["next_open_required_flag"] = next_open_required
        out["close_to_close_explanatory_only_flag"] = c2c_only
        out["liquidity_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        rows.append(out)
    enriched = pd.DataFrame(rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def validate_sec_distress_parser(facts: pd.DataFrame, gold: pd.DataFrame, out_errors: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = []
    reviewed_col = gold.get("gold_review_status", gold.get("review_status", pd.Series(["reviewed"] * len(gold), index=gold.index)))
    reviewed = reviewed_col.fillna("").astype(str).str.lower().isin({"reviewed", "approved", "curated"})
    for _, row in gold.iterrows():
        event_id = _norm(row.get("event_id"))
        fact_name = _norm(row.get("fact_name"))
        expected = row.get("expected_value", "")
        expected_present = True if "expected_present" not in row or pd.isna(row.get("expected_present")) else _bool_value(row.get("expected_present"))
        candidates = facts[(facts.get("event_id", pd.Series(dtype=str)).astype(str) == event_id) & (facts.get("fact_name", pd.Series(dtype=str)).astype(str) == fact_name)]
        actual = candidates.sort_values("confidence", ascending=False).iloc[0]["value"] if not candidates.empty else ""
        if not bool(reviewed.loc[row.name]):
            status = "gold_not_reviewed"
        elif not expected_present:
            status = "ok" if str(actual).strip().lower() in {"", "unknown", "false", "nan"} else "false_positive"
        elif candidates.empty:
            status = "missing"
        elif str(actual).strip().lower() == str(expected).strip().lower():
            status = "ok"
        else:
            try:
                status = "ok" if abs(float(actual) - float(expected)) <= float(row.get("tolerance", 0) or 0) else "mismatch"
            except Exception:
                status = "mismatch"
        rows.append({**row.to_dict(), "actual_value": actual, "status": status})
    errors = pd.DataFrame(rows)
    ok_count = int(errors["status"].eq("ok").sum()) if not errors.empty else 0
    accuracy = ok_count / len(errors) if len(errors) else 0.0
    gates = {
        "gold_set_60_rows": len(errors) >= 60,
        "gold_set_human_reviewed": bool(reviewed.all()) if len(gold) else False,
        "row_accuracy_90": accuracy >= 0.90,
        "hard_negatives_not_mislabeled_distress": not bool((errors.get("status", pd.Series(dtype=str)).eq("false_positive")).any()),
    }
    report = {"gold_rows": int(len(errors)), "correct_rows": ok_count, "row_accuracy": float(accuracy), "gates": gates, "parser_audit_pass": bool(all(gates.values()))}
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def _reviewed_usable_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    hard = events.get("hard_negative_flag", pd.Series(False, index=events.index)).map(_bool_value)
    event_type = events.get("sec_distress_event_type", events.get("event_subtype", pd.Series("", index=events.index))).fillna("").astype(str).str.lower()
    return events[status.isin({"reviewed", "curated", "approved"}) & ~hard & event_type.isin(NEGATIVE_DISTRESS_TYPES)].copy()


def sec_distress_readiness_summary(
    events: pd.DataFrame,
    *,
    min_train: int = 40,
    source_documents: pd.DataFrame | None = None,
    parser_errors: pd.DataFrame | None = None,
) -> dict[str, object]:
    source_docs = int(len(source_documents)) if source_documents is not None else int(events.get("source_doc_ids", pd.Series(dtype=str)).fillna("").astype(str).str.len().gt(0).sum())
    reviewed = _reviewed_usable_events(events)
    event_type = reviewed.get("sec_distress_event_type", reviewed.get("event_subtype", pd.Series(dtype=str))).fillna("").astype(str).str.lower()
    release_session = reviewed.get("release_session", pd.Series("", index=reviewed.index)).fillna("").astype(str).str.lower()
    timestamps = pd.to_datetime(reviewed.get("event_time", pd.Series(dtype=str)), errors="coerce")
    clear_timestamps = timestamps.notna() & release_session.isin({"before_open", "intraday", "after_close"})
    next_open_ready = reviewed.get("next_open_return_available_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    explanatory_only = reviewed.get("close_to_close_explanatory_only_flag", pd.Series(True, index=reviewed.index)).map(_bool_value)
    metrics: dict[str, object] = {
        "source_documents_recovered": source_docs,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_distress_rows": int(len(reviewed)),
        "delisting_rows": int(event_type.isin({"delisting_notice", "failure_to_satisfy_listing_rule", "bid_price_deficiency", "equity_deficiency"}).sum()),
        "bankruptcy_rows": int(event_type.eq("bankruptcy_receivership").sum()),
        "debt_default_rows": int(event_type.isin({"debt_acceleration", "covenant_default"}).sum()),
        "rows_with_market_cap_context": int(pd.to_numeric(reviewed.get("market_cap_before_event", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_pre_event_runup_context": int(pd.to_numeric(reviewed.get("pre_event_market_adjusted_return_20d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_liquidity_context": int(pd.to_numeric(reviewed.get("dollar_volume_before_event", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_clear_event_timestamps": int(clear_timestamps.sum()),
        "rows_with_next_open_execution_audit": int(next_open_ready.sum()),
        "close_to_close_explanatory_only_rows": int(explanatory_only.sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
    }
    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_distress_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_distress_rows"] >= 100,
        "negative_distress_events_60": metrics["reviewed_usable_distress_rows"] >= 60,
        "delisting_events_20": metrics["delisting_rows"] >= 20,
        "bankruptcy_events_10": metrics["bankruptcy_rows"] >= 10,
        "debt_default_events_10": metrics["debt_default_rows"] >= 10,
        "market_cap_context_rows_40": metrics["rows_with_market_cap_context"] >= 40,
        "pre_event_runup_context_rows_40": metrics["rows_with_pre_event_runup_context"] >= 40,
        "liquidity_context_rows_40": metrics["rows_with_liquidity_context"] >= 40,
        "event_timestamps_clear": metrics["rows_with_clear_event_timestamps"] >= metrics["reviewed_usable_distress_rows"] and metrics["reviewed_usable_distress_rows"] > 0,
        "execution_survivability_next_open_audited": metrics["rows_with_next_open_execution_audit"] >= metrics["reviewed_usable_distress_rows"] and metrics["reviewed_usable_distress_rows"] > 0,
        "close_to_close_not_explanatory_only": metrics["close_to_close_explanatory_only_rows"] == 0 and metrics["reviewed_usable_distress_rows"] > 0,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
    }
    if parser_errors is not None:
        audit_rows = int(len(parser_errors))
        precision = float(parser_errors.get("status", pd.Series(dtype=str)).astype(str).eq("ok").mean()) if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_precision"] = precision
        gates["parser_audit_pass"] = audit_rows >= 60 and precision >= 0.90
    else:
        metrics["parser_audit_precision"] = "missing"
        gates["parser_audit_pass"] = False
    hard_gates = [g for g in gates if g != "reviewed_usable_events_100_preferred"]
    blockers = [g for g in hard_gates if not gates[g]]
    metrics["gates"] = {k: bool(v) for k, v in gates.items()}
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if all(gates[g] for g in hard_gates):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "reviewed SEC distress corpus clears readiness and execution survivability gates"
    elif metrics["reviewed_usable_distress_rows"] >= 80 and (
        not gates["execution_survivability_next_open_audited"] or not gates["close_to_close_not_explanatory_only"]
    ):
        metrics["decision"] = "execution survivability failed"
        metrics["reason"] = "next-open tradability has not been audited; close-to-close behavior is explanation-only"
    elif metrics["source_documents_recovered"] == 0 or metrics["parsed_event_rows"] == 0:
        metrics["decision"] = "continue source discovery"
        metrics["reason"] = "no source-backed parsed SEC distress event corpus exists yet"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_sec_distress_readiness_report(
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
    summary = sec_distress_readiness_summary(events, min_train=min_train, source_documents=source_documents, parser_errors=parser_errors)
    out = ensure_parent(out_path)
    lines = [
        "# SEC Distress Events Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## Verdict",
        "",
        f"- decision: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Execution Survivability Gate",
        "",
        "- Classification must be one of immediate-gap, delayed-digestion, slow-burn repricing, pre-event setup, or explanation-only.",
        "- Close-to-close effects are explanatory only unless next-open behavior survives 25/50/100 bps stress.",
        "- SEC distress defaults to explanation-only when release session, halt status, next-open price, or liquidity audit is missing.",
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
    lines.extend(["", "## Blocking Fields", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
