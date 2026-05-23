from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SectorPreset:
    name: str
    tickers: tuple[str, ...]
    sector_benchmark: str
    benchmark: str = "SPY"
    description: str = ""


SECTOR_PRESETS: dict[str, SectorPreset] = {
    "semiconductors": SectorPreset(
        name="semiconductors",
        tickers=("NVDA", "AMD", "AVGO", "INTC", "QCOM", "TXN", "MU", "ADI", "MRVL", "AMAT", "LRCX", "KLAC", "ON", "MCHP"),
        sector_benchmark="SMH",
        description="Large/liquid U.S.-listed semiconductor and semiconductor-equipment names; SMH as rough sector ETF.",
    ),
    "mega_cap_tech": SectorPreset(
        name="mega_cap_tech",
        tickers=("AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL"),
        sector_benchmark="QQQ",
        description="Mega-cap technology/platform names; QQQ as rough peer/sector proxy.",
    ),
    "software": SectorPreset(
        name="software",
        tickers=("MSFT", "ORCL", "CRM", "ADBE", "NOW", "SNOW", "DDOG", "MDB", "NET", "PLTR", "CRWD", "ZS"),
        sector_benchmark="IGV",
        description="Large/liquid software and cloud names; IGV as rough software ETF.",
    ),
    "biotech": SectorPreset(
        name="biotech",
        tickers=("AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "BMRN", "ILMN", "INCY", "ALNY"),
        sector_benchmark="XBI",
        description="Biotech/pharma-leaning issuers; XBI as rough sector ETF.",
    ),
}


# Friendly aliases used in the README and CLI examples. These duplicate a few
# presets intentionally so users can choose natural names.
SECTOR_PRESETS.update(
    {
        "semis": SECTOR_PRESETS["semiconductors"],
        "tech_platforms": SECTOR_PRESETS["mega_cap_tech"],
        "cloud_software": SECTOR_PRESETS["software"],
        "banks": SectorPreset(
            name="banks",
            tickers=("JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF"),
            sector_benchmark="KBE",
            description="Large/liquid U.S. banks and financial institutions; KBE as rough bank ETF.",
        ),
    }
)


def normalize_preset_name(name: str) -> str:
    return str(name).lower().strip().replace("-", "_").replace(" ", "_")


def get_preset(name: str) -> SectorPreset:
    key = normalize_preset_name(name)
    if key not in SECTOR_PRESETS:
        choices = ", ".join(sorted(SECTOR_PRESETS))
        raise ValueError(f"Unknown preset {name!r}. Choices: {choices}")
    return SECTOR_PRESETS[key]


def list_presets() -> list[dict]:
    return [asdict(SECTOR_PRESETS[k]) for k in sorted(SECTOR_PRESETS)]


def parse_ticker_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    out: list[str] = []
    if not values:
        return out
    for raw in values:
        for part in str(raw).replace(",", " ").split():
            if part.strip():
                out.append(part.strip().upper())
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    return deduped


def resolve_tickers(tickers: list[str] | tuple[str, ...] | None = None, preset: str | None = None) -> tuple[str, ...]:
    out: list[str] = []
    if preset:
        out.extend(get_preset(preset).tickers)
    out.extend(parse_ticker_list(list(tickers or [])))
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    return tuple(deduped)
