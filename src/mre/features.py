from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import pandas as pd


FeatureDtype = Literal["numeric", "categorical", "boolean"]
FeatureSource = Literal["source_doc", "price_pre_event", "vendor_expectation", "manual_review", "event_metadata", "derived"]
LeakageRisk = Literal["low", "medium", "high"]

FEATURE_DTYPES = {"numeric", "categorical", "boolean"}
FEATURE_SOURCES = {"source_doc", "price_pre_event", "vendor_expectation", "manual_review", "event_metadata", "derived"}
LEAKAGE_RISKS = {"low", "medium", "high"}


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    dtype: FeatureDtype
    source: FeatureSource
    asof_required: bool = True
    allowed_for_modeling: bool = True
    leakage_risk: LeakageRisk = "low"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("FeatureSpec.name must be non-empty")
        if self.dtype not in FEATURE_DTYPES:
            raise ValueError(f"Unsupported feature dtype: {self.dtype}")
        if self.source not in FEATURE_SOURCES:
            raise ValueError(f"Unsupported feature source: {self.source}")
        if self.leakage_risk not in LEAKAGE_RISKS:
            raise ValueError(f"Unsupported leakage risk: {self.leakage_risk}")


def specs_from_names(
    categorical_names: Sequence[str],
    numeric_names: Sequence[str],
    *,
    categorical_source: FeatureSource = "event_metadata",
    numeric_source: FeatureSource = "derived",
) -> list[FeatureSpec]:
    specs: list[FeatureSpec] = []
    seen: set[str] = set()
    for name in categorical_names:
        key = str(name).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        specs.append(FeatureSpec(name=key, dtype="categorical", source=categorical_source))
    for name in numeric_names:
        key = str(name).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        specs.append(FeatureSpec(name=key, dtype="numeric", source=numeric_source))
    return specs


def available_feature_specs(
    df: pd.DataFrame,
    specs: Sequence[FeatureSpec],
    *,
    modeling_only: bool = True,
    allow_high_leakage: bool = False,
) -> list[FeatureSpec]:
    available: list[FeatureSpec] = []
    for spec in specs:
        if spec.name not in df.columns:
            continue
        if modeling_only and not spec.allowed_for_modeling:
            continue
        if modeling_only and spec.leakage_risk == "high" and not allow_high_leakage:
            continue
        if spec.dtype in {"numeric", "boolean"} and not pd.to_numeric(df[spec.name], errors="coerce").notna().any():
            continue
        available.append(spec)
    return available


def split_feature_specs(specs: Sequence[FeatureSpec]) -> tuple[list[str], list[str]]:
    categorical: list[str] = []
    numeric: list[str] = []
    for spec in specs:
        if spec.dtype == "categorical":
            categorical.append(spec.name)
        elif spec.dtype in {"numeric", "boolean"}:
            numeric.append(spec.name)
        else:  # pragma: no cover - FeatureSpec validates dtype at construction.
            raise ValueError(f"Unsupported feature dtype: {spec.dtype}")
    return categorical, numeric
