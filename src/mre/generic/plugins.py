from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compatibility import CompatibilityReport
from .ids import to_dict


@dataclass(frozen=True)
class PluginManifest:
    plugin_name: str
    plugin_version: str
    plugin_kind: str
    supported_source_systems: list[str] = field(default_factory=list)
    supported_event_families: list[str] = field(default_factory=list)
    supported_claim_schemas: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    optional_capabilities: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)
    output_contracts: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


@dataclass(frozen=True)
class PluginCompatibility:
    manifest: PluginManifest
    compatibility: CompatibilityReport

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)
