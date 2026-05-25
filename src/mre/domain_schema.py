from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_PROMOTION_GATES = {
    "min_reviewed_rows": 80,
    "min_model_eligible_rows": 60,
    "min_likely_oos_predictions": 30,
}

REQUIRED_SCHEMA_FIELDS = {"domain", "event_type", "default_subtype", "description"}


@dataclass(frozen=True)
class DomainSchema:
    domain: str
    event_type: str
    default_subtype: str
    description: str
    required_review_columns: list[str] = field(default_factory=list)
    domain_columns: list[str] = field(default_factory=list)
    categorical_features: list[str] = field(default_factory=list)
    numeric_features: list[str] = field(default_factory=list)
    promotion_gates: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PROMOTION_GATES))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _string_list(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError(f"{field_name} contains an empty column name")
        out.append(text)
    return out


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen and value not in dupes:
            dupes.append(value)
        seen.add(key)
    return dupes


def validate_domain_schema(schema: DomainSchema) -> DomainSchema:
    missing = [field_name for field_name in sorted(REQUIRED_SCHEMA_FIELDS) if not str(getattr(schema, field_name)).strip()]
    if missing:
        raise ValueError(f"Domain schema missing required fields: {missing}")

    for field_name in ["required_review_columns", "domain_columns", "categorical_features", "numeric_features"]:
        values = list(getattr(schema, field_name))
        dupes = _duplicate_values(values)
        if dupes:
            raise ValueError(f"Domain schema {schema.domain} has duplicate values in {field_name}: {dupes}")

    overlapping_columns = set(c.lower() for c in schema.required_review_columns) & set(c.lower() for c in schema.domain_columns)
    if overlapping_columns:
        raise ValueError(f"Domain schema {schema.domain} repeats required review columns in domain_columns: {sorted(overlapping_columns)}")

    missing_gates = [key for key in DEFAULT_PROMOTION_GATES if key not in schema.promotion_gates]
    if missing_gates:
        raise ValueError(f"Domain schema {schema.domain} missing promotion gates: {missing_gates}")
    for key, value in schema.promotion_gates.items():
        if int(value) < 0:
            raise ValueError(f"Domain schema {schema.domain} has negative promotion gate {key}: {value}")
    return schema


def domain_schema_from_mapping(data: Mapping[str, Any]) -> DomainSchema:
    missing = [field_name for field_name in sorted(REQUIRED_SCHEMA_FIELDS) if not str(data.get(field_name, "")).strip()]
    if missing:
        raise ValueError(f"Domain schema mapping missing required fields: {missing}")

    promotion_gates = dict(DEFAULT_PROMOTION_GATES)
    supplied_gates = data.get("promotion_gates") or {}
    if not isinstance(supplied_gates, Mapping):
        raise ValueError("promotion_gates must be an object")
    promotion_gates.update({str(key): int(value) for key, value in supplied_gates.items()})

    schema = DomainSchema(
        domain=str(data["domain"]).strip(),
        event_type=str(data["event_type"]).strip(),
        default_subtype=str(data["default_subtype"]).strip(),
        description=str(data["description"]).strip(),
        required_review_columns=_string_list(data.get("required_review_columns"), "required_review_columns"),
        domain_columns=_string_list(data.get("domain_columns"), "domain_columns"),
        categorical_features=_string_list(data.get("categorical_features"), "categorical_features"),
        numeric_features=_string_list(data.get("numeric_features"), "numeric_features"),
        promotion_gates=promotion_gates,
    )
    return validate_domain_schema(schema)


def load_domain_schema(path: str | Path) -> DomainSchema:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"Domain schema file must contain a JSON object: {p}")
    return domain_schema_from_mapping(data)


def load_domain_schemas(directory: str | Path) -> dict[str, DomainSchema]:
    schemas: dict[str, DomainSchema] = {}
    for path in sorted(Path(directory).glob("*.json")):
        schema = load_domain_schema(path)
        if schema.domain in schemas:
            raise ValueError(f"Duplicate domain schema for {schema.domain}")
        schemas[schema.domain] = schema
    return schemas
