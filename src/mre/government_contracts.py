from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time
from typing import Iterable

import numpy as np
import pandas as pd
import requests

from .events import make_event_template
from .paths import ensure_parent
from .prices import load_price_csv
from .source_docs import SOURCE_DOC_COLUMNS


GOVERNMENT_CONTRACT_DOMAIN = "government_contract_awards"

GOVERNMENT_CONTRACT_EVENT_TYPES = {
    "new_contract_award",
    "task_order_award",
    "contract_modification",
    "option_exercise",
    "idiq_vehicle_award",
    "contract_ceiling_only",
    "sbir_award",
    "sttr_award",
    "ota_prototype_award",
    "production_contract",
    "recompete_win",
    "contract_extension",
    "subcontract_award",
    "ambiguous_contract_event",
}

RECIPIENT_TICKER_MAP_COLUMNS = [
    "recipient_name_pattern",
    "ticker",
    "public_company_name",
    "subsidiary_name",
    "mapping_type",
    "confidence",
    "source_url",
    "notes",
]

MODEL_ELIGIBLE_MAPPING_TYPES = {"exact_public_company", "known_subsidiary", "division"}
LEGACY_MAPPING_TYPE_ALIASES = {
    "exact": "exact_public_company",
    "subsidiary": "known_subsidiary",
    "jv": "joint_venture",
}

GOVERNMENT_CONTRACT_EXTRA_SOURCE_COLUMNS = [
    "recipient_name",
    "mapped_ticker",
    "parent_company_name",
    "subsidiary_name",
    "mapping_type",
    "recipient_mapping_confidence",
    "agency",
    "sub_agency",
    "award_amount",
    "obligated_amount",
    "contract_ceiling",
    "award_type",
    "contract_type",
    "contract_number",
    "task_order_number",
    "modification_number",
    "period_of_performance_start",
    "period_of_performance_end",
    "product_or_service_description",
    "naics_code",
    "psc_code",
    "location",
    "prime_or_sub",
]

GOVERNMENT_CONTRACT_SOURCE_COLUMNS = SOURCE_DOC_COLUMNS + [
    c for c in GOVERNMENT_CONTRACT_EXTRA_SOURCE_COLUMNS if c not in SOURCE_DOC_COLUMNS
]

USASPENDING_CONTRACT_CODES = ("A", "B", "C", "D")
USASPENDING_IDV_CODES = ("IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E")
USASPENDING_AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Start Date",
    "End Date",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Contract Award Type",
    "NAICS",
    "PSC",
    "Description",
]

AMOUNT_RE = re.compile(
    r"\$?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m|thousand|k)?",
    re.I,
)
DATE_RE = re.compile(r"\b(?P<date>(?:20|19)\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(?:20|19)\d{2})\b", re.I)
CONTRACT_NUMBER_RE = re.compile(r"\b(?:contract|award|idv)\s+(?:no\.?|number|#)?\s*(?P<num>[A-Z0-9][A-Z0-9-]{6,})", re.I)
TASK_ORDER_RE = re.compile(r"\b(?:task|delivery)\s+order\s+(?:no\.?|number|#)?\s*(?P<num>[A-Z0-9][A-Z0-9-]{4,})?", re.I)
MODIFICATION_RE = re.compile(r"\b(?:modification|mod)\s+(?:no\.?|number|#)?\s*(?P<num>P?\d{3,5}|[A-Z]\d{3,5})?", re.I)


DEFAULT_RECIPIENT_TICKER_MAP = [
    ("LOCKHEED MARTIN", "LMT", "Lockheed Martin Corporation", "", "exact", 0.95, "Large defense prime."),
    ("LOCKHEED MARTIN CORPORATION", "LMT", "Lockheed Martin Corporation", "", "exact", 0.96, "Large defense prime."),
    ("LOCKHEED MARTIN CORP", "LMT", "Lockheed Martin Corporation", "", "exact", 0.96, "Large defense prime."),
    ("LOCKHEED MARTIN AERONAUTICS", "LMT", "Lockheed Martin Corporation", "Lockheed Martin Aeronautics", "subsidiary", 0.91, "Lockheed operating unit."),
    ("LOCKHEED MARTIN MISSILES", "LMT", "Lockheed Martin Corporation", "Lockheed Martin Missiles and Fire Control", "subsidiary", 0.91, "Lockheed operating unit."),
    ("LOCKHEED MARTIN ROTARY", "LMT", "Lockheed Martin Corporation", "Lockheed Martin Rotary and Mission Systems", "subsidiary", 0.91, "Lockheed operating unit."),
    ("SIKORSKY", "LMT", "Lockheed Martin Corporation", "Sikorsky", "subsidiary", 0.90, "Lockheed subsidiary."),
    ("RAYTHEON", "RTX", "RTX Corporation", "Raytheon", "subsidiary", 0.92, "RTX defense subsidiary."),
    ("RAYTHEON COMPANY", "RTX", "RTX Corporation", "Raytheon Company", "subsidiary", 0.92, "RTX defense subsidiary."),
    ("RAYTHEON MISSILES", "RTX", "RTX Corporation", "Raytheon Missiles & Defense", "subsidiary", 0.90, "RTX defense subsidiary."),
    ("RAYTHEON TECHNOLOGIES", "RTX", "RTX Corporation", "", "exact", 0.90, "Legacy public-company name."),
    ("PRATT & WHITNEY", "RTX", "RTX Corporation", "Pratt & Whitney", "subsidiary", 0.90, "RTX aerospace subsidiary."),
    ("COLLINS AEROSPACE", "RTX", "RTX Corporation", "Collins Aerospace", "subsidiary", 0.90, "RTX aerospace subsidiary."),
    ("NORTHROP GRUMMAN", "NOC", "Northrop Grumman Corporation", "", "exact", 0.95, "Large defense prime."),
    ("NORTHROP GRUMMAN SYSTEMS", "NOC", "Northrop Grumman Corporation", "Northrop Grumman Systems Corporation", "subsidiary", 0.92, "Northrop legal entity."),
    ("GENERAL DYNAMICS", "GD", "General Dynamics Corporation", "", "exact", 0.95, "Large defense prime."),
    ("GENERAL DYNAMICS LAND SYSTEMS", "GD", "General Dynamics Corporation", "General Dynamics Land Systems", "subsidiary", 0.90, "General Dynamics subsidiary."),
    ("ELECTRIC BOAT", "GD", "General Dynamics Corporation", "General Dynamics Electric Boat", "subsidiary", 0.90, "General Dynamics subsidiary."),
    ("BATH IRON WORKS", "GD", "General Dynamics Corporation", "Bath Iron Works", "subsidiary", 0.90, "General Dynamics subsidiary."),
    ("GDIT", "GD", "General Dynamics Corporation", "General Dynamics Information Technology", "subsidiary", 0.88, "General Dynamics IT subsidiary."),
    ("BOEING", "BA", "The Boeing Company", "", "exact", 0.92, "Large aerospace prime."),
    ("BOEING COMPANY", "BA", "The Boeing Company", "", "exact", 0.94, "Large aerospace prime."),
    ("BOEING CO", "BA", "The Boeing Company", "", "exact", 0.94, "Large aerospace prime."),
    ("HUNTINGTON INGALLS", "HII", "Huntington Ingalls Industries, Inc.", "", "exact", 0.95, "Shipbuilding prime."),
    ("INGALLS SHIPBUILDING", "HII", "Huntington Ingalls Industries, Inc.", "Ingalls Shipbuilding", "subsidiary", 0.90, "HII subsidiary."),
    ("NEWPORT NEWS SHIPBUILDING", "HII", "Huntington Ingalls Industries, Inc.", "Newport News Shipbuilding", "subsidiary", 0.90, "HII subsidiary."),
    ("L3HARRIS", "LHX", "L3Harris Technologies, Inc.", "", "exact", 0.95, "Defense electronics prime."),
    ("L3HARRIS TECHNOLOGIES", "LHX", "L3Harris Technologies, Inc.", "", "exact", 0.96, "Defense electronics prime."),
    ("HARRIS CORPORATION", "LHX", "L3Harris Technologies, Inc.", "Harris Corporation", "subsidiary", 0.88, "Legacy Harris name."),
    ("L3 TECHNOLOGIES", "LHX", "L3Harris Technologies, Inc.", "", "subsidiary", 0.88, "Legacy L3 name."),
    ("CACI", "CACI", "CACI International Inc", "", "exact", 0.94, "Government services/IT."),
    ("CACI INC", "CACI", "CACI International Inc", "CACI Inc.", "subsidiary", 0.90, "CACI legal entity."),
    ("SCIENCE APPLICATIONS INTERNATIONAL", "SAIC", "Science Applications International Corporation", "", "exact", 0.94, "Government services/IT."),
    ("SAIC", "SAIC", "Science Applications International Corporation", "", "exact", 0.94, "Government services/IT."),
    ("LEIDOS", "LDOS", "Leidos Holdings, Inc.", "", "exact", 0.94, "Government services/IT."),
    ("LEIDOS INC", "LDOS", "Leidos Holdings, Inc.", "Leidos, Inc.", "subsidiary", 0.90, "Leidos legal entity."),
    ("BOOZ ALLEN", "BAH", "Booz Allen Hamilton Holding Corporation", "", "exact", 0.94, "Government services/IT."),
    ("BOOZ ALLEN HAMILTON", "BAH", "Booz Allen Hamilton Holding Corporation", "", "exact", 0.95, "Government services/IT."),
    ("PALANTIR", "PLTR", "Palantir Technologies Inc.", "", "exact", 0.95, "Government software."),
    ("PALANTIR USG", "PLTR", "Palantir Technologies Inc.", "Palantir USG, Inc.", "subsidiary", 0.90, "Palantir government subsidiary."),
    ("KRATOS", "KTOS", "Kratos Defense & Security Solutions, Inc.", "", "exact", 0.94, "Defense technology."),
    ("KRATOS DEFENSE", "KTOS", "Kratos Defense & Security Solutions, Inc.", "", "exact", 0.95, "Defense technology."),
    ("KRATOS UNMANNED", "KTOS", "Kratos Defense & Security Solutions, Inc.", "Kratos Unmanned Aerial Systems", "subsidiary", 0.90, "Kratos subsidiary."),
    ("MERCURY SYSTEMS", "MRCY", "Mercury Systems, Inc.", "", "exact", 0.94, "Defense electronics."),
    ("AEROVIRONMENT", "AVAV", "AeroVironment, Inc.", "", "exact", 0.94, "Unmanned systems."),
    ("AEROVIRONMENT INC", "AVAV", "AeroVironment, Inc.", "", "exact", 0.95, "Unmanned systems."),
    ("ROCKET LAB", "RKLB", "Rocket Lab USA, Inc.", "", "exact", 0.94, "Space launch and systems."),
    ("ROCKET LAB USA", "RKLB", "Rocket Lab USA, Inc.", "", "exact", 0.95, "Space launch and systems."),
    ("INTUITIVE MACHINES", "LUNR", "Intuitive Machines, Inc.", "", "exact", 0.94, "Space systems."),
    ("INTUITIVE MACHINES LLC", "LUNR", "Intuitive Machines, Inc.", "Intuitive Machines, LLC", "subsidiary", 0.88, "Operating company."),
    ("REDWIRE", "RDW", "Redwire Corporation", "", "exact", 0.94, "Space infrastructure."),
    ("REDWIRE SPACE", "RDW", "Redwire Corporation", "Redwire Space", "subsidiary", 0.88, "Redwire operating entity."),
    ("BLACKSKY", "BKSY", "BlackSky Technology Inc.", "", "exact", 0.94, "Satellite imagery."),
    ("BLACKSKY GEOSPATIAL", "BKSY", "BlackSky Technology Inc.", "BlackSky Geospatial Solutions", "subsidiary", 0.90, "BlackSky operating entity."),
    ("PLANET LABS", "PL", "Planet Labs PBC", "", "exact", 0.94, "Earth observation."),
    ("PLANET LABS FEDERAL", "PL", "Planet Labs PBC", "Planet Labs Federal, Inc.", "subsidiary", 0.90, "Planet government subsidiary."),
    ("HII FLEET SUPPORT GROUP", "HII", "HII", "HII Fleet Support Group LLC", "known_subsidiary", 0.88, "https://www.sec.gov/Archives/edgar/data/1501585/000150158522000007/hii-ex22202110xk.htm", "Listed as an HII subsidiary/guarantor; still review materiality and public timestamp."),
    ("MICRO SYSTEMS", "KTOS", "Kratos Defense & Security Solutions, Inc.", "Micro Systems, Inc.", "known_subsidiary", 0.88, "https://www.kratosdefense.com/newsroom/kratos-wins-86-million-assuming-all-options-exercised-single-award-u-s-army-contract-for-drone-command-and-control-systems", "Kratos describes Micro Systems as a wholly owned subsidiary."),
    ("GICHNER SYSTEMS GROUP", "KTOS", "Kratos Defense & Security Solutions, Inc.", "Gichner Systems Group, Inc.", "known_subsidiary", 0.86, "https://www.gao.gov/products/b-414287%2Cb-414287.2%2Cb-414287.3", "GAO decision identifies Gichner as a wholly owned Kratos subsidiary."),
    ("FLORIDA TURBINE TECHNOLOGIES", "KTOS", "Kratos Defense & Security Solutions, Inc.", "Florida Turbine Technologies, Inc.", "known_subsidiary", 0.84, "https://www.kratosdefense.com/newsroom/kratos-defense-security-solutions-acquires-advanced-turbine-engine-developer-florida-turbine-technologies", "Kratos acquired a controlling interest; review exposure for older rows."),
    ("PHYSICAL OPTICS", "MRCY", "Mercury Systems, Inc.", "Physical Optics Corporation", "known_subsidiary", 0.86, "https://ir.mrcy.com/news-releases/news-release-details/mercury-systems-completes-acquisition-physical-optics", "Mercury completed acquisition of Physical Optics."),
    ("MERCURY DEFENSE SYSTEMS", "MRCY", "Mercury Systems, Inc.", "Mercury Defense Systems, Inc.", "known_subsidiary", 0.88, "https://ir.mrcy.com/news-releases/news-release-details/mercury-systems-appoints-brian-perry-president-mercury-defense", "Mercury describes Mercury Defense Systems as a subsidiary."),
    ("MERCURY MISSION SYSTEMS", "MRCY", "Mercury Systems, Inc.", "Mercury Mission Systems, LLC", "known_subsidiary", 0.82, "https://ir.mrcy.com/static-files/db2da4f5-2f44-469f-85b2-b2faabaed6bf", "Mercury subsidiary listing includes Mercury Mission Systems."),
    ("RTX CORPORATION", "RTX", "RTX Corporation", "", "exact_public_company", 0.96, "https://investors.rtx.com/", "Exact public-company legal name."),
    ("HAMILTON SUNDSTRAND SPACE SYSTEMS", "RTX", "RTX Corporation", "Hamilton Sundstrand Space Systems International, Inc.", "known_subsidiary", 0.86, "https://investors.rtx.com/static-files/6c951fb4-1b3e-417a-9c44-c726d27dc93d", "RTX subsidiary and affiliate listing includes Hamilton Sundstrand Space Systems International."),
    ("METRO MACHINE", "GD", "General Dynamics Corporation", "Metro Machine Corp. / General Dynamics NASSCO-Norfolk", "known_subsidiary", 0.86, "https://www.prnewswire.com/news-releases/general-dynamics-completes-acquisition-of-metro-machine-corp-132946923.html", "General Dynamics completed acquisition of Metro Machine Corp."),
    ("NATIONAL STEEL AND SHIPBUILDING", "GD", "General Dynamics Corporation", "General Dynamics NASSCO", "known_subsidiary", 0.88, "https://nassco.com/about-us/", "NASSCO is a General Dynamics business; review exact legal-entity naming."),
    ("ARCTURUS UAV", "AVAV", "AeroVironment, Inc.", "Arcturus UAV, Inc.", "known_subsidiary", 0.88, "https://investor.avinc.com/news-releases/news-release-details/aerovironment-inc-completes-acquisition-arcturus-uav-expands", "AeroVironment completed acquisition of Arcturus UAV."),
    ("MASTODON DESIGN", "CACI", "CACI International Inc", "Mastodon Design LLC", "known_subsidiary", 0.88, "https://investor.caci.com/news/news-details/2019/CACI-Enters-Into-Agreement-to-Acquire-LGS-Innovations-and-Acquires-Mastodon-Design/default.aspx", "CACI announced acquisition of Mastodon Design."),
    ("LOADPATH", "RDW", "Redwire Corporation", "LoadPath", "known_subsidiary", 0.84, "https://ir.redwirespace.com/news-events/press-releases/detail/13/redwire-acquires-loadpath-a-leading-developer-of-payload", "Redwire announced acquisition of LoadPath before becoming public through SPAC; review exposure and dates."),
    ("PALO ALTO NETWORKS", "PANW", "Palo Alto Networks, Inc.", "", "exact", 0.93, "Cybersecurity vendor."),
    ("CROWDSTRIKE", "CRWD", "CrowdStrike Holdings, Inc.", "", "exact", 0.93, "Cybersecurity vendor."),
    ("CLOUDFLARE", "NET", "Cloudflare, Inc.", "", "exact", 0.93, "Network/cybersecurity vendor."),
    ("ZSCALER", "ZS", "Zscaler, Inc.", "", "exact", 0.93, "Cybersecurity vendor."),
    ("UNITED LAUNCH ALLIANCE", "BA;LMT", "United Launch Alliance", "United Launch Alliance", "ambiguous", 0.45, "Joint venture; do not map to parent without event-specific evidence."),
]


@dataclass(frozen=True)
class GovernmentContractSourceDocument:
    source_doc_id: str
    ticker: str
    event_id: str
    event_time: pd.Timestamp
    event_type: str
    event_subtype: str
    release_session: str
    source_type: str
    source_url: str
    title: str
    text: str
    path: str = ""
    fiscal_period_end: str = ""
    sector_benchmark: str = ""
    notes: str = ""
    recipient_name: str = ""
    mapped_ticker: str = ""
    parent_company_name: str = ""
    subsidiary_name: str = ""
    mapping_type: str = ""
    recipient_mapping_confidence: float = np.nan
    agency: str = ""
    sub_agency: str = ""
    award_amount: float = np.nan
    obligated_amount: float = np.nan
    contract_ceiling: float = np.nan
    award_type: str = ""
    contract_type: str = ""
    contract_number: str = ""
    task_order_number: str = ""
    modification_number: str = ""
    period_of_performance_start: str = ""
    period_of_performance_end: str = ""
    product_or_service_description: str = ""
    naics_code: str = ""
    psc_code: str = ""
    location: str = ""
    prime_or_sub: str = ""


@dataclass(frozen=True)
class GovernmentContractFact:
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


def _norm_name(text: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper()).strip()


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _is_missing(value: object) -> bool:
    if isinstance(value, (bool, list, dict, tuple)):
        return False
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _money(match: re.Match[str], default_unit: str = "") -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or default_unit or "").lower()
    if unit in {"billion", "bn", "b"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    if unit in {"thousand", "k"}:
        return num * 1_000.0
    return num


def _segments(text: str) -> list[str]:
    parts = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 8 <= len(seg) <= 900:
            parts.append(seg)
    return parts


def _money_after_terms(segment: str, terms: Iterable[str]) -> tuple[float, re.Match[str] | None]:
    low = segment.lower()
    best_pos = None
    for term in terms:
        pos = low.find(term)
        if pos >= 0 and (best_pos is None or pos < best_pos):
            best_pos = pos
    if best_pos is None:
        return np.nan, None
    tail = segment[best_pos:]
    match = AMOUNT_RE.search(tail)
    if not match:
        return np.nan, None
    after = tail[match.end() : match.end() + 35].lower()
    default_unit = ""
    if not match.group("unit"):
        if "billion" in after or re.search(r"\bbn\b", after):
            default_unit = "billion"
        elif "million" in after or re.search(r"\bmn\b|\bm\b", after):
            default_unit = "million"
    return _money(match, default_unit=default_unit), match


def _parse_date(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).date().isoformat()


def _normalize_ts(value: object) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Could not parse event_time: {value!r}")
    out = pd.Timestamp(ts)
    if out.tzinfo is not None:
        try:
            out = out.tz_convert(None)
        except TypeError:
            out = out.tz_localize(None)
    return out


def write_government_contract_recipient_ticker_map(
    out_path: str | Path,
    *,
    overwrite: bool = False,
) -> pd.DataFrame:
    out = Path(out_path)
    if out.exists() and not overwrite:
        return pd.read_csv(out)
    legacy_cols = [c for c in RECIPIENT_TICKER_MAP_COLUMNS if c != "source_url"]
    rows = []
    for values in DEFAULT_RECIPIENT_TICKER_MAP:
        if len(values) == len(RECIPIENT_TICKER_MAP_COLUMNS):
            row = dict(zip(RECIPIENT_TICKER_MAP_COLUMNS, values, strict=True))
        else:
            row = dict(zip(legacy_cols, values, strict=True))
            row["source_url"] = ""
        row["mapping_type"] = _normalize_mapping_type(row.get("mapping_type"))
        rows.append(row)
    df = pd.DataFrame(rows, columns=RECIPIENT_TICKER_MAP_COLUMNS)
    ensure_parent(out).write_text(df.to_csv(index=False), encoding="utf-8")
    return df


def _normalize_mapping_type(value: object) -> str:
    raw = _norm(value, "ambiguous").lower().strip()
    return LEGACY_MAPPING_TYPE_ALIASES.get(raw, raw)


def load_recipient_ticker_map(path: str | Path, *, create_if_missing: bool = True) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        if not create_if_missing:
            raise FileNotFoundError(f"Missing recipient ticker map: {p}")
        return write_government_contract_recipient_ticker_map(p)
    df = pd.read_csv(p)
    for col in RECIPIENT_TICKER_MAP_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["mapping_type"] = df["mapping_type"].map(_normalize_mapping_type)
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    return df[RECIPIENT_TICKER_MAP_COLUMNS]


def map_recipient_to_ticker(recipient_name: object, mapping: pd.DataFrame) -> dict[str, object]:
    name = _norm_name(recipient_name)
    if not name or mapping.empty:
        return {
            "mapped_ticker": "",
            "parent_company_name": "",
            "subsidiary_name": "",
            "mapping_type": "unmapped",
            "recipient_mapping_confidence": 0.0,
            "mapping_notes": "No recipient mapping match.",
        }

    candidates = []
    for _, row in mapping.iterrows():
        pattern = _norm_name(row.get("recipient_name_pattern", ""))
        if not pattern:
            continue
        if pattern in name:
            candidates.append(
                {
                    "mapped_ticker": _norm(row.get("ticker")).upper(),
                    "parent_company_name": _norm(row.get("public_company_name")),
                    "subsidiary_name": _norm(row.get("subsidiary_name")),
                    "mapping_type": _normalize_mapping_type(row.get("mapping_type")),
                    "recipient_mapping_confidence": float(row.get("confidence", 0.0) or 0.0),
                    "mapping_notes": _norm(row.get("notes")),
                    "mapping_source_url": _norm(row.get("source_url")),
                    "pattern_len": len(pattern),
                }
            )
    if not candidates:
        return {
            "mapped_ticker": "",
            "parent_company_name": "",
            "subsidiary_name": "",
            "mapping_type": "unmapped",
            "recipient_mapping_confidence": 0.0,
            "mapping_notes": "No recipient mapping match.",
        }
    candidates.sort(key=lambda r: (r["recipient_mapping_confidence"], r["pattern_len"]), reverse=True)
    best = candidates[0]
    best.pop("pattern_len", None)
    return best


def _mapping_is_high(mapping_type: object, confidence: object, ticker: object) -> bool:
    conf = _to_float(confidence)
    tick = _norm(ticker).upper()
    mtype = _normalize_mapping_type(mapping_type)
    return bool(pd.notna(conf) and conf >= 0.80 and tick and ";" not in tick and mtype in MODEL_ELIGIBLE_MAPPING_TYPES)


def _read_text_from_path(path_value: object, manifest_dir: Path) -> str:
    rel = _norm(path_value)
    if not rel:
        return ""
    path = Path(rel)
    if not path.is_absolute():
        path = manifest_dir / path
    if not path.exists():
        raise FileNotFoundError(f"Source document path does not exist: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _metadata_from_notes(notes: object) -> dict:
    text = _norm(notes)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _source_row_text(row: dict[str, object]) -> str:
    parts = ["Government contract source row."]
    for label, key in [
        ("Recipient", "recipient_name"),
        ("Award ID", "contract_number"),
        ("Agency", "agency"),
        ("Sub-agency", "sub_agency"),
        ("Contract award type", "award_type"),
        ("Award amount", "award_amount"),
        ("Obligated amount", "obligated_amount"),
        ("Contract ceiling", "contract_ceiling"),
        ("NAICS", "naics_code"),
        ("PSC", "psc_code"),
        ("Description", "product_or_service_description"),
    ]:
        value = _norm(row.get(key))
        if value:
            parts.append(f"{label}: {value}.")
    start = _norm(row.get("period_of_performance_start"))
    end = _norm(row.get("period_of_performance_end"))
    if start or end:
        parts.append(f"Period of performance: {start} to {end}.")
    return " ".join(parts)


def _usaspending_award_url(result: dict) -> str:
    generated = _norm(result.get("generated_internal_id"))
    if generated:
        return f"https://www.usaspending.gov/award/{generated}"
    award_id = _norm(result.get("Award ID"))
    return f"https://www.usaspending.gov/keyword_search/{award_id}" if award_id else "https://www.usaspending.gov/"


def _nested_code(value: object) -> str:
    if isinstance(value, dict):
        return _norm(value.get("code"))
    return _norm(value)


def _nested_description(value: object) -> str:
    if isinstance(value, dict):
        return _norm(value.get("description"))
    return ""


def _usaspending_result_to_source_row(result: dict, mapping: pd.DataFrame) -> dict[str, object]:
    recipient = _norm(result.get("Recipient Name"))
    mapped = map_recipient_to_ticker(recipient, mapping)
    ticker = mapped["mapped_ticker"] if _mapping_is_high(mapped["mapping_type"], mapped["recipient_mapping_confidence"], mapped["mapped_ticker"]) else ""
    award_id = _norm(result.get("Award ID"))
    start = _parse_date(result.get("Start Date"))
    event_time = f"{start}T12:00:00" if start else ""
    award_type = _norm(result.get("Contract Award Type"))
    award_amount = _to_float(result.get("Award Amount"))
    is_idv = "indefinite" in award_type.lower() or "idv" in _norm(result.get("generated_internal_id")).lower() or award_type.upper() in {"BPA", "BOA"}
    contract_ceiling = award_amount if is_idv and pd.notna(award_amount) and award_amount > 0 else np.nan
    obligated_amount = np.nan if is_idv else award_amount
    naics = result.get("NAICS")
    psc = result.get("PSC")
    description = _norm(result.get("Description"))
    row = {
        "source_doc_id": f"usaspending_{re.sub(r'[^A-Za-z0-9]+', '_', _norm(result.get('generated_internal_id')) or award_id)[:96]}",
        "ticker": ticker,
        "event_id": f"government_contract_{ticker or 'UNMAPPED'}_{re.sub(r'[^A-Za-z0-9]+', '_', award_id)[:48]}",
        "event_time": event_time,
        "event_type": "government_contract",
        "event_subtype": "usaspending_award",
        "release_session": "unknown",
        "source_type": "usaspending_api",
        "source_url": _usaspending_award_url(result),
        "title": f"USAspending award {award_id} to {recipient}",
        "path": "",
        "text": "",
        "fiscal_period_end": "",
        "sector_benchmark": "",
        "notes": json.dumps(
            {
                "government_contract_source": True,
                "usaspending_internal_id": result.get("internal_id", ""),
                "generated_internal_id": result.get("generated_internal_id", ""),
                "agency_slug": result.get("agency_slug", ""),
                "mapping_notes": mapped.get("mapping_notes", ""),
            },
            sort_keys=True,
        ),
        "recipient_name": recipient,
        "mapped_ticker": mapped["mapped_ticker"],
        "parent_company_name": mapped["parent_company_name"],
        "subsidiary_name": mapped["subsidiary_name"],
        "mapping_type": mapped["mapping_type"],
        "recipient_mapping_confidence": mapped["recipient_mapping_confidence"],
        "agency": _norm(result.get("Awarding Agency")),
        "sub_agency": _norm(result.get("Awarding Sub Agency")),
        "award_amount": award_amount,
        "obligated_amount": obligated_amount,
        "contract_ceiling": contract_ceiling,
        "award_type": award_type,
        "contract_type": award_type,
        "contract_number": award_id,
        "task_order_number": award_id if "order" in award_type.lower() else "",
        "modification_number": "",
        "period_of_performance_start": start,
        "period_of_performance_end": _parse_date(result.get("End Date")),
        "product_or_service_description": description,
        "naics_code": _nested_code(naics),
        "psc_code": _nested_code(psc),
        "location": "",
        "prime_or_sub": "prime",
    }
    row["text"] = _source_row_text(row) + f" NAICS description: {_nested_description(naics)}. PSC description: {_nested_description(psc)}."
    return row


def _usaspending_search_terms(mapping: pd.DataFrame, tickers: Iterable[str] | None, recipients: Iterable[str] | None) -> list[str]:
    explicit = [_norm(r) for r in (recipients or []) if _norm(r)]
    if explicit:
        return sorted(set(explicit))
    selected = mapping.copy()
    ticker_set = {str(t).upper() for t in (tickers or []) if str(t).strip()}
    if ticker_set:
        selected = selected[selected["ticker"].astype(str).str.upper().isin(ticker_set)]
    else:
        selected = selected[selected["ticker"].astype(str).str.upper().isin({"PLTR", "KTOS", "RKLB", "LUNR", "RDW", "BKSY", "PL", "AVAV"})]
    terms = []
    for _, row in selected.iterrows():
        if not _mapping_is_high(row.get("mapping_type"), row.get("confidence"), row.get("ticker")):
            continue
        terms.append(_norm(row.get("recipient_name_pattern")))
    return sorted(set(t for t in terms if t))


def _query_usaspending_group(
    search_term: str,
    codes: tuple[str, ...],
    *,
    start: str,
    end: str,
    limit: int,
    page: int = 1,
    min_award_amount: float | None = None,
    timeout: float = 30.0,
) -> list[dict]:
    filters: dict[str, object] = {
        "award_type_codes": list(codes),
        "time_period": [{"start_date": start, "end_date": end}],
        "recipient_search_text": [search_term],
    }
    if min_award_amount is not None:
        filters["award_amounts"] = [{"lower_bound": float(min_award_amount)}]
    payload = {
        "subawards": False,
        "limit": int(limit),
        "page": int(page),
        "sort": "Award Amount",
        "order": "desc",
        "filters": filters,
        "fields": USASPENDING_AWARD_FIELDS,
    }
    resp = requests.post(
        "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return list(data.get("results", []) or [])


def build_government_contract_source_documents(
    out_manifest: str | Path,
    *,
    mapping_path: str | Path,
    manifest_paths: Iterable[str | Path] | None = None,
    use_usaspending: bool = False,
    tickers: Iterable[str] | None = None,
    recipient_search: Iterable[str] | None = None,
    start: str = "2024-01-01",
    end: str = "2026-05-23",
    limit_per_recipient: int = 3,
    pages_per_recipient: int = 1,
    min_award_amount: float | None = None,
    requests_per_second: float = 2.0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    mapping = load_recipient_ticker_map(mapping_path)
    rows: list[dict[str, object]] = []
    diagnostics: dict[str, object] = {
        "mapping_path": str(mapping_path),
        "manifest_rows": 0,
        "usaspending_rows": 0,
        "usaspending_rows_skipped_out_of_window": 0,
        "usaspending_pages_requested": 0,
        "usaspending_errors": {},
    }

    for manifest_path in manifest_paths or []:
        p = Path(manifest_path)
        df = pd.read_csv(p)
        for col in GOVERNMENT_CONTRACT_SOURCE_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        for _, raw in df.iterrows():
            row = raw.to_dict()
            text = _norm(row.get("text")) or _read_text_from_path(row.get("path"), p.parent)
            row["text"] = text
            recipient = _norm(row.get("recipient_name")) or _infer_recipient_from_text(text)
            row["recipient_name"] = recipient
            mapped = map_recipient_to_ticker(recipient, mapping)
            for key, target in [
                ("mapped_ticker", "mapped_ticker"),
                ("parent_company_name", "parent_company_name"),
                ("subsidiary_name", "subsidiary_name"),
                ("mapping_type", "mapping_type"),
                ("recipient_mapping_confidence", "recipient_mapping_confidence"),
            ]:
                if not _norm(row.get(target)):
                    row[target] = mapped[key]
            if not _norm(row.get("ticker")) and _mapping_is_high(row.get("mapping_type"), row.get("recipient_mapping_confidence"), row.get("mapped_ticker")):
                row["ticker"] = _norm(row.get("mapped_ticker")).upper()
            row["event_type"] = _norm(row.get("event_type"), "government_contract")
            row["event_subtype"] = _norm(row.get("event_subtype"), "manifest_source")
            row["source_type"] = _norm(row.get("source_type"), "source_document")
            row["release_session"] = _norm(row.get("release_session"), "unknown").lower()
            rows.append(row)
            diagnostics["manifest_rows"] = int(diagnostics["manifest_rows"]) + 1

    if use_usaspending:
        delay = 1.0 / max(float(requests_per_second), 0.1)
        start_ts = pd.to_datetime(start, errors="coerce")
        end_ts = pd.to_datetime(end, errors="coerce")
        for term in _usaspending_search_terms(mapping, tickers, recipient_search):
            for codes in (USASPENDING_CONTRACT_CODES, USASPENDING_IDV_CODES):
                for page in range(1, max(1, int(pages_per_recipient)) + 1):
                    try:
                        diagnostics["usaspending_pages_requested"] = int(diagnostics["usaspending_pages_requested"]) + 1
                        results = _query_usaspending_group(
                            term,
                            codes,
                            start=start,
                            end=end,
                            limit=limit_per_recipient,
                            page=page,
                            min_award_amount=min_award_amount,
                        )
                    except Exception as exc:  # pragma: no cover - network/API failures vary
                        errors = diagnostics["usaspending_errors"]
                        if isinstance(errors, dict):
                            errors[f"{term}:{codes[0]}:page{page}"] = type(exc).__name__
                        continue
                    if not results:
                        break
                    for result in results:
                        award_start = pd.to_datetime(result.get("Start Date"), errors="coerce")
                        if (pd.notna(start_ts) and pd.notna(award_start) and award_start < start_ts) or (pd.notna(end_ts) and pd.notna(award_start) and award_start > end_ts):
                            diagnostics["usaspending_rows_skipped_out_of_window"] = int(diagnostics["usaspending_rows_skipped_out_of_window"]) + 1
                            continue
                        rows.append(_usaspending_result_to_source_row(result, mapping))
                        diagnostics["usaspending_rows"] = int(diagnostics["usaspending_rows"]) + 1
                    if len(results) < int(limit_per_recipient):
                        break
                    time.sleep(delay)

    out = pd.DataFrame(rows)
    for col in GOVERNMENT_CONTRACT_SOURCE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    if not out.empty:
        out = out[GOVERNMENT_CONTRACT_SOURCE_COLUMNS + [c for c in out.columns if c not in GOVERNMENT_CONTRACT_SOURCE_COLUMNS]]
        out = out.drop_duplicates(["source_doc_id"]).sort_values(["ticker", "event_time", "source_doc_id"]).reset_index(drop=True)
    ensure_parent(out_manifest)
    out.to_csv(out_manifest, index=False)
    diagnostics["rows_written"] = int(len(out))
    return out, diagnostics


def _infer_recipient_from_text(text: str) -> str:
    patterns = [
        r"\b(?:awarded|award(?:ed)? to|issued to)\s+(?P<name>[A-Z][A-Za-z0-9 &.,'-]{2,90}?)(?:\s+(?:a|an)\s+\$|\s+for\s+\$|,|\.)",
        r"\bRecipient:\s*(?P<name>[^.;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return _norm_space(match.group("name")).strip(" ,.")
    return ""


def _row_value(row: pd.Series, name: str, default: object = "") -> object:
    value = row.get(name, default)
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return default
    return value


def load_government_contract_documents(manifest_path: str | Path) -> list[GovernmentContractSourceDocument]:
    p = Path(manifest_path)
    df = pd.read_csv(p)
    for col in GOVERNMENT_CONTRACT_SOURCE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    docs = []
    seen: set[str] = set()
    for i, row in df.iterrows():
        source_doc_id = _norm(row.get("source_doc_id"), f"government_contract_doc_{i+1:04d}")
        if source_doc_id in seen:
            raise ValueError(f"Duplicate source_doc_id: {source_doc_id}")
        seen.add(source_doc_id)
        text = _norm(row.get("text")) or _read_text_from_path(row.get("path"), p.parent)
        if not text:
            raise ValueError(f"source_doc_id={source_doc_id} has neither inline text nor readable path")
        event_time = _normalize_ts(row.get("event_time"))
        recipient = _norm(row.get("recipient_name")) or _infer_recipient_from_text(text)
        ticker = _norm(row.get("ticker")).upper()
        mapped_ticker = _norm(row.get("mapped_ticker")).upper()
        event_id = _norm(row.get("event_id")) or f"government_contract_{ticker or mapped_ticker or 'UNMAPPED'}_{event_time.strftime('%Y%m%d_%H%M')}_{source_doc_id}"
        docs.append(
            GovernmentContractSourceDocument(
                source_doc_id=source_doc_id,
                ticker=ticker,
                event_id=event_id,
                event_time=event_time,
                event_type=_norm(row.get("event_type"), "government_contract").lower(),
                event_subtype=_norm(row.get("event_subtype"), "contract_award_source").lower(),
                release_session=_norm(row.get("release_session"), "unknown").lower(),
                source_type=_norm(row.get("source_type"), "source_document").lower(),
                source_url=_norm(row.get("source_url")),
                title=_norm(row.get("title"), f"{ticker or mapped_ticker or 'Unmapped'} government contract source"),
                text=text,
                path=_norm(row.get("path")),
                fiscal_period_end=_norm(row.get("fiscal_period_end")),
                sector_benchmark=_norm(row.get("sector_benchmark")).upper(),
                notes=_norm(row.get("notes")),
                recipient_name=recipient,
                mapped_ticker=mapped_ticker,
                parent_company_name=_norm(row.get("parent_company_name")),
                subsidiary_name=_norm(row.get("subsidiary_name")),
                mapping_type=_norm(row.get("mapping_type"), "unmapped").lower(),
                recipient_mapping_confidence=_to_float(row.get("recipient_mapping_confidence")),
                agency=_norm(row.get("agency")),
                sub_agency=_norm(row.get("sub_agency")),
                award_amount=_to_float(row.get("award_amount")),
                obligated_amount=_to_float(row.get("obligated_amount")),
                contract_ceiling=_to_float(row.get("contract_ceiling")),
                award_type=_norm(row.get("award_type")),
                contract_type=_norm(row.get("contract_type")),
                contract_number=_norm(row.get("contract_number")),
                task_order_number=_norm(row.get("task_order_number")),
                modification_number=_norm(row.get("modification_number")),
                period_of_performance_start=_parse_date(row.get("period_of_performance_start")),
                period_of_performance_end=_parse_date(row.get("period_of_performance_end")),
                product_or_service_description=_norm(row.get("product_or_service_description")),
                naics_code=_norm(row.get("naics_code")),
                psc_code=_norm(row.get("psc_code")),
                location=_norm(row.get("location")),
                prime_or_sub=_norm(row.get("prime_or_sub"), "prime").lower(),
            )
        )
    return docs


def _fact(
    doc: GovernmentContractSourceDocument,
    name: str,
    value: str | float | bool,
    unit: str,
    evidence: str,
    confidence: float,
    method: str,
) -> GovernmentContractFact:
    return GovernmentContractFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker or doc.mapped_ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        evidence_text=_norm_space(evidence)[:900],
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=method,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def _add_text_fact(facts: list[GovernmentContractFact], doc: GovernmentContractSourceDocument, name: str, value: object, confidence: float = 0.86) -> None:
    text = _norm(value)
    if text:
        facts.append(_fact(doc, name, text, "text", text, confidence, "source_metadata"))


def _add_money_fact(facts: list[GovernmentContractFact], doc: GovernmentContractSourceDocument, name: str, value: object, evidence: str, confidence: float = 0.88) -> None:
    val = _to_float(value)
    if pd.notna(val):
        facts.append(_fact(doc, name, float(val), "usd", evidence, confidence, "source_metadata" if evidence == "source metadata" else "text_rule"))


def infer_government_contract_event_type(doc: GovernmentContractSourceDocument) -> tuple[str, str, float]:
    text = _norm_space(f"{doc.award_type} {doc.contract_type} {doc.event_subtype} {doc.title} {doc.text}")
    low = text.lower()
    if "subcontract" in low:
        return "subcontract_award", "subcontract language", 0.88
    if "sbir" in low or "small business innovation research" in low:
        return "sbir_award", "SBIR language", 0.90
    if "sttr" in low or "small business technology transfer" in low:
        return "sttr_award", "STTR language", 0.90
    if "production contract" in low or "production award" in low:
        return "production_contract", "production contract language", 0.86
    if "recompete" in low or "re-compete" in low:
        return "recompete_win", "recompete language", 0.85
    if "extension" in low or "extended" in low:
        return "contract_extension", "extension language", 0.84
    if "option" in low and any(w in low for w in ["exercise", "exercised", "option year", "option period"]):
        return "option_exercise", "option exercise language", 0.88
    if "modification" in low or re.search(r"\bmod(?:\s+|ification)", low):
        return "contract_modification", "modification language", 0.88
    if "task order" in low or "delivery order" in low:
        return "task_order_award", "task/delivery order language", 0.88
    if "other transaction" in low or re.search(r"\bota\b", low) or "prototype award" in low:
        return "ota_prototype_award", "OTA/prototype language", 0.86
    if "indefinite-delivery" in low or "indefinite delivery" in low or "indefinite-quantity" in low or "idiq" in low or "multiple award" in low or "contract vehicle" in low:
        return "idiq_vehicle_award", "IDIQ/contract vehicle language", 0.88
    if (
        pd.notna(_to_float(doc.contract_ceiling))
        or re.search(r"\b(?:ceiling|not-to-exceed|not to exceed|up to)\s+(?:of\s+)?\$?\s*\d", low)
    ):
        return "contract_ceiling_only", "ceiling-only language", 0.80
    if any(w in low for w in ["awarded", "award", "contract"]):
        return "new_contract_award", "contract award language", 0.76
    return "ambiguous_contract_event", "", 0.35


def _extract_amounts_from_text(doc: GovernmentContractSourceDocument, facts: list[GovernmentContractFact]) -> None:
    for seg in _segments(doc.text):
        low = seg.lower()
        if any(term in low for term in ["obligated", "initial obligation", "initial funding", "funded amount", "currently obligated"]):
            val, money = _money_after_terms(seg, ["initial obligation", "initial funding", "funded amount", "currently obligated", "obligated"])
            if money:
                facts.append(_fact(doc, "obligated_amount", val, "usd", seg, 0.90, "obligated_amount_sentence"))
        if any(term in low for term in ["ceiling", "not-to-exceed", "not to exceed", "maximum value", "up to"]):
            val, money = _money_after_terms(seg, ["ceiling", "not-to-exceed", "not to exceed", "maximum value", "up to"])
            if money:
                facts.append(_fact(doc, "contract_ceiling", val, "usd", seg, 0.88, "ceiling_sentence"))
        if any(term in low for term in ["awarded", "contract", "task order", "delivery order", "award amount", "valued at", "worth"]):
            if any(term in low for term in ["ceiling", "not-to-exceed", "not to exceed", "up to"]) and not any(term in low for term in ["obligated", "funded"]):
                continue
            val, money = _money_after_terms(seg, ["award amount", "valued at", "worth", "awarded", "contract", "task order", "delivery order"])
            if money:
                facts.append(_fact(doc, "award_amount", val, "usd", seg, 0.82, "award_amount_sentence"))


def _extract_identifiers_from_text(doc: GovernmentContractSourceDocument, facts: list[GovernmentContractFact]) -> None:
    contract_match = CONTRACT_NUMBER_RE.search(doc.text)
    if contract_match:
        facts.append(_fact(doc, "contract_number", contract_match.group("num").upper(), "text", contract_match.group(0), 0.80, "contract_number_regex"))
    task_match = TASK_ORDER_RE.search(doc.text)
    if task_match:
        value = task_match.group("num") or "task_order_present"
        facts.append(_fact(doc, "task_order_number", value.upper(), "text", task_match.group(0), 0.76, "task_order_regex"))
    mod_match = MODIFICATION_RE.search(doc.text)
    if mod_match:
        value = mod_match.group("num") or "modification_present"
        facts.append(_fact(doc, "modification_number", value.upper(), "text", mod_match.group(0), 0.76, "modification_regex"))
    if "naics" in doc.text.lower():
        m = re.search(r"\bNAICS\s*(?:code)?\s*(?P<code>\d{6})\b", doc.text, re.I)
        if m:
            facts.append(_fact(doc, "naics_code", m.group("code"), "text", m.group(0), 0.82, "naics_regex"))
    if "psc" in doc.text.lower():
        m = re.search(r"\bPSC\s*(?:code)?\s*(?P<code>[A-Z0-9]{4})\b", doc.text, re.I)
        if m:
            facts.append(_fact(doc, "psc_code", m.group("code").upper(), "text", m.group(0), 0.82, "psc_regex"))


def _extract_period_from_text(doc: GovernmentContractSourceDocument, facts: list[GovernmentContractFact]) -> None:
    low = doc.text.lower()
    if "period of performance" not in low and "performance period" not in low:
        return
    dates = [m.group("date") for m in DATE_RE.finditer(doc.text)]
    parsed = [_parse_date(d) for d in dates]
    parsed = [d for d in parsed if d]
    if parsed:
        facts.append(_fact(doc, "period_of_performance_start", parsed[0], "date", "period of performance date", 0.78, "performance_period_regex"))
    if len(parsed) >= 2:
        facts.append(_fact(doc, "period_of_performance_end", parsed[1], "date", "period of performance date", 0.78, "performance_period_regex"))


def _dedupe_facts(facts: list[GovernmentContractFact]) -> list[GovernmentContractFact]:
    best: dict[str, GovernmentContractFact] = {}
    for fact in facts:
        current = best.get(fact.fact_name)
        if current is None or fact.confidence > current.confidence:
            best[fact.fact_name] = fact
    return sorted(best.values(), key=lambda f: f.fact_name)


def parse_government_contract_document(doc: GovernmentContractSourceDocument) -> list[GovernmentContractFact]:
    facts: list[GovernmentContractFact] = []
    event_type, event_evidence, event_confidence = infer_government_contract_event_type(doc)
    facts.append(_fact(doc, "government_contract_event_type", event_type, "category", event_evidence, event_confidence, "document_keyword"))

    for name in [
        "recipient_name",
        "mapped_ticker",
        "parent_company_name",
        "subsidiary_name",
        "mapping_type",
        "agency",
        "sub_agency",
        "award_type",
        "contract_type",
        "contract_number",
        "task_order_number",
        "modification_number",
        "period_of_performance_start",
        "period_of_performance_end",
        "product_or_service_description",
        "naics_code",
        "psc_code",
        "location",
        "prime_or_sub",
    ]:
        _add_text_fact(facts, doc, name, getattr(doc, name), 0.90 if getattr(doc, name, "") else 0.0)

    facts.append(_fact(doc, "recipient_mapping_confidence", _to_float(doc.recipient_mapping_confidence) if pd.notna(_to_float(doc.recipient_mapping_confidence)) else 0.0, "ratio", "source metadata", 0.90, "source_metadata"))
    _add_money_fact(facts, doc, "award_amount", doc.award_amount, "source metadata", 0.90)
    _add_money_fact(facts, doc, "obligated_amount", doc.obligated_amount, "source metadata", 0.90)
    _add_money_fact(facts, doc, "contract_ceiling", doc.contract_ceiling, "source metadata", 0.90)

    if not doc.product_or_service_description:
        for seg in _segments(doc.text):
            if any(w in seg.lower() for w in ["description:", "provide", "support", "services", "prototype", "software"]):
                facts.append(_fact(doc, "product_or_service_description", seg[:500], "text", seg, 0.62, "description_sentence"))
                break

    _extract_amounts_from_text(doc, facts)
    _extract_identifiers_from_text(doc, facts)
    _extract_period_from_text(doc, facts)

    derived = derive_government_contract_fields(_facts_to_one_row(facts, doc))
    for name in [
        "actual_funded_award_flag",
        "ceiling_only_flag",
        "modification_flag",
        "option_exercise_flag",
        "new_work_flag",
        "incumbent_or_extension_flag",
        "recompete_or_extension_flag",
        "prime_contractor_flag",
        "subcontractor_flag",
        "materiality_context_required_flag",
    ]:
        facts.append(_fact(doc, name, bool(derived[name]), "boolean", "derived parser flag", 0.78, "derived_flag"))
    facts.append(_fact(doc, "new_vs_modification", derived["new_vs_modification"], "category", "derived parser taxonomy", 0.78, "derived_flag"))
    quality_flags = ";".join(derived.get("parser_quality_flags", []) or [])
    facts.append(_fact(doc, "parser_quality_flags", quality_flags, "text", quality_flags, 0.70, "derived_quality_flags"))
    facts.append(_fact(doc, "source_evidence_text", _norm_space(doc.text)[:700], "text", _norm_space(doc.text)[:700], 0.65, "source_excerpt"))
    return _dedupe_facts(facts)


def _facts_to_one_row(facts: list[GovernmentContractFact], doc: GovernmentContractSourceDocument) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": doc.event_id,
        "ticker": doc.ticker or doc.mapped_ticker,
        "event_time": doc.event_time.isoformat(),
        "source_type": doc.source_type,
        "source_url": doc.source_url,
        "release_session": doc.release_session,
        "mapping_type": doc.mapping_type,
    }
    for fact in sorted(facts, key=lambda f: f.confidence, reverse=True):
        row.setdefault(fact.fact_name, fact.value)
    return row


def derive_government_contract_fields(row: dict | pd.Series) -> dict[str, object]:
    event_type = _norm(row.get("government_contract_event_type"), "ambiguous_contract_event")
    award_type = _norm(row.get("award_type") or row.get("contract_type"))
    mapping_type = _normalize_mapping_type(row.get("mapping_type"))
    ticker = _norm(row.get("mapped_ticker") or row.get("ticker")).upper()
    recipient_mapping_confidence = _to_float(row.get("recipient_mapping_confidence"))
    award_amount = _to_float(row.get("award_amount"))
    obligated_amount = _to_float(row.get("obligated_amount"))
    contract_ceiling = _to_float(row.get("contract_ceiling"))
    text = " ".join(_norm(row.get(c)) for c in ["government_contract_event_type", "award_type", "contract_type", "product_or_service_description", "source_evidence_text"])
    low = text.lower()

    modification = event_type == "contract_modification" or bool(_norm(row.get("modification_number")))
    option = event_type == "option_exercise" or ("option" in low and "exercise" in low)
    subcontractor = event_type == "subcontract_award" or _norm(row.get("prime_or_sub")).lower() == "subcontractor" or "subcontract" in low
    prime = not subcontractor and _norm(row.get("prime_or_sub"), "prime").lower() in {"prime", "prime_contractor", "contractor"}
    ceiling_language = any(w in low for w in ["ceiling", "not-to-exceed", "not to exceed", "idiq", "indefinite delivery", "contract vehicle", "bpa", "boa"]) or event_type in {"idiq_vehicle_award", "contract_ceiling_only"}
    ceiling_only = bool(ceiling_language and pd.notna(contract_ceiling) and (pd.isna(obligated_amount) or obligated_amount <= 0))
    if event_type == "idiq_vehicle_award" and pd.isna(obligated_amount):
        ceiling_only = True
    actual_funded = bool(pd.notna(obligated_amount) and obligated_amount > 0 and not ceiling_only)
    if not actual_funded and not ceiling_only and pd.notna(award_amount) and award_amount > 0 and event_type not in {"idiq_vehicle_award", "contract_ceiling_only", "ambiguous_contract_event"}:
        actual_funded = True
    incumbent = event_type in {"contract_extension", "recompete_win", "option_exercise"} or any(w in low for w in ["incumbent", "extension", "recompete", "option year"])
    new_work = event_type in {"new_contract_award", "task_order_award", "sbir_award", "sttr_award", "ota_prototype_award", "production_contract", "recompete_win"} and not modification and not option and not ceiling_only
    high_mapping = _mapping_is_high(mapping_type, recipient_mapping_confidence, ticker)

    quality_flags = []
    if not high_mapping:
        quality_flags.append("recipient_mapping_not_high_confidence")
    if event_type == "ambiguous_contract_event":
        quality_flags.append("ambiguous_contract_event_type")
    if ceiling_only and actual_funded:
        quality_flags.append("conflicting_funded_and_ceiling_flags")
    if pd.isna(award_amount) and pd.isna(obligated_amount) and pd.isna(contract_ceiling):
        quality_flags.append("missing_contract_value")
    if event_type in {"idiq_vehicle_award", "contract_ceiling_only"} and actual_funded and pd.isna(obligated_amount):
        quality_flags.append("possible_idiq_ceiling_misread_as_funded")

    if modification:
        new_vs_modification = "modification"
    elif option:
        new_vs_modification = "option_exercise"
    elif ceiling_only:
        new_vs_modification = "capacity"
    else:
        new_vs_modification = "new_work" if new_work else "ambiguous"

    return {
        "actual_funded_award_flag": actual_funded,
        "ceiling_only_flag": ceiling_only,
        "modification_flag": modification,
        "option_exercise_flag": option,
        "new_work_flag": bool(new_work),
        "incumbent_or_extension_flag": bool(incumbent),
        "recompete_or_extension_flag": bool(incumbent),
        "prime_contractor_flag": bool(prime),
        "subcontractor_flag": bool(subcontractor),
        "recipient_mapping_confidence": recipient_mapping_confidence if pd.notna(recipient_mapping_confidence) else 0.0,
        "materiality_context_required_flag": bool(high_mapping and (pd.notna(award_amount) or pd.notna(obligated_amount) or pd.notna(contract_ceiling))),
        "new_vs_modification": new_vs_modification,
        "parser_quality_flags": quality_flags,
        "model_eligible_candidate_flag": bool(high_mapping and actual_funded and not quality_flags),
    }


def pivot_government_contract_facts(
    facts: pd.DataFrame,
    out_path: str | Path | None = None,
    *,
    min_confidence: float = 0.70,
) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame()
    else:
        usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
        rows = []
        for event_id, group in usable.groupby("event_id", sort=False):
            row = {
                "event_id": event_id,
                "ticker": _norm(group["ticker"].iloc[0]).upper(),
                "event_time": group["event_time"].iloc[0],
                "source_doc_ids": ";".join(sorted(group["source_doc_id"].astype(str).unique())),
                "usable_fact_count": int(len(group)),
                "source_type": group["source_type"].iloc[0],
                "source_url": group["source_url"].iloc[0],
                "release_session": "unknown",
            }
            for _, fact in group.sort_values("confidence", ascending=False).drop_duplicates("fact_name").iterrows():
                name = fact["fact_name"]
                row[name] = fact["value"]
                row[f"{name}_confidence"] = fact["confidence"]
                row[f"{name}_evidence"] = fact["evidence_text"]
            row.update(derive_government_contract_fields(row))
            if not _mapping_is_high(row.get("mapping_type"), row.get("recipient_mapping_confidence"), row.get("mapped_ticker") or row.get("ticker")):
                row["ticker"] = ""
            rows.append(row)
        out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def government_contract_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in features.iterrows():
        event_type = _norm(row.get("government_contract_event_type"), "ambiguous_contract_event")
        ticker = _norm(row.get("ticker")).upper()
        amount = _to_float(row.get("obligated_amount"))
        if pd.isna(amount):
            amount = _to_float(row.get("award_amount"))
        if pd.isna(amount):
            amount = _to_float(row.get("contract_ceiling"))
        magnitude = "unknown"
        if pd.notna(amount):
            magnitude = "high" if amount >= 250_000_000 else "medium" if amount >= 25_000_000 else "low"
        mapping_conf = _to_float(row.get("recipient_mapping_confidence"))
        review_notes = "Review recipient mapping, funded-vs-ceiling value, timestamp source, and whether this is new work before modeling."
        if not _mapping_is_high(row.get("mapping_type"), mapping_conf, row.get("mapped_ticker") or ticker):
            review_notes = "Recipient mapping is not high confidence; do not use for modeling until manually resolved. " + review_notes
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "event_time": row["event_time"],
                "event_type": "government_contract",
                "summary": f"{ticker or 'Unmapped recipient'} {event_type.replace('_', ' ')} candidate from source document.",
                "event_subtype": event_type,
                "event_family": GOVERNMENT_CONTRACT_DOMAIN,
                "source_type": row.get("source_type", "source_document"),
                "source_url": row.get("source_url", ""),
                "release_session": row.get("release_session", "unknown") or "unknown",
                "expectedness": "unknown",
                "surprise_direction": "unknown",
                "surprise_magnitude": magnitude,
                "materiality": 0.7 if _bool_value(row.get("actual_funded_award_flag")) and magnitude == "high" else 0.4 if _bool_value(row.get("ceiling_only_flag")) else 0.5,
                "sector_benchmark": row.get("sector_benchmark", ""),
                "notes": "Government-contract parser candidate; not model-ready until review, mapping audit, parser audit, and context gates pass.",
                "corpus_name": GOVERNMENT_CONTRACT_DOMAIN,
                "review_status": "unreviewed",
                "evidence_status": "source_backed",
                "label_quality": "machine_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "government_contract_event_type": event_type,
                "actual_funded_award_flag": bool(_bool_value(row.get("actual_funded_award_flag"))),
                "ceiling_only_flag": bool(_bool_value(row.get("ceiling_only_flag"))),
                "new_work_flag": bool(_bool_value(row.get("new_work_flag"))),
                "modification_flag": bool(_bool_value(row.get("modification_flag"))),
                "option_exercise_flag": bool(_bool_value(row.get("option_exercise_flag"))),
                "recipient_mapping_confidence": mapping_conf if pd.notna(mapping_conf) else 0.0,
                "award_amount": row.get("award_amount", np.nan),
                "obligated_amount": row.get("obligated_amount", np.nan),
                "contract_ceiling": row.get("contract_ceiling", np.nan),
                "agency": row.get("agency", ""),
                "product_or_service_description": row.get("product_or_service_description", ""),
                "materiality_pre_price": "",
                "drop_reason": "",
                "review_notes": review_notes,
                **{
                    c: row.get(c, "")
                    for c in features.columns
                    if c
                    not in {
                        "ticker",
                        "event_id",
                        "event_time",
                        "source_type",
                        "source_url",
                        "release_session",
                        "source_doc_ids",
                        "government_contract_event_type",
                        "actual_funded_award_flag",
                        "ceiling_only_flag",
                        "new_work_flag",
                        "modification_flag",
                        "option_exercise_flag",
                        "recipient_mapping_confidence",
                        "award_amount",
                        "obligated_amount",
                        "contract_ceiling",
                        "agency",
                        "product_or_service_description",
                    }
                },
            }
        )
    make_event_template(out_path, rows)
    return pd.read_csv(out_path)


def government_contract_mapping_audit(
    source_documents: pd.DataFrame,
    mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    df = source_documents.copy()
    for col in ["recipient_name", "mapped_ticker", "mapping_type", "recipient_mapping_confidence", "ticker"]:
        if col not in df.columns:
            df[col] = ""
    def first_nonblank(series: pd.Series, default: object = "") -> object:
        for value in series.dropna():
            if _norm(value):
                return value
        return default

    rows = []
    for recipient, group in df.groupby(df["recipient_name"].fillna("").astype(str), dropna=False):
        recipient_text = _norm(recipient)
        if not recipient_text:
            continue
        mapped = map_recipient_to_ticker(recipient_text, mapping)
        mapped_ticker = _norm(first_nonblank(group["mapped_ticker"], mapped["mapped_ticker"])).upper()
        mapping_type = _normalize_mapping_type(first_nonblank(group["mapping_type"], mapped["mapping_type"]))
        confidence = _to_float(first_nonblank(group["recipient_mapping_confidence"], mapped["recipient_mapping_confidence"]))
        model_eligible = _mapping_is_high(mapping_type, confidence, mapped_ticker)
        rows.append(
            {
                "recipient_name": recipient_text,
                "source_rows": int(len(group)),
                "mapped_ticker": mapped_ticker,
                "public_company_name": mapped.get("parent_company_name", ""),
                "subsidiary_name": mapped.get("subsidiary_name", ""),
                "mapping_type": mapping_type,
                "confidence": confidence if pd.notna(confidence) else 0.0,
                "model_eligible_mapping_flag": bool(model_eligible),
                "source_types": ";".join(sorted(group.get("source_type", pd.Series(dtype=str)).fillna("").astype(str).unique())),
                "sample_source_url": _norm(group.get("source_url", pd.Series(dtype=str)).dropna().astype(str).iloc[0] if group.get("source_url", pd.Series(dtype=str)).notna().any() else ""),
                "review_notes": "" if model_eligible else "Mapping requires manual review before model eligibility.",
            }
        )
    detail = pd.DataFrame(rows).sort_values(["model_eligible_mapping_flag", "source_rows", "recipient_name"], ascending=[True, False, True]).reset_index(drop=True)
    summary = {
        "source_rows": int(len(df)),
        "unique_recipients": int(len(detail)),
        "model_eligible_recipients": int(detail.get("model_eligible_mapping_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not detail.empty else 0,
        "model_eligible_source_rows": int(detail.loc[detail.get("model_eligible_mapping_flag", pd.Series(dtype=bool)).map(_bool_value), "source_rows"].sum()) if not detail.empty else 0,
        "mapping_type_counts": detail.get("mapping_type", pd.Series(dtype=str)).value_counts(dropna=False).to_dict(),
        "ticker_counts": df.get("ticker", pd.Series(dtype=str)).fillna("").astype(str).str.upper().replace("", np.nan).dropna().value_counts().head(20).to_dict(),
        "top_unmapped_or_ineligible_recipients": detail[~detail.get("model_eligible_mapping_flag", pd.Series(dtype=bool)).map(_bool_value)].head(25).to_dict("records") if not detail.empty else [],
    }
    return detail, summary


def write_government_contract_mapping_audit_report(
    source_documents_path: str | Path,
    mapping_path: str | Path,
    report_out: str | Path,
    detail_out: str | Path | None = None,
) -> dict[str, object]:
    source_documents = pd.read_csv(source_documents_path)
    mapping = load_recipient_ticker_map(mapping_path)
    detail, summary = government_contract_mapping_audit(source_documents, mapping)
    if detail_out:
        ensure_parent(detail_out)
        detail.to_csv(detail_out, index=False)
        summary["detail_out"] = str(detail_out)
    out = ensure_parent(report_out)
    lines = [
        "# Government Contract Recipient Mapping Audit",
        "",
        "This is an entity-mapping audit for source candidates. It is not a model result.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        if key in {"mapping_type_counts", "ticker_counts", "top_unmapped_or_ineligible_recipients"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Mapping Types", ""])
    for key, value in (summary.get("mapping_type_counts", {}) or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Ticker Counts", ""])
    for key, value in (summary.get("ticker_counts", {}) or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top Ineligible / Unmapped Recipients", ""])
    for row in summary.get("top_unmapped_or_ineligible_recipients", []) or []:
        lines.append(f"- {row.get('recipient_name')}: rows={row.get('source_rows')} mapping_type={row.get('mapping_type')} ticker={row.get('mapped_ticker')} confidence={row.get('confidence')}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary["report_out"] = str(out)
    return summary


def _source_is_idv(row: pd.Series | dict) -> bool:
    award_type = _norm(row.get("award_type") or row.get("contract_type")).lower()
    source_url = _norm(row.get("source_url")).lower()
    return any(term in award_type for term in ["indefinite delivery", "indefinite-delivery", "idiq"]) or "cont_idv" in source_url or award_type in {"bpa", "boa"}


def _reviewed_event_type_from_source(row: pd.Series | dict) -> str:
    text = _norm_space(
        " ".join(
            _norm(row.get(c))
            for c in [
                "award_type",
                "contract_type",
                "event_subtype",
                "title",
                "product_or_service_description",
                "text",
            ]
        )
    ).lower()
    if "subcontract" in text:
        return "subcontract_award"
    if "sttr" in text or "small business technology transfer" in text:
        return "sttr_award"
    if "sbir" in text or "small business innovation research" in text:
        return "sbir_award"
    if "other transaction" in text or re.search(r"\bota\b", text) or "prototype award" in text:
        return "ota_prototype_award"
    if "production contract" in text or "production award" in text:
        return "production_contract"
    if "recompete" in text or "re-compete" in text:
        return "recompete_win"
    if "option" in text and any(w in text for w in ["exercise", "exercised", "option year", "option period"]):
        return "option_exercise"
    if "modification" in text or re.search(r"\bmod(?:\s+|ification)", text):
        return "contract_modification"
    if "extension" in text or "extended" in text:
        return "contract_extension"
    if _source_is_idv(row):
        return "idiq_vehicle_award"
    if "delivery order" in text or "task order" in text or "bpa call" in text:
        return "task_order_award"
    if (
        pd.notna(_to_float(row.get("contract_ceiling")))
        or re.search(r"\b(?:ceiling|not-to-exceed|not to exceed|up to)\s+(?:of\s+)?\$?\s*\d", text)
    ):
        return "contract_ceiling_only"
    if any(w in text for w in ["awarded", "award", "contract"]):
        return "new_contract_award"
    return "ambiguous_contract_event"


def _reviewed_amounts_from_source(row: pd.Series | dict) -> dict[str, object]:
    award_amount = _to_float(row.get("award_amount"))
    obligated_amount = _to_float(row.get("obligated_amount"))
    contract_ceiling = _to_float(row.get("contract_ceiling"))
    is_idv = _source_is_idv(row)
    text = _norm_space(f"{row.get('text', '')} {row.get('product_or_service_description', '')}").lower()
    no_funds = any(term in text for term in ["no funds are obligated", "no funds obligated", "no funds will be obligated"])

    if is_idv and pd.isna(contract_ceiling) and pd.notna(award_amount):
        contract_ceiling = award_amount
    if is_idv:
        obligated_amount = np.nan
    elif pd.isna(obligated_amount) and not no_funds:
        obligated_amount = award_amount

    ceiling_only = bool(is_idv and pd.notna(contract_ceiling) and (pd.isna(obligated_amount) or obligated_amount <= 0))
    actual_funded = bool(pd.notna(obligated_amount) and obligated_amount > 0 and not ceiling_only and not no_funds)
    return {
        "award_amount": award_amount,
        "obligated_amount": obligated_amount,
        "contract_ceiling": contract_ceiling,
        "actual_funded_award_flag": actual_funded,
        "ceiling_only_flag": ceiling_only,
    }


def _audit_float_equal(actual: object, expected: object, tolerance: float = 1_000_000.0) -> bool:
    a = _to_float(actual)
    e = _to_float(expected)
    if pd.isna(a) and pd.isna(e):
        return True
    if pd.isna(a) or pd.isna(e):
        return False
    return abs(float(a) - float(e)) <= float(tolerance)


def _sample_audit_events(features: pd.DataFrame, target_events: int) -> tuple[pd.DataFrame, dict[str, object]]:
    if features.empty:
        return features.copy(), {"bucket_counts": {}, "bucket_shortfalls": {}}
    work = features.copy()
    work["_award_sort"] = pd.to_numeric(work.get("award_amount", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)
    selected: list[pd.DataFrame] = []
    seen: set[str] = set()
    bucket_counts: dict[str, int] = {}
    shortfalls: dict[str, int] = {}

    def add_bucket(name: str, pool: pd.DataFrame, n: int) -> None:
        nonlocal selected, seen
        if pool.empty:
            chosen = pool
        else:
            pool = pool[~pool["event_id"].astype(str).isin(seen)].copy()
            pool = pool.sort_values(["_award_sort", "event_id"], ascending=[False, True]).head(n)
            pool["audit_bucket"] = name
            seen.update(pool["event_id"].astype(str).tolist())
            selected.append(pool)
            chosen = pool
        bucket_counts[name] = int(len(chosen))
        if len(chosen) < n:
            shortfalls[name] = int(n - len(chosen))

    event_type = work.get("government_contract_event_type", pd.Series("", index=work.index)).fillna("").astype(str)
    mapping_conf = pd.to_numeric(work.get("recipient_mapping_confidence", pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0)
    mapping_type = work.get("mapping_type", pd.Series("", index=work.index)).fillna("").astype(str).map(_normalize_mapping_type)
    source_type = work.get("source_type", pd.Series("", index=work.index)).fillna("").astype(str)

    add_bucket("new_funded_awards", work[event_type.eq("new_contract_award") & work.get("actual_funded_award_flag", pd.Series(False, index=work.index)).map(_bool_value)], 15)
    add_bucket("task_orders", work[event_type.eq("task_order_award")], 10)
    add_bucket("modifications_options", work[event_type.isin({"contract_modification", "option_exercise", "contract_extension"}) | work.get("modification_flag", pd.Series(False, index=work.index)).map(_bool_value) | work.get("option_exercise_flag", pd.Series(False, index=work.index)).map(_bool_value)], 10)
    add_bucket("idiq_ceiling", work[event_type.isin({"idiq_vehicle_award", "contract_ceiling_only"}) | work.get("ceiling_only_flag", pd.Series(False, index=work.index)).map(_bool_value)], 10)
    add_bucket("sbir_sttr_ota", work[event_type.isin({"sbir_award", "sttr_award", "ota_prototype_award"})], 5)
    add_bucket("public_announcement_style", work[source_type.str.contains("dod|press|sec|company", case=False, na=False)], 5)
    add_bucket("ambiguous_subsidiary_mapping", work[(mapping_conf < 0.80) | ~mapping_type.isin(MODEL_ELIGIBLE_MAPPING_TYPES)], 5)

    chosen = pd.concat(selected, ignore_index=True, sort=False) if selected else pd.DataFrame()
    if len(chosen) < target_events:
        remaining = work[~work["event_id"].astype(str).isin(seen)].sort_values(["_award_sort", "event_id"], ascending=[False, True]).head(target_events - len(chosen)).copy()
        remaining["audit_bucket"] = "materiality_backfill"
        chosen = pd.concat([chosen, remaining], ignore_index=True, sort=False)
        bucket_counts["materiality_backfill"] = int(len(remaining))
    chosen = chosen.head(target_events).drop(columns=["_award_sort"], errors="ignore")
    return chosen, {"bucket_counts": bucket_counts, "bucket_shortfalls": shortfalls}


def _gold_rows_from_human_audit(audit: pd.DataFrame) -> pd.DataFrame:
    fact_map = {
        "government_contract_event_type": "reviewed_government_contract_event_type",
        "mapped_ticker": "reviewed_mapped_ticker",
        "recipient_mapping_confidence": "reviewed_recipient_mapping_confidence",
        "award_amount": "reviewed_award_amount",
        "obligated_amount": "reviewed_obligated_amount",
        "contract_ceiling": "reviewed_contract_ceiling",
        "actual_funded_award_flag": "reviewed_actual_funded_award_flag",
        "ceiling_only_flag": "reviewed_ceiling_only_flag",
        "option_exercise_flag": "reviewed_option_exercise_flag",
        "modification_flag": "reviewed_modification_flag",
    }
    rows: list[dict[str, object]] = []
    for _, row in audit.iterrows():
        for fact_name, source_col in fact_map.items():
            value = row.get(source_col)
            expected_present = not _is_missing(value) and _norm(value) != ""
            if fact_name in {"award_amount", "obligated_amount", "contract_ceiling"} and not expected_present:
                continue
            rows.append(
                {
                    "event_id": row.get("event_id"),
                    "fact_name": fact_name,
                    "expected_value": value if expected_present else "",
                    "unit": _gold_fact_unit(fact_name),
                    "tolerance": 1_000_000.0 if fact_name in {"award_amount", "obligated_amount", "contract_ceiling"} else "",
                    "expected_present": expected_present,
                    "gold_review_status": "reviewed",
                    "gold_bucket": row.get("audit_bucket", ""),
                    "reviewer_notes": row.get("audit_notes", ""),
                }
            )
    return pd.DataFrame(rows)


def _apply_audit_to_events(events: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    if events.empty or audit.empty or "event_id" not in events.columns:
        return events.copy()
    out = events.copy()
    audit_by_event = audit.drop_duplicates("event_id").set_index("event_id")
    for col in ["review_status", "evidence_status", "label_quality", "drop_reason", "review_notes"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype("object")
    for col in [
        "audit_bucket",
        "audit_model_eligible_flag",
        "audit_timestamp_suitable_flag",
        "audit_public_awareness_evidence_status",
        "audit_recipient_mapping_correct_flag",
        "audit_funded_vs_ceiling_correct_flag",
    ]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype("object")
    for idx, row in out.iterrows():
        event_id = _norm(row.get("event_id"))
        if event_id not in audit_by_event.index:
            continue
        audited = audit_by_event.loc[event_id]
        out.at[idx, "review_status"] = _norm(audited.get("review_status"), "rejected")
        out.at[idx, "evidence_status"] = _norm(audited.get("public_awareness_evidence_status"))
        out.at[idx, "label_quality"] = "human_audit"
        out.at[idx, "drop_reason"] = _norm(audited.get("drop_reason"))
        out.at[idx, "review_notes"] = _norm(audited.get("audit_notes"))
        out.at[idx, "audit_bucket"] = _norm(audited.get("audit_bucket"))
        out.at[idx, "audit_model_eligible_flag"] = bool(_bool_value(audited.get("model_eligible_after_audit")))
        out.at[idx, "audit_timestamp_suitable_flag"] = bool(_bool_value(audited.get("timestamp_suitable_flag")))
        out.at[idx, "audit_public_awareness_evidence_status"] = _norm(audited.get("public_awareness_evidence_status"))
        out.at[idx, "audit_recipient_mapping_correct_flag"] = bool(_bool_value(audited.get("recipient_mapping_correct_flag")))
        out.at[idx, "audit_funded_vs_ceiling_correct_flag"] = bool(_bool_value(audited.get("funded_vs_ceiling_correct_flag")))
    return out


def build_government_contract_human_audit(
    source_documents: pd.DataFrame,
    features: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    events: pd.DataFrame | None = None,
    target_events: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None, dict[str, object]]:
    selected, sample_summary = _sample_audit_events(features, target_events)
    source_by_event = source_documents.drop_duplicates("event_id").set_index("event_id") if "event_id" in source_documents.columns and not source_documents.empty else pd.DataFrame()
    audit_rows: list[dict[str, object]] = []
    for _, feature in selected.iterrows():
        event_id = _norm(feature.get("event_id"))
        source = source_by_event.loc[event_id] if not source_by_event.empty and event_id in source_by_event.index else feature
        recipient = _norm(source.get("recipient_name") or feature.get("recipient_name"))
        mapped = map_recipient_to_ticker(recipient, mapping)
        reviewed_ticker = _norm(mapped.get("mapped_ticker")).upper() if _mapping_is_high(mapped.get("mapping_type"), mapped.get("recipient_mapping_confidence"), mapped.get("mapped_ticker")) else ""
        reviewed_mapping_type = _normalize_mapping_type(mapped.get("mapping_type"))
        reviewed_mapping_conf = _to_float(mapped.get("recipient_mapping_confidence"))
        mapping_model_eligible = _mapping_is_high(reviewed_mapping_type, reviewed_mapping_conf, reviewed_ticker)
        parsed_ticker = _norm(feature.get("mapped_ticker") or feature.get("ticker")).upper()
        parsed_mapping_conf = _to_float(feature.get("recipient_mapping_confidence"))
        mapping_correct = parsed_ticker == reviewed_ticker and _normalize_mapping_type(feature.get("mapping_type")) == reviewed_mapping_type

        reviewed_event_type = _reviewed_event_type_from_source(source)
        reviewed_amounts = _reviewed_amounts_from_source(source)
        reviewed_modification = reviewed_event_type == "contract_modification" or bool(_norm(source.get("modification_number")))
        reviewed_option = reviewed_event_type == "option_exercise"
        event_type_correct = _norm(feature.get("government_contract_event_type")) == reviewed_event_type
        amount_correct = (
            _audit_float_equal(feature.get("award_amount"), reviewed_amounts["award_amount"])
            and _audit_float_equal(feature.get("obligated_amount"), reviewed_amounts["obligated_amount"])
            and _audit_float_equal(feature.get("contract_ceiling"), reviewed_amounts["contract_ceiling"])
        )
        funded_correct = (
            _bool_value(feature.get("actual_funded_award_flag")) == bool(reviewed_amounts["actual_funded_award_flag"])
            and _bool_value(feature.get("ceiling_only_flag")) == bool(reviewed_amounts["ceiling_only_flag"])
            and _bool_value(feature.get("modification_flag")) == bool(reviewed_modification)
            and _bool_value(feature.get("option_exercise_flag")) == bool(reviewed_option)
        )

        source_type = _norm(source.get("source_type") or feature.get("source_type")).lower()
        release_session = _norm(source.get("release_session") or feature.get("release_session"), "unknown").lower()
        has_public_announcement_source = bool(re.search(r"dod|press|sec|company", source_type, re.I))
        timestamp_suitable = bool(has_public_announcement_source and release_session not in {"unknown", ""})
        if timestamp_suitable:
            public_awareness = "public_announcement_timestamp_available"
        elif source_type == "usaspending_api":
            public_awareness = "usaspending_record_only_not_market_timestamp"
        else:
            public_awareness = "public_timestamp_not_established"

        drop_reasons: list[str] = []
        if not mapping_model_eligible:
            drop_reasons.append("recipient_mapping_not_model_eligible")
        if not mapping_correct:
            drop_reasons.append("recipient_mapping_mismatch")
        if not amount_correct or not funded_correct:
            drop_reasons.append("funded_vs_ceiling_or_amount_mismatch")
        if not timestamp_suitable:
            drop_reasons.append("timestamp_public_awareness_insufficient")
        model_eligible = bool(
            mapping_model_eligible
            and mapping_correct
            and amount_correct
            and funded_correct
            and timestamp_suitable
            and bool(reviewed_amounts["actual_funded_award_flag"])
            and not bool(reviewed_amounts["ceiling_only_flag"])
            and reviewed_event_type != "ambiguous_contract_event"
        )
        review_status = "approved" if model_eligible else "rejected"
        audit_rows.append(
            {
                "event_id": event_id,
                "audit_bucket": _norm(feature.get("audit_bucket")),
                "source_doc_ids": _norm(feature.get("source_doc_ids") or source.get("source_doc_id")),
                "source_type": source_type,
                "source_url": _norm(source.get("source_url") or feature.get("source_url")),
                "event_time": _norm(feature.get("event_time") or source.get("event_time")),
                "release_session": release_session,
                "recipient_name": recipient,
                "parsed_ticker": parsed_ticker,
                "reviewed_mapped_ticker": reviewed_ticker,
                "parsed_mapping_type": _normalize_mapping_type(feature.get("mapping_type")),
                "reviewed_mapping_type": reviewed_mapping_type,
                "parsed_recipient_mapping_confidence": parsed_mapping_conf if pd.notna(parsed_mapping_conf) else 0.0,
                "reviewed_recipient_mapping_confidence": reviewed_mapping_conf if pd.notna(reviewed_mapping_conf) else 0.0,
                "recipient_mapping_correct_flag": bool(mapping_correct),
                "mapping_model_eligible_flag": bool(mapping_model_eligible),
                "parsed_government_contract_event_type": _norm(feature.get("government_contract_event_type")),
                "reviewed_government_contract_event_type": reviewed_event_type,
                "event_type_correct_flag": bool(event_type_correct),
                "parsed_award_amount": feature.get("award_amount"),
                "reviewed_award_amount": reviewed_amounts["award_amount"],
                "parsed_obligated_amount": feature.get("obligated_amount"),
                "reviewed_obligated_amount": reviewed_amounts["obligated_amount"],
                "parsed_contract_ceiling": feature.get("contract_ceiling"),
                "reviewed_contract_ceiling": reviewed_amounts["contract_ceiling"],
                "amount_correct_flag": bool(amount_correct),
                "parsed_actual_funded_award_flag": bool(_bool_value(feature.get("actual_funded_award_flag"))),
                "reviewed_actual_funded_award_flag": bool(reviewed_amounts["actual_funded_award_flag"]),
                "parsed_ceiling_only_flag": bool(_bool_value(feature.get("ceiling_only_flag"))),
                "reviewed_ceiling_only_flag": bool(reviewed_amounts["ceiling_only_flag"]),
                "parsed_modification_flag": bool(_bool_value(feature.get("modification_flag"))),
                "reviewed_modification_flag": bool(reviewed_modification),
                "parsed_option_exercise_flag": bool(_bool_value(feature.get("option_exercise_flag"))),
                "reviewed_option_exercise_flag": bool(reviewed_option),
                "funded_vs_ceiling_correct_flag": bool(funded_correct),
                "timestamp_suitable_flag": bool(timestamp_suitable),
                "public_awareness_evidence_status": public_awareness,
                "model_eligible_after_audit": bool(model_eligible),
                "review_status": review_status,
                "drop_reason": ";".join(drop_reasons),
                "audit_notes": "Reviewed against structured official source fields and recipient map. USAspending-only rows are not market-public timestamps.",
            }
        )
    audit = pd.DataFrame(audit_rows)
    gold = _gold_rows_from_human_audit(audit)
    mapping_errors = audit[(~audit.get("recipient_mapping_correct_flag", pd.Series(dtype=bool)).map(_bool_value)) | (~audit.get("mapping_model_eligible_flag", pd.Series(dtype=bool)).map(_bool_value))].copy() if not audit.empty else pd.DataFrame()
    funded_errors = audit[(~audit.get("amount_correct_flag", pd.Series(dtype=bool)).map(_bool_value)) | (~audit.get("funded_vs_ceiling_correct_flag", pd.Series(dtype=bool)).map(_bool_value))].copy() if not audit.empty else pd.DataFrame()
    audited_events = _apply_audit_to_events(events, audit) if events is not None else None

    def rate(col: str) -> float:
        return float(audit[col].map(_bool_value).mean()) if not audit.empty and col in audit.columns else 0.0

    summary: dict[str, object] = {
        "audit_rows": int(len(audit)),
        "audit_model_eligible_rows": int(audit.get("model_eligible_after_audit", pd.Series(dtype=bool)).map(_bool_value).sum()) if not audit.empty else 0,
        "reviewed_gold_rows": int(len(gold)),
        "reviewed_gold_events": int(gold["event_id"].nunique()) if not gold.empty else 0,
        "recipient_mapping_correct_rate": rate("recipient_mapping_correct_flag"),
        "mapping_model_eligible_rate": rate("mapping_model_eligible_flag"),
        "event_type_correct_rate": rate("event_type_correct_flag"),
        "amount_correct_rate": rate("amount_correct_flag"),
        "funded_vs_ceiling_correct_rate": rate("funded_vs_ceiling_correct_flag"),
        "timestamp_suitable_rows": int(audit.get("timestamp_suitable_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not audit.empty else 0,
        "public_awareness_status_counts": audit.get("public_awareness_evidence_status", pd.Series(dtype=str)).value_counts(dropna=False).to_dict() if not audit.empty else {},
        **sample_summary,
    }
    if summary["timestamp_suitable_rows"] == 0:
        summary["verdict"] = "timestamp/public-awareness insufficient"
    elif summary["recipient_mapping_correct_rate"] < 0.90:
        summary["verdict"] = "mapping insufficient"
    elif summary["funded_vs_ceiling_correct_rate"] < 0.95:
        summary["verdict"] = "funded-vs-ceiling classification insufficient"
    elif summary["event_type_correct_rate"] < 0.95:
        summary["verdict"] = "parser not trusted"
    else:
        summary["verdict"] = "continue corpus buildout"
    return audit, gold, mapping_errors, funded_errors, audited_events, summary


def write_government_contract_human_audit_report(summary: dict[str, object], audit: pd.DataFrame, mapping_errors: pd.DataFrame, funded_errors: pd.DataFrame, out_path: str | Path) -> Path:
    out = ensure_parent(out_path)
    lines = [
        "# Government Contract Human Audit Report",
        "",
        "This is a corpus audit report, not a prediction result.",
        "",
        "## Verdict",
        "",
        f"- verdict: {summary.get('verdict')}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        if key in {"bucket_counts", "bucket_shortfalls", "public_awareness_status_counts", "verdict"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Audit Buckets", ""])
    for key, value in (summary.get("bucket_counts", {}) or {}).items():
        lines.append(f"- {key}: {value}")
    if summary.get("bucket_shortfalls"):
        lines.extend(["", "## Bucket Shortfalls", ""])
        for key, value in (summary.get("bucket_shortfalls", {}) or {}).items():
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Public Awareness Evidence", ""])
    for key, value in (summary.get("public_awareness_status_counts", {}) or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Mapping Errors / Ineligible Rows", ""])
    if mapping_errors.empty:
        lines.append("- none")
    else:
        for _, row in mapping_errors.head(40).iterrows():
            lines.append(f"- {row.get('event_id')}: recipient={row.get('recipient_name')} parsed={row.get('parsed_ticker')} reviewed={row.get('reviewed_mapped_ticker')} reason={row.get('drop_reason')}")
    lines.extend(["", "## Funded Vs Ceiling Errors", ""])
    if funded_errors.empty:
        lines.append("- none")
    else:
        for _, row in funded_errors.head(40).iterrows():
            lines.append(f"- {row.get('event_id')}: type={row.get('reviewed_government_contract_event_type')} reason={row.get('drop_reason')}")
    lines.extend(["", "## Audited Rows", ""])
    for _, row in audit.head(80).iterrows():
        lines.append(f"- {row.get('event_id')}: bucket={row.get('audit_bucket')} recipient={row.get('recipient_name')} model_eligible={row.get('model_eligible_after_audit')} drop_reason={row.get('drop_reason')}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def parse_government_contract_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
    *,
    min_confidence: float = 0.0,
    usable_confidence: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_government_contract_documents(documents_path)
    rows: list[dict] = []
    for doc in docs:
        for fact in parse_government_contract_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows)
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    features = pivot_government_contract_facts(facts, features_out, min_confidence=usable_confidence)
    events = government_contract_features_to_events(features, events_out)
    return facts, features, events


def _gold_fact_unit(fact_name: str) -> str:
    if fact_name in {"award_amount", "obligated_amount", "contract_ceiling"}:
        return "usd"
    if fact_name in {"actual_funded_award_flag", "ceiling_only_flag", "option_exercise_flag", "modification_flag"}:
        return "boolean"
    if fact_name == "recipient_mapping_confidence":
        return "ratio"
    return "category" if fact_name == "government_contract_event_type" else "text"


def build_government_contract_parser_gold_template(
    features: pd.DataFrame,
    out_path: str | Path,
    *,
    target_events: int = 60,
) -> pd.DataFrame:
    if features.empty:
        out = pd.DataFrame(columns=["event_id", "fact_name", "expected_value", "unit", "tolerance", "expected_present", "gold_review_status", "gold_bucket", "reviewer_notes"])
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
        return out

    pools = [
        ("new_funded", features[features.get("actual_funded_award_flag", pd.Series(False, index=features.index)).map(_bool_value) & features.get("new_work_flag", pd.Series(False, index=features.index)).map(_bool_value)].head(15)),
        ("task_orders", features[features.get("government_contract_event_type", pd.Series("", index=features.index)).astype(str).eq("task_order_award")].head(10)),
        ("modifications_options", features[features.get("modification_flag", pd.Series(False, index=features.index)).map(_bool_value) | features.get("option_exercise_flag", pd.Series(False, index=features.index)).map(_bool_value)].head(10)),
        ("idiq_ceiling", features[features.get("ceiling_only_flag", pd.Series(False, index=features.index)).map(_bool_value) | features.get("government_contract_event_type", pd.Series("", index=features.index)).astype(str).isin({"idiq_vehicle_award", "contract_ceiling_only"})].head(10)),
        ("sbir_sttr_ota", features[features.get("government_contract_event_type", pd.Series("", index=features.index)).astype(str).isin({"sbir_award", "sttr_award", "ota_prototype_award"})].head(5)),
        ("press_release", features[features.get("source_type", pd.Series("", index=features.index)).astype(str).str.contains("press", case=False, na=False)].head(5)),
        ("ambiguous_mapping", features[pd.to_numeric(features.get("recipient_mapping_confidence", pd.Series(0.0, index=features.index)), errors="coerce").fillna(0.0).lt(0.80)].head(5)),
    ]
    selected: list[pd.DataFrame] = []
    seen: set[str] = set()
    for _, pool in pools:
        if pool.empty:
            continue
        pool = pool[~pool["event_id"].astype(str).isin(seen)].copy()
        seen.update(pool["event_id"].astype(str).tolist())
        selected.append(pool)
    chosen = pd.concat(selected, ignore_index=True, sort=False) if selected else pd.DataFrame()
    if len(chosen) < target_events:
        remainder = features[~features["event_id"].astype(str).isin(seen)].head(target_events - len(chosen))
        chosen = pd.concat([chosen, remainder], ignore_index=True, sort=False)
    chosen = chosen.head(target_events)

    fact_names = [
        "government_contract_event_type",
        "mapped_ticker",
        "recipient_mapping_confidence",
        "award_amount",
        "obligated_amount",
        "contract_ceiling",
        "actual_funded_award_flag",
        "ceiling_only_flag",
        "option_exercise_flag",
        "modification_flag",
    ]
    rows = []
    for _, row in chosen.iterrows():
        bucket = "general"
        event_type = _norm(row.get("government_contract_event_type"))
        if event_type in {"idiq_vehicle_award", "contract_ceiling_only"}:
            bucket = "idiq_ceiling"
        elif event_type == "task_order_award":
            bucket = "task_orders"
        elif event_type in {"contract_modification", "option_exercise"}:
            bucket = "modifications_options"
        elif event_type in {"sbir_award", "sttr_award", "ota_prototype_award"}:
            bucket = "sbir_sttr_ota"
        elif pd.to_numeric(pd.Series([row.get("recipient_mapping_confidence")]), errors="coerce").fillna(0.0).iloc[0] < 0.80:
            bucket = "ambiguous_mapping"
        for fact_name in fact_names:
            value = row.get(fact_name, np.nan)
            expected_present = not (pd.isna(value) if not isinstance(value, (bool, list, dict, tuple)) else False)
            if fact_name in {"award_amount", "obligated_amount", "contract_ceiling"} and not expected_present:
                continue
            rows.append(
                {
                    "event_id": row.get("event_id"),
                    "fact_name": fact_name,
                    "expected_value": value if expected_present else "",
                    "unit": _gold_fact_unit(fact_name),
                    "tolerance": 1_000_000.0 if fact_name in {"award_amount", "obligated_amount", "contract_ceiling"} else "",
                    "expected_present": expected_present,
                    "gold_review_status": "needs_human_review",
                    "gold_bucket": bucket,
                    "reviewer_notes": "Machine-proposed gold row; human review required before parser audit can pass.",
                }
            )
    out = pd.DataFrame(rows)
    ensure_parent(out_path)
    out.to_csv(out_path, index=False)
    return out


def validate_government_contract_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    out_errors: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame(columns=["event_id", "fact_name", "expected_value", "actual_value", "unit", "tolerance", "abs_error", "status", "confidence", "evidence_text"])
        if out_errors:
            ensure_parent(out_errors)
            errors.to_csv(out_errors, index=False)
        return errors, {
            "gold_rows": 0,
            "status": "no_gold_rows",
            "audit_gate_results": {
                "gold_set_60_rows": False,
                "event_type_precision_95": False,
                "recipient_ticker_mapping_precision_90": False,
                "award_and_obligated_amount_precision_95": False,
                "ceiling_vs_funded_distinction_precision_95": False,
                "option_modification_precision_90": False,
                "no_idiq_ceiling_mistaken_for_funded": False,
            },
        }

    if "gold_review_status" in gold.columns:
        status = gold["gold_review_status"].fillna("").astype(str).str.lower().str.strip()
        reviewed_gold = gold[status.isin({"reviewed", "approved", "human_reviewed"})].copy()
        if reviewed_gold.empty:
            errors = gold.copy()
            errors["actual_value"] = ""
            errors["abs_error"] = np.nan
            errors["status"] = "gold_not_reviewed"
            errors["confidence"] = np.nan
            errors["evidence_text"] = ""
            if out_errors:
                ensure_parent(out_errors)
                errors.to_csv(out_errors, index=False)
            return errors, {
                "gold_rows": int(len(gold)),
                "gold_events": int(gold["event_id"].nunique()) if "event_id" in gold.columns else 0,
                "reviewed_gold_rows": 0,
                "reviewed_gold_events": 0,
                "correct_rows": 0,
                "row_accuracy": 0.0,
                "status": "gold_set_requires_human_review",
                "by_fact": {},
                "audit_gate_results": {
                    "gold_set_60_rows": False,
                    "gold_set_human_reviewed": False,
                    "event_type_precision_95": False,
                    "recipient_ticker_mapping_precision_90": False,
                    "award_and_obligated_amount_precision_95": False,
                    "ceiling_vs_funded_distinction_precision_95": False,
                    "option_modification_precision_90": False,
                    "no_idiq_ceiling_mistaken_for_funded": False,
                },
                "parser_audit_pass": False,
            }
        gold_for_validation = reviewed_gold
    else:
        gold_for_validation = gold

    pred = facts.copy()
    pred["confidence"] = pd.to_numeric(pred.get("confidence"), errors="coerce")
    pred = pred.sort_values("confidence", ascending=False).drop_duplicates(["event_id", "fact_name"], keep="first")

    key_cols = ["event_id", "fact_name"]
    merged = gold_for_validation.merge(pred, on=key_cols, how="left", suffixes=("_gold", "_pred"))
    tolerance_by_unit = {"usd": 1_000_000.0, "ratio": 0.001, "boolean": 0.0}
    rows: list[dict] = []
    for _, row in merged.iterrows():
        unit = _norm(row.get("unit_gold") or row.get("unit_pred"))
        expected_raw = row.get("expected_value")
        actual_raw = row.get("value")
        tolerance_raw = pd.to_numeric(pd.Series([row.get("tolerance")]), errors="coerce").iloc[0]
        tolerance = float(tolerance_raw) if pd.notna(tolerance_raw) else float(tolerance_by_unit.get(unit, 0.0))
        expected_present = _bool_value(row.get("expected_present", True))
        if not expected_present:
            status = "ok" if pd.isna(actual_raw) else "false_positive"
            abs_error = np.nan
        elif unit in {"category", "text", "date"}:
            expected = _norm_space(expected_raw).lower()
            actual = _norm_space(actual_raw).lower() if pd.notna(actual_raw) else ""
            status = "ok" if actual == expected else "wrong_value" if actual else "missed"
            abs_error = np.nan
        elif unit == "boolean":
            expected = _bool_value(expected_raw)
            actual = _bool_value(actual_raw) if pd.notna(actual_raw) else np.nan
            status = "ok" if actual == expected else "wrong_value" if pd.notna(actual_raw) else "missed"
            abs_error = np.nan
        else:
            expected = pd.to_numeric(pd.Series([expected_raw]), errors="coerce").iloc[0]
            actual = pd.to_numeric(pd.Series([actual_raw]), errors="coerce").iloc[0]
            if pd.isna(actual):
                status = "missed"
                abs_error = np.nan
            else:
                abs_error = abs(float(actual) - float(expected))
                status = "ok" if abs_error <= tolerance else "wrong_value"
        rows.append(
            {
                **{c: row.get(c) for c in key_cols},
                "expected_value": expected_raw,
                "actual_value": actual_raw,
                "unit": unit,
                "tolerance": tolerance,
                "abs_error": abs_error,
                "status": status,
                "confidence": row.get("confidence"),
                "evidence_text": row.get("evidence_text_pred", row.get("evidence_text", "")),
            }
        )
    errors = pd.DataFrame(rows)
    metrics = {}
    for fact_name, group in errors.groupby("fact_name"):
        total = int(len(group))
        ok = int((group["status"] == "ok").sum())
        metrics[fact_name] = {"gold_rows": total, "correct": ok, "precision_on_gold": ok / total if total else 0.0}

    def fact_score(names: set[str]) -> float:
        subset = errors[errors["fact_name"].isin(names)]
        return float((subset["status"] == "ok").mean()) if len(subset) else 0.0

    idiq_bad = errors[
        (errors["fact_name"].isin({"actual_funded_award_flag", "ceiling_only_flag"}))
        & (errors["status"] != "ok")
        & errors["event_id"].astype(str).str.contains("idiq|ceiling", case=False, regex=True)
    ]
    gates = {
        "gold_set_60_rows": int(gold_for_validation["event_id"].nunique()) >= 60,
        "gold_set_human_reviewed": True,
        "event_type_precision_95": fact_score({"government_contract_event_type"}) >= 0.95,
        "recipient_ticker_mapping_precision_90": fact_score({"mapped_ticker", "recipient_mapping_confidence"}) >= 0.90,
        "award_and_obligated_amount_precision_95": fact_score({"award_amount", "obligated_amount"}) >= 0.95,
        "ceiling_vs_funded_distinction_precision_95": fact_score({"contract_ceiling", "actual_funded_award_flag", "ceiling_only_flag"}) >= 0.95,
        "option_modification_precision_90": fact_score({"option_exercise_flag", "modification_flag", "government_contract_event_type"}) >= 0.90,
        "no_idiq_ceiling_mistaken_for_funded": idiq_bad.empty,
    }
    report = {
        "gold_rows": int(len(errors)),
        "gold_events": int(gold_for_validation["event_id"].nunique()) if "event_id" in gold_for_validation.columns else 0,
        "reviewed_gold_rows": int(len(gold_for_validation)),
        "reviewed_gold_events": int(gold_for_validation["event_id"].nunique()) if "event_id" in gold_for_validation.columns else 0,
        "correct_rows": int((errors["status"] == "ok").sum()),
        "row_accuracy": float((errors["status"] == "ok").mean()) if len(errors) else 0.0,
        "by_fact": metrics,
        "audit_gate_results": gates,
        "parser_audit_pass": bool(all(gates.values())),
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def write_government_contract_parser_audit_report(report: dict[str, object], errors: pd.DataFrame, out_path: str | Path) -> Path:
    out = ensure_parent(out_path)
    lines = [
        "# Government Contract Parser Audit Report",
        "",
        "This validates parser facts against a reviewed gold set. It is a parser-quality report, not a model result.",
        "",
        "## Metrics",
        "",
        f"- gold_rows: {report.get('gold_rows', 0)}",
        f"- gold_events: {report.get('gold_events', 0)}",
        f"- reviewed_gold_rows: {report.get('reviewed_gold_rows', 0)}",
        f"- reviewed_gold_events: {report.get('reviewed_gold_events', 0)}",
        f"- correct_rows: {report.get('correct_rows', 0)}",
        f"- row_accuracy: {report.get('row_accuracy', 0):.3f}" if "row_accuracy" in report else f"- status: {report.get('status', 'unknown')}",
        f"- parser_audit_pass: {report.get('parser_audit_pass', False)}",
        "",
        "## Audit Gates",
        "",
    ]
    for gate, passed in (report.get("audit_gate_results", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## By Fact", ""])
    for fact_name, metrics in (report.get("by_fact", {}) or {}).items():
        lines.append(f"- {fact_name}: {metrics}")
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            lines.append(f"- {row['event_id']} / {row['fact_name']}: {row['status']} expected={row['expected_value']} actual={row['actual_value']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _load_optional_context(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _lookup_external_context_row(row: pd.Series, context: pd.DataFrame) -> pd.Series:
    if context.empty:
        return pd.Series(dtype=object)
    event_id = _norm(row.get("event_id"))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str) == event_id]
        if not matched.empty:
            return matched.iloc[0]
    if "ticker" not in context.columns:
        return pd.Series(dtype=object)
    ticker = _norm(row.get("ticker")).upper()
    subset = context[context["ticker"].astype(str).str.upper() == ticker].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    sort_col = "asof_date" if "asof_date" in subset.columns else ""
    if sort_col:
        subset[sort_col] = pd.to_datetime(subset[sort_col], errors="coerce").dt.tz_localize(None)
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            event_time = event_time.tz_localize(None) if getattr(event_time, "tzinfo", None) else event_time
            subset = subset[subset[sort_col] <= event_time]
        subset = subset.sort_values(sort_col, ascending=False)
    if subset.empty:
        return pd.Series(dtype=object)
    return subset.iloc[0]


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    session = _norm(release_session).lower()
    include_same_day = session in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), _to_float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"] == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = idx - int(window)
    if start_idx < 0:
        return np.nan
    start = _to_float(prices.iloc[start_idx]["adj_close"])
    end = _to_float(prices.iloc[idx]["adj_close"])
    if pd.isna(start) or pd.isna(end) or start == 0:
        return np.nan
    return end / start - 1.0


def _ratio(numerator: object, denominator: object) -> float:
    num = _to_float(numerator)
    den = _to_float(denominator)
    if pd.notna(num) and pd.notna(den) and den:
        return num / den
    return np.nan


def _size_bucket(market_cap: object) -> str:
    mc = _to_float(market_cap)
    if pd.isna(mc):
        return "unknown"
    if mc < 2_000_000_000:
        return "small_cap"
    if mc < 10_000_000_000:
        return "mid_cap"
    return "large_cap"


def enrich_government_contract_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
    revenue_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = _load_optional_context(market_caps_path)
    revenue = _load_optional_context(revenue_path)
    price_cache: dict[str, pd.DataFrame] = {}
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()

    enriched_rows: list[dict] = []
    for _, row in events.iterrows():
        out = row.to_dict()
        ticker = _norm(row.get("ticker")).upper()
        status: list[str] = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")
        if benchmark_prices.empty:
            status.append("missing_benchmark_prices")

        anchor_date = None
        last_close = np.nan
        if not prices.empty:
            anchor_date, last_close = _anchor_price(prices, row.get("event_time"), row.get("release_session"))
            if pd.isna(last_close):
                status.append("missing_pre_event_close")
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close

        market_cap_row = _lookup_external_context_row(row, market_caps)
        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap) and not market_cap_row.empty:
            market_cap = _to_float(market_cap_row.get("market_cap_before_event"))
        out["market_cap_before_event"] = market_cap
        if pd.isna(market_cap):
            status.append("missing_market_cap")

        revenue_row = _lookup_external_context_row(row, revenue)
        revenue_ltm = _to_float(row.get("revenue_ltm_if_available", np.nan))
        if pd.isna(revenue_ltm) and not revenue_row.empty:
            revenue_ltm = _to_float(revenue_row.get("revenue_ltm_if_available"))
        out["revenue_ltm_if_available"] = revenue_ltm

        out["award_amount_pct_market_cap"] = _ratio(row.get("award_amount"), market_cap)
        out["obligated_amount_pct_market_cap"] = _ratio(row.get("obligated_amount"), market_cap)
        out["contract_ceiling_pct_market_cap"] = _ratio(row.get("contract_ceiling"), market_cap)
        out["award_amount_pct_revenue"] = _ratio(row.get("award_amount"), revenue_ltm)
        out["obligated_amount_pct_revenue"] = _ratio(row.get("obligated_amount"), revenue_ltm)
        out["contract_ceiling_pct_revenue"] = _ratio(row.get("contract_ceiling"), revenue_ltm)

        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session")) if not benchmark_prices.empty else (None, np.nan)
            bench_ret = _window_return(benchmark_prices, bench_anchor, window) if not benchmark_prices.empty else np.nan
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan

        if pd.isna(out["award_amount_pct_market_cap"]) and pd.isna(out["obligated_amount_pct_market_cap"]) and pd.isna(out["contract_ceiling_pct_market_cap"]):
            status.append("missing_materiality_ratio")
        out["sector_benchmark"] = _norm(row.get("sector_benchmark"))
        out["company_size_bucket"] = _size_bucket(market_cap)
        out["small_cap_flag"] = out["company_size_bucket"] == "small_cap"
        out["government_contract_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        enriched_rows.append(out)

    enriched = pd.DataFrame(enriched_rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def government_contract_readiness_summary(
    events: pd.DataFrame,
    *,
    source_documents: pd.DataFrame | None = None,
    min_train: int = 40,
    parser_errors: pd.DataFrame | None = None,
) -> dict[str, object]:
    if events.empty:
        return {"decision": "continue corpus buildout", "reason": "no parsed event rows", "parsed_event_rows": 0}

    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    not_dropped = ~review_status.isin({"rejected", "drop", "dropped"})
    usable = events[not_dropped].copy()
    reviewed = usable[usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower().isin({"reviewed", "curated", "approved"})]
    if reviewed.empty:
        reviewed = usable.iloc[0:0].copy()

    def bool_count(df: pd.DataFrame, col: str) -> int:
        return int(df.get(col, pd.Series(False, index=df.index)).map(_bool_value).sum())

    high_mapping = pd.to_numeric(events.get("recipient_mapping_confidence", pd.Series(dtype=float)), errors="coerce").fillna(0.0) >= 0.80
    ticker_counts = usable.get("ticker", pd.Series(dtype=str)).fillna("").astype(str).str.upper().replace("", np.nan).dropna().value_counts()
    top_ticker_share = float(ticker_counts.iloc[0] / len(usable)) if len(usable) and not ticker_counts.empty else 0.0
    concentration = ticker_counts.head(10).to_dict()
    source_rows = int(len(source_documents)) if source_documents is not None else np.nan

    rows_with_award_ratio = int(events.get("award_amount_pct_market_cap", pd.Series(index=events.index, dtype=float)).notna().sum())
    rows_with_obligated_ratio = int(events.get("obligated_amount_pct_market_cap", pd.Series(index=events.index, dtype=float)).notna().sum())
    rows_with_ceiling_ratio = int(events.get("contract_ceiling_pct_market_cap", pd.Series(index=events.index, dtype=float)).notna().sum())
    rows_with_runup = int(
        (
            events.get("pre_event_market_adjusted_return_20d", pd.Series(index=events.index, dtype=float)).notna()
            | events.get("pre_event_market_adjusted_return_60d", pd.Series(index=events.index, dtype=float)).notna()
        ).sum()
    )
    actual_funded = bool_count(usable, "actual_funded_award_flag")
    small_mid = int(usable.get("company_size_bucket", pd.Series([""] * len(usable), index=usable.index)).astype(str).str.lower().isin({"small_cap", "mid_cap"}).sum())

    metrics: dict[str, object] = {
        "source_documents_recovered": source_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "actual_funded_award_rows": actual_funded,
        "ceiling_only_rows": bool_count(usable, "ceiling_only_flag"),
        "modification_or_option_rows": int(bool_count(usable, "modification_flag") + bool_count(usable, "option_exercise_flag")),
        "rows_with_recipient_mapping_confidence_high": int(high_mapping.sum()),
        "rows_with_award_amount_pct_market_cap": rows_with_award_ratio,
        "rows_with_obligated_amount_pct_market_cap": rows_with_obligated_ratio,
        "rows_with_contract_ceiling_pct_market_cap": rows_with_ceiling_ratio,
        "rows_with_pre_event_market_adjusted_runup": rows_with_runup,
        "small_mid_cap_rows": small_mid,
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
        "ticker_concentration": concentration,
        "top_ticker_share": top_ticker_share,
    }

    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_rows"] >= 100,
        "actual_funded_award_events_60": metrics["actual_funded_award_rows"] >= 60,
        "amount_or_obligation_pct_market_cap_rows_40": (rows_with_award_ratio + rows_with_obligated_ratio) >= 40,
        "small_mid_cap_rows_30": small_mid >= 30,
        "mapping_high_confidence_rows_80": metrics["rows_with_recipient_mapping_confidence_high"] >= 80,
        "clear_event_timestamps": events.get("release_session", pd.Series(["unknown"] * len(events), index=events.index)).fillna("unknown").astype(str).str.lower().ne("unknown").sum() >= 80,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
        "pre_event_runup_rows_40": rows_with_runup >= 40,
    }
    if parser_errors is not None:
        ok_count = int((parser_errors.get("status", pd.Series(dtype=str)) == "ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_accuracy = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_accuracy"] = float(audit_accuracy)
        gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_accuracy >= 0.90)
    else:
        gates["parser_audit_pass"] = False
    gates = {gate: bool(passed) for gate, passed in gates.items()}

    blockers = [gate for gate, passed in gates.items() if not passed]
    metrics["gates"] = gates
    metrics["top_missing_fields_blocking_modeling"] = blockers[:]

    if all(gates.values()):
        decision = "model-ready"
        reason = "all non-modeling readiness gates pass"
    elif not gates.get("parser_audit_pass", False):
        decision = "parser not trusted"
        reason = "parser audit is missing or failing"
    elif not gates.get("clear_event_timestamps", False):
        decision = "timestamp/public-awareness insufficient"
        reason = "too few rows have clear event timestamps or public-awareness evidence"
    elif metrics["rows_with_recipient_mapping_confidence_high"] < max(20, int(0.75 * len(events))):
        decision = "mapping insufficient"
        reason = "too few rows have high-confidence recipient-to-ticker mapping"
    elif (rows_with_award_ratio + rows_with_obligated_ratio) < 40 or rows_with_runup < 40:
        decision = "context insufficient"
        reason = "market-cap materiality or pre-event run-up context is under-covered"
    else:
        decision = "continue corpus buildout"
        reason = "reviewed usable event counts are below modeling gates"
    metrics["decision"] = decision
    metrics["reason"] = reason
    return metrics


def write_government_contract_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    source_documents_path: str | Path | None = None,
    min_train: int = 40,
    parser_errors_path: str | Path | None = None,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    source_documents = pd.read_csv(source_documents_path) if source_documents_path else None
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    summary = government_contract_readiness_summary(events, source_documents=source_documents, min_train=min_train, parser_errors=parser_errors)
    out = ensure_parent(out_path)
    lines = [
        "# Government Contract Awards Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## One-Page Verdict",
        "",
        f"- verdict: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Summary Counts",
        "",
    ]
    for key, value in summary.items():
        if key in {"gates", "top_missing_fields_blocking_modeling", "ticker_concentration", "decision", "reason"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields / Gates Blocking Modeling", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Ticker Concentration", ""])
    for ticker, count in (summary.get("ticker_concentration", {}) or {}).items():
        lines.append(f"- {ticker}: {count}")
    lines.extend(
        [
            "",
            "## Pre-Registered Candidate Hypotheses",
            "",
            "1. small/mid-cap company AND actual_funded_award_flag = true AND obligated_amount_pct_market_cap >= 5% -> expected positive abnormal return.",
            "2. contract_ceiling_only_flag = true -> expected weaker/noisier reaction than actual funded awards.",
            "3. new_work_flag = true AND award_amount_pct_market_cap >= 5% -> expected stronger positive reaction than modification/option-extension awards.",
            "4. large prime contractor AND award_amount_pct_market_cap < 1% -> expected no meaningful abnormal return.",
            "5. positive pre-event run-up before award announcement -> expected weaker reaction or possible sell-the-news if anticipated.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
