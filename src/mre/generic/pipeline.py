from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..provenance import build_run_manifest, write_run_manifest
from .compatibility_eval import attach_readiness, summarize_compatibility
from .ids import json_friendly
from .plugin_runner import PluginRunReport, run_source_to_extraction
from .publishers import build_generic_digest, build_generic_static_site, export_generic_api
from .quality import build_generic_quality_report
from .review import make_generic_claim_review_queue
from .sources import SourceQuery
from .toy_plugins import ToyClaimExtractor, ToyEventDetector, ToyOfficialAdapter, ToyWeakAdapter


def default_generic_pipeline_config(
    *,
    out_dir: str = "artifacts/generic_toy",
    adapter: str = "toy_official",
    auto_accept_min_confidence: float | None = 0.8,
) -> dict[str, Any]:
    return {
        "source": {
            "adapter": adapter,
            "source_system": adapter,
            "query_id": "toy_query",
            "params": {"topic": "toy_event"},
        },
        "review": {
            "auto_accept_min_confidence": auto_accept_min_confidence,
            "require_evidence": True,
        },
        "outputs": {
            "out_dir": out_dir,
            "build_quality_report": True,
            "build_static_site": True,
            "build_api_export": True,
            "build_digest": True,
        },
        "provenance": {
            "write_manifest": True,
        },
    }


def write_generic_pipeline_template(out_path, **kwargs) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_generic_pipeline_config(**kwargs), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load_config(config_path_or_dict) -> dict[str, Any]:
    if isinstance(config_path_or_dict, dict):
        return dict(config_path_or_dict)
    return json.loads(Path(config_path_or_dict).read_text(encoding="utf-8"))


def _adapter(name: str):
    if name == "toy_weak":
        return ToyWeakAdapter()
    if name == "toy_official":
        return ToyOfficialAdapter()
    raise ValueError(f"Unsupported generic adapter: {name}")


def _records(rows: list) -> list[dict[str, Any]]:
    return [row.to_dict() if hasattr(row, "to_dict") else dict(row) for row in rows]


def _event_rows(report: PluginRunReport) -> list[dict[str, Any]]:
    rows = []
    for candidate in report.artifacts.get("event_candidates", []):
        payload = candidate.to_dict()
        payload["event_id"] = payload.get("event_candidate_id", "")
        payload["status"] = payload.get("status", "candidate")
        rows.append(payload)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def _dry_run_report(config: dict[str, Any]) -> dict[str, Any]:
    outputs = config.get("outputs", {})
    stages = [
        "source_to_extraction",
        "write_dataset",
        "review_queue",
        "quality_report",
        "api_export",
        "static_site",
        "digest",
        "run_manifest",
    ]
    return {
        "status": "dry_run",
        "out_dir": outputs.get("out_dir", ""),
        "stages": [{"name": name, "status": "planned"} for name in stages],
        "outputs": {},
    }


def run_generic_pipeline(config_path_or_dict, *, dry_run: bool = False) -> dict[str, Any]:
    config = _load_config(config_path_or_dict)
    if dry_run:
        return _dry_run_report(config)

    source = config.get("source", {})
    outputs = config.get("outputs", {})
    review_config = config.get("review", {})
    out_dir = Path(outputs.get("out_dir") or "artifacts/generic_toy")
    out_dir.mkdir(parents=True, exist_ok=True)

    adapter = _adapter(str(source.get("adapter") or "toy_official"))
    query = SourceQuery(
        query_id=str(source.get("query_id") or "toy_query"),
        source_system=str(source.get("source_system") or source.get("adapter") or "toy_official"),
        params=dict(source.get("params") or {}),
    )
    run_report = run_source_to_extraction(
        source_adapter=adapter,
        query=query,
        event_detector=ToyEventDetector(),
        claim_extractor=ToyClaimExtractor(),
    )

    compatibility_reports = [attach_readiness(report) for report in run_report.compatibility_reports]
    doc_rows = _records(run_report.artifacts.get("normalized_documents", []))
    event_rows = _event_rows(run_report)
    claim_rows = _records(run_report.artifacts.get("claims", []))
    evidence_rows = _records(run_report.artifacts.get("evidence_spans", []))
    for claim in claim_rows:
        claim.setdefault("source_system", claim.get("metadata", {}).get("source_system", query.source_system))

    paths: dict[str, str] = {
        "documents": _write_csv(out_dir / "generic_documents.csv", doc_rows),
        "events": _write_csv(out_dir / "generic_events.csv", event_rows),
        "claims": _write_csv(out_dir / "generic_claims.csv", claim_rows),
        "evidence_spans": _write_csv(out_dir / "generic_evidence_spans.csv", evidence_rows),
    }

    review_queue, review_diagnostics = make_generic_claim_review_queue(
        pd.DataFrame(claim_rows),
        pd.DataFrame(evidence_rows),
        out_path=out_dir / "generic_claim_review_queue.csv",
        auto_accept_min_confidence=review_config.get("auto_accept_min_confidence"),
        require_evidence=bool(review_config.get("require_evidence", True)),
    )
    paths["review_queue"] = str(out_dir / "generic_claim_review_queue.csv")

    quality = None
    if outputs.get("build_quality_report", True):
        quality = build_generic_quality_report(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            compatibility_reports=compatibility_reports,
            out_json=out_dir / "generic_quality_report.json",
            out_md=out_dir / "generic_quality_report.md",
        )
        paths["quality_json"] = str(out_dir / "generic_quality_report.json")
        paths["quality_md"] = str(out_dir / "generic_quality_report.md")

    if outputs.get("build_api_export", True):
        api_paths = export_generic_api(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            out_dir=out_dir / "api",
        )
        paths["api_dir"] = str(out_dir / "api")
        paths.update({f"api_{key}": value for key, value in api_paths.items()})

    if outputs.get("build_static_site", True):
        source_texts = {row["source_doc_id"]: row.get("text", "") for row in doc_rows if row.get("source_doc_id")}
        site_paths = build_generic_static_site(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            source_texts=source_texts,
            out_dir=out_dir / "site",
            title="Generic Evidence Event Dataset",
        )
        paths["site_dir"] = str(out_dir / "site")
        paths.update({f"site_{key}": value for key, value in site_paths.items()})

    if outputs.get("build_digest", True):
        digest_path = out_dir / "generic_digest.md"
        build_generic_digest(
            events=pd.DataFrame(event_rows),
            claims=pd.DataFrame(claim_rows),
            evidence_spans=pd.DataFrame(evidence_rows),
            review_queue=review_queue,
            out_path=digest_path,
        )
        paths["digest"] = str(digest_path)

    if config.get("provenance", {}).get("write_manifest", True):
        manifest = build_run_manifest(config, [], extra={"pipeline": "generic_toy"})
        manifest_path = write_run_manifest(out_dir / "run_manifest.json", manifest)
        paths["run_manifest"] = str(manifest_path)

    report = {
        "status": run_report.status,
        "out_dir": str(out_dir),
        "outputs": paths,
        "diagnostics": run_report.diagnostics,
        "review_diagnostics": review_diagnostics,
        "quality_warnings": [] if quality is None else quality.get("warnings", []),
        "compatibility": [summarize_compatibility(report) for report in compatibility_reports],
        "warnings": run_report.warnings,
    }
    report = json_friendly(report)
    (out_dir / "pipeline_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
