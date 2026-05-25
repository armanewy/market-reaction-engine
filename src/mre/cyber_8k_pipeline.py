from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cyber_8k_api_export import export_cyber_8k_api
from .cyber_8k_dataset import build_cyber_8k_dataset
from .cyber_8k_digest import build_cyber_8k_digest
from .cyber_8k_site import build_cyber_8k_static_site
from .cyber_8k_sources import build_cyber_8k_source_documents
from .cyber_8k_quality import build_cyber_8k_quality_report
from .paths import ensure_dir, ensure_parent
from .provenance import build_run_manifest, write_run_manifest
from .sec import SecClient


def default_cyber_8k_config(
    *,
    source_documents_csv: str = "examples/cyber_8k_watch/source_documents.csv",
    out_dir: str = "artifacts/cyber_8k_watch",
    tickers: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    return {
        "source": {
            "mode": "existing_manifest",
            "source_documents_csv": source_documents_csv,
            "tickers": tickers or [],
            "start": start,
            "end": end,
            "limit_per_ticker": None,
        },
        "extraction": {
            "claims_csv": None,
            "evidence_spans_csv": None,
            "auto_accept_min_confidence": 0.9,
        },
        "review": {
            "require_evidence": True,
            "review_queue_csv": None,
        },
        "outputs": {
            "out_dir": out_dir,
            "build_static_site": True,
            "build_api_export": True,
            "build_digest": True,
            "build_quality_report": True,
        },
        "provenance": {
            "write_manifest": True,
        },
    }


def write_cyber_8k_pipeline_template(out_path, **kwargs) -> Path:
    path = ensure_parent(out_path)
    path.write_text(json.dumps(default_cyber_8k_config(**kwargs), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load_config(config_path: str | Path | dict) -> dict:
    if isinstance(config_path, dict):
        return config_path
    path = Path(config_path)
    return json.loads(path.read_text(encoding="utf-8"))


def _stage(name: str, status: str, **kwargs) -> dict:
    return {"name": name, "status": status, **kwargs}


def run_cyber_8k_pipeline(config_path, *, dry_run: bool = False) -> dict:
    config = _load_config(config_path)
    source = config.get("source", {})
    extraction = config.get("extraction", {})
    review = config.get("review", {})
    outputs = config.get("outputs", {})
    provenance = config.get("provenance", {})
    out_dir = Path(outputs.get("out_dir") or "artifacts/cyber_8k_watch")
    stages: list[dict[str, Any]] = []
    report: dict[str, Any] = {"status": "dry_run" if dry_run else "ok", "stages": stages, "outputs": {}}

    if dry_run:
        for name in [
            "source_documents",
            "parse_claims",
            "claim_review_queue",
            "build_dataset",
            "quality_report",
            "api_export",
            "static_site",
            "digest",
            "run_manifest",
        ]:
            stages.append(_stage(name, "planned"))
        return report

    ensure_dir(out_dir)
    mode = str(source.get("mode") or "existing_manifest")
    if mode == "existing_manifest":
        source_documents_csv = Path(source.get("source_documents_csv") or "")
        if not source_documents_csv:
            raise ValueError("source.source_documents_csv is required for existing_manifest mode")
        stages.append(_stage("source_documents", "used_existing", path=str(source_documents_csv)))
    elif mode == "sec_client":
        source_documents_csv = out_dir / "source_documents.csv"
        docs_dir = out_dir / "source_docs"
        client = SecClient(source.get("user_agent"), requests_per_second=float(source.get("requests_per_second", 5.0)))
        source_df, diagnostics = build_cyber_8k_source_documents(
            client,
            tickers=source.get("tickers") or [],
            out_manifest=source_documents_csv,
            docs_dir=docs_dir,
            start=source.get("start"),
            end=source.get("end"),
            limit_per_ticker=source.get("limit_per_ticker"),
            overwrite=bool(source.get("overwrite", False)),
        )
        stages.append(_stage("source_documents", "built", rows=int(len(source_df)), diagnostics=diagnostics.to_dict(), path=str(source_documents_csv)))
    else:
        raise ValueError(f"Unsupported Cyber 8-K source mode: {mode}")

    run_manifest_path = out_dir / "run_manifest.json" if provenance.get("write_manifest", True) else None
    summary = build_cyber_8k_dataset(
        source_documents_csv,
        claims_csv=extraction.get("claims_csv"),
        evidence_spans_csv=extraction.get("evidence_spans_csv"),
        review_queue_csv=review.get("review_queue_csv"),
        out_dir=out_dir,
        run_manifest_path=run_manifest_path,
        auto_accept_min_confidence=extraction.get("auto_accept_min_confidence"),
    )
    stages.extend(
        [
            _stage("parse_claims", "completed", claims=summary["claims"], evidence_spans=summary["evidence_spans"]),
            _stage("claim_review_queue", "completed", rows=summary["review_queue_rows"]),
            _stage("build_dataset", "completed", events=summary["events"]),
        ]
    )
    report["outputs"].update(summary["outputs"])

    if outputs.get("build_quality_report", True):
        quality_json = out_dir / "cyber_quality_report.json"
        quality_md = out_dir / "cyber_quality_report.md"
        quality = build_cyber_8k_quality_report(
            summary["outputs"]["events"],
            summary["outputs"]["claims"],
            summary["outputs"]["evidence_spans"],
            summary["outputs"]["review_queue"],
            out_json=quality_json,
            out_md=quality_md,
        )
        report["outputs"]["quality_report_json"] = str(quality_json)
        report["outputs"]["quality_report_md"] = str(quality_md)
        stages.append(_stage("quality_report", "completed", warnings=quality.get("warnings", [])))
    else:
        stages.append(_stage("quality_report", "skipped"))

    if outputs.get("build_api_export", True):
        api_paths = export_cyber_8k_api(summary["outputs"]["events"], summary["outputs"]["claims"], summary["outputs"]["evidence_spans"], out_dir / "api")
        report["outputs"]["api"] = api_paths
        stages.append(_stage("api_export", "completed", out_dir=str(out_dir / "api")))
    else:
        stages.append(_stage("api_export", "skipped"))

    if outputs.get("build_static_site", True):
        site_paths = build_cyber_8k_static_site(summary["outputs"]["events"], summary["outputs"]["claims"], summary["outputs"]["evidence_spans"], out_dir / "site")
        report["outputs"]["site"] = site_paths
        stages.append(_stage("static_site", "completed", out_dir=str(out_dir / "site")))
    else:
        stages.append(_stage("static_site", "skipped"))

    if outputs.get("build_digest", True):
        digest_path = out_dir / "cyber_8k_digest.md"
        build_cyber_8k_digest(summary["outputs"]["events"], summary["outputs"]["claims"], summary["outputs"]["evidence_spans"], out_path=digest_path)
        report["outputs"]["digest"] = str(digest_path)
        stages.append(_stage("digest", "completed", path=str(digest_path)))
    else:
        stages.append(_stage("digest", "skipped"))

    if run_manifest_path is not None:
        input_paths = [source_documents_csv]
        for optional in [extraction.get("claims_csv"), extraction.get("evidence_spans_csv"), review.get("review_queue_csv")]:
            if optional:
                input_paths.append(Path(optional))
        manifest = build_run_manifest(config, input_paths, extra={"pipeline": "cyber_8k_watch"})
        write_run_manifest(run_manifest_path, manifest)
        report["outputs"]["run_manifest"] = str(run_manifest_path)
        stages.append(_stage("run_manifest", "completed", path=str(run_manifest_path)))
    else:
        stages.append(_stage("run_manifest", "skipped"))

    report_path = out_dir / "pipeline_report.json"
    report["outputs"]["pipeline_report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return report
