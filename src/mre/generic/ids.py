from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any


def json_friendly(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Real) and not math.isfinite(float(value)):
        return None
    if is_dataclass(value):
        return json_friendly(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(k): json_friendly(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_friendly(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return json_friendly(asdict(value))
    if isinstance(value, Mapping):
        return json_friendly(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to dict")


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps([json_friendly(part) for part in parts], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(prefix).strip()) or "id"
    return f"{safe_prefix}_{digest}"


def validate_score(value: float, *, name: str = "score") -> float:
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
    return score
