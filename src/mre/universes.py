from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import ensure_parent

# Small, opinionated research universes. These are meant for bootstrapping a
# corpus, not for defining a survivorship-bias-free investment universe.
# Replace or version these lists when doing serious research.
DEFAULT_UNIVERSES: dict[str, dict[str, object]] = {
    "semiconductors": {
        "description": "Large U.S.-listed semiconductor, equipment, and chip-design names.",
        "benchmark": "SOXX",
        "tickers": [
            "NVDA",
            "AMD",
            "AVGO",
            "INTC",
            "QCOM",
            "TXN",
            "MU",
            "ADI",
            "MRVL",
            "AMAT",
            "LRCX",
            "KLAC",
            "MCHP",
            "ON",
            "NXPI",
            "MPWR",
            "TER",
            "ASML",
            "TSM",
        ],
    },
    "mega_cap_tech": {
        "description": "Mega-cap U.S. platform/AI/cloud technology names.",
        "benchmark": "XLK",
        "tickers": ["AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA", "AVGO", "ORCL"],
    },
    "cloud_software": {
        "description": "Large public cloud/software application and infrastructure names.",
        "benchmark": "IGV",
        "tickers": [
            "MSFT",
            "CRM",
            "NOW",
            "ADBE",
            "SNOW",
            "DDOG",
            "NET",
            "MDB",
            "CRWD",
            "ZS",
            "PANW",
            "TEAM",
            "WDAY",
            "SHOP",
        ],
    },
}


def normalize_universe_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def available_universes() -> pd.DataFrame:
    rows = []
    for name, spec in DEFAULT_UNIVERSES.items():
        rows.append(
            {
                "universe": name,
                "benchmark": spec["benchmark"],
                "n_tickers": len(spec["tickers"]),
                "description": spec["description"],
            }
        )
    return pd.DataFrame(rows).sort_values("universe").reset_index(drop=True)


def get_universe(name: str) -> dict[str, object]:
    key = normalize_universe_name(name)
    if key not in DEFAULT_UNIVERSES:
        options = ", ".join(sorted(DEFAULT_UNIVERSES))
        raise ValueError(f"Unknown universe {name!r}. Available universes: {options}")
    return DEFAULT_UNIVERSES[key]


def universe_tickers(name: str) -> list[str]:
    spec = get_universe(name)
    return [str(t).upper() for t in spec["tickers"]]


def universe_benchmark(name: str) -> str:
    return str(get_universe(name)["benchmark"]).upper()


def write_universe_csv(name: str, out_path: str | Path) -> pd.DataFrame:
    spec = get_universe(name)
    rows = [
        {
            "universe": normalize_universe_name(name),
            "ticker": str(t).upper(),
            "sector_benchmark": str(spec["benchmark"]).upper(),
            "notes": "Default bootstrap universe; replace/version this list for serious research.",
        }
        for t in spec["tickers"]
    ]
    df = pd.DataFrame(rows)
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def load_universe_csv(path: str | Path) -> tuple[list[str], str | None]:
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        raise ValueError("Universe CSV must include a ticker column")
    tickers = sorted(df["ticker"].dropna().astype(str).str.upper().unique().tolist())
    benchmark = None
    if "sector_benchmark" in df.columns:
        vals = df["sector_benchmark"].dropna().astype(str).str.upper().str.strip()
        vals = vals[vals != ""]
        if not vals.empty:
            benchmark = vals.mode().iloc[0]
    return tickers, benchmark
