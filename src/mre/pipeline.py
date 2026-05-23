from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .analyst_revisions import merge_analyst_revisions
from .backtest import make_peer_control_events, make_placebo_events, run_research_backtest
from .base_rates import base_rate_table
from .corpus import build_curated_corpus, corpus_quality_summary, validate_corpus_csv
from .earnings import build_alpha_vantage_earnings_corpus, build_earnings_corpus_from_sec, build_yfinance_earnings_corpus
from .event_study import run_event_study
from .events import event_tickers, load_events
from .expectations import enrich_expectations, merge_external_expectations
from .extraction import run_document_extraction
from .ingestion import build_sec_source_document_manifest, ingest_source_document_manifest
from .options import merge_options_implied_moves
from .paths import ensure_dir, ensure_parent
from .prices import fetch_yfinance_prices
from .release_times import merge_release_times
from .reports import event_study_report
from .review import make_review_queue
from .sec import SecClient
from .sectors import get_preset, parse_ticker_list

PIPELINE_SCHEMA_VERSION = 1


@dataclass
class PipelineStep:
    name: str
    status: str = "pending"
    message: str = ""
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineState:
    config_path: str
    run_id: str
    run_dir: str
    dry_run: bool = False
    steps: list[PipelineStep] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)

    def add(self, step: PipelineStep) -> PipelineStep:
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _diagnostics_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {"value": str(obj)}


def _now_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "unknown"


def default_pipeline_config(
    *,
    run_id: str = "semis_earnings_research_v1",
    domain: str = "earnings_guidance",
    preset: str = "semiconductors",
    tickers: Iterable[str] | None = None,
    source_mode: str = "yfinance_earnings",
) -> dict[str, Any]:
    ticker_list = [str(t).upper() for t in (tickers or [])]
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "run_id": run_id,
        "root": ".",
        "domain": domain,
        "corpus_name": run_id,
        "preset": preset,
        "tickers": ticker_list,
        "start": "2020-01-01",
        "end": "2025-01-01",
        "benchmark": "SPY",
        "sector_benchmark": "",
        "source": {
            "mode": source_mode,
            "events_csv": "",
            "ingestion_csv": "",
            "source_documents_csv": "",
            "forms": "8-K",
            "item_filter": "2.02",
            "limit_per_ticker": 80,
            "requests_per_second": 5.0,
            "release_session": "unknown",
            "stop_after_review_queue": False,
            "auto_accept_review_threshold": None,
        },
        "expectations": {
            "external_expectations_csv": "",
            "release_times_csv": "",
            "options_csv": "",
            "analyst_revisions_csv": "",
            "analyst_revision_windows": "7,30",
            "analyst_revision_metrics": "eps,revenue,gross_margin,forward_revenue",
            "fill_labels_from_expectations": True,
        },
        "corpus": {
            "require_reviewed": False,
            "min_materiality": 0.0,
            "validate_only": False,
        },
        "prices": {
            "provider": "yfinance",
            "prices_dir": "",
            "start": "2019-01-01",
            "end": "2025-01-15",
        },
        "event_study": {
            "horizons": [1, 3, 10],
            "estimation_window": 120,
            "estimation_gap": 5,
            "min_estimation_observations": 60,
        },
        "controls": {
            "make_placebo": True,
            "placebo_n_per_event": 1,
            "placebo_mode": "random",
            "make_peer_controls": True,
            "peer_map_csv": "",
            "universe_csv": "",
        },
        "backtest": {
            "enabled": True,
            "horizon": 1,
            "min_train": 40,
            "purge_days": 3,
            "probability_threshold": 0.60,
            "allow_short": True,
            "cost_bps": 5.0,
            "slippage_bps": 5.0,
            "calibration_bins": 10,
            "null_iterations": 500,
            "seed": 42,
        },
        "gates": {
            "min_predictions": 30,
            "min_trades": 5,
            "max_calibration_ece": 0.20,
            "max_null_p_value": 0.10,
            "require_positive_net_return": True,
            "control_max_relative_net_return": 0.75,
        },
    }


def write_pipeline_template(out_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    cfg = default_pipeline_config(**kwargs)
    p = ensure_parent(out_path)
    p.write_text(json.dumps(cfg, indent=2))
    return cfg


def load_pipeline_config(config_path: str | Path) -> dict[str, Any]:
    p = Path(config_path)
    cfg = json.loads(p.read_text())
    if int(cfg.get("schema_version", 1)) != PIPELINE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported pipeline schema_version={cfg.get('schema_version')}; expected {PIPELINE_SCHEMA_VERSION}")
    return cfg


def _as_path(value: object) -> Path | None:
    text = "" if value is None else str(value).strip()
    return Path(text) if text else None


def _csv_has_rows(path: str | Path | None) -> bool:
    if not path:
        return False
    p = Path(path)
    if not p.exists():
        return False
    try:
        return len(pd.read_csv(p)) > 0
    except Exception:
        return False


def _resolve_universe(cfg: dict[str, Any]) -> tuple[list[str], str, str]:
    tickers = set(parse_ticker_list(cfg.get("tickers", []) or []))
    benchmark = str(cfg.get("benchmark") or "SPY").upper().strip()
    sector_benchmark = str(cfg.get("sector_benchmark") or "").upper().strip()
    preset_name = cfg.get("preset")
    if preset_name:
        preset = get_preset(str(preset_name))
        tickers.update(preset.tickers)
        if not benchmark:
            benchmark = preset.benchmark
        if not sector_benchmark:
            sector_benchmark = preset.sector_benchmark
    if not tickers:
        raise ValueError("Pipeline config needs tickers or a preset.")
    return sorted(tickers), benchmark or "SPY", sector_benchmark


def _run_paths(cfg: dict[str, Any]) -> dict[str, Path]:
    root = Path(cfg.get("root") or ".")
    run_id = str(cfg.get("run_id") or "research_run")
    run_dir = Path(cfg.get("run_dir") or root / "runs" / run_id)
    return {
        "root": root,
        "run_dir": run_dir,
        "data_dir": run_dir / "data",
        "events_dir": run_dir / "data" / "events",
        "docs_dir": run_dir / "data" / "source_docs",
        "prices_dir": run_dir / "data" / "prices",
        "artifacts_dir": run_dir / "artifacts",
        "controls_dir": run_dir / "artifacts" / "controls",
        "backtest_dir": run_dir / "artifacts" / "backtest",
    }


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    ensure_parent(path).write_text(json.dumps(payload, indent=2, default=str))


def _safe_run(step: PipelineStep, fn, *, dry_run: bool = False) -> Any:
    if dry_run:
        step.status = "dry_run"
        step.message = "Skipped because --dry-run was supplied."
        return None
    try:
        result = fn()
        if step.status == "pending":
            step.status = "ok"
        return result
    except Exception as exc:  # deliberate: pipeline report should show exact failing stage
        step.status = "failed"
        step.message = str(exc)
        raise


def _source_candidates(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState) -> tuple[Path, Path | None]:
    source = cfg.get("source", {}) or {}
    mode = str(source.get("mode") or "manual_events").lower().strip()
    benchmark = str(cfg.get("benchmark") or "SPY").upper().strip()
    sector_benchmark = str(cfg.get("sector_benchmark") or "").upper().strip()
    tickers: list[str] = []
    events_dir = paths["events_dir"]
    docs_dir = paths["docs_dir"]
    step = state.add(PipelineStep("source_candidates"))

    if mode in {"manual", "manual_events", "existing"}:
        events_csv = _as_path(source.get("events_csv"))
        if not events_csv:
            raise ValueError("source.mode=manual_events requires source.events_csv")
        step.outputs["events"] = str(events_csv)
        step.status = "ok"
        step.message = "Using supplied event CSV."
        state.artifacts["candidate_events"] = str(events_csv)
        return events_csv, None

    events_out = events_dir / "01_candidate_events.csv"
    facts_out: Path | None = None

    def run():
        nonlocal facts_out, tickers, benchmark, sector_benchmark
        if mode in {"yfinance_earnings", "alpha_vantage_earnings", "sec_earnings", "sec_docs", "sec_source_docs"}:
            tickers, benchmark, sector_benchmark = _resolve_universe(cfg)
        if mode == "yfinance_earnings":
            df, diag = build_yfinance_earnings_corpus(
                tickers=tickers,
                out_path=events_out,
                sector_benchmark=sector_benchmark,
                start=cfg.get("start"),
                end=cfg.get("end"),
                limit_per_ticker=source.get("limit_per_ticker"),
            )
            step.metrics.update(_diagnostics_dict(diag))
            return df
        if mode == "alpha_vantage_earnings":
            df = build_alpha_vantage_earnings_corpus(
                tickers=tickers,
                out_path=events_out,
                api_key=source.get("api_key") or os.environ.get("ALPHA_VANTAGE_API_KEY"),
                sector_benchmark=sector_benchmark,
                start=cfg.get("start"),
                end=cfg.get("end"),
                limit_per_ticker=source.get("limit_per_ticker"),
                release_session=source.get("release_session", "unknown"),
            )
            return df
        if mode == "sec_earnings":
            client = SecClient(user_agent=source.get("user_agent"), requests_per_second=float(source.get("requests_per_second", 5.0)))
            df = build_earnings_corpus_from_sec(
                client=client,
                tickers=tickers,
                out_path=events_out,
                start=cfg.get("start"),
                end=cfg.get("end"),
                sector_benchmark=sector_benchmark,
                limit_per_ticker=source.get("limit_per_ticker"),
            )
            return df
        if mode in {"sec_docs", "sec_source_docs"}:
            client = SecClient(user_agent=source.get("user_agent"), requests_per_second=float(source.get("requests_per_second", 5.0)))
            docs_manifest = events_dir / "01_source_documents.csv"
            forms = [v.strip().upper() for v in str(source.get("forms", "8-K")).split(",") if v.strip()]
            docs, docs_diag = build_sec_source_document_manifest(
                client,
                tickers=tickers,
                out_manifest=docs_manifest,
                docs_dir=docs_dir,
                forms=forms,
                start=cfg.get("start"),
                end=cfg.get("end"),
                item_filter=None if str(source.get("item_filter", "2.02")).lower() in {"", "none", "all"} else str(source.get("item_filter", "2.02")),
                limit_per_ticker=source.get("limit_per_ticker"),
                sector_benchmark=sector_benchmark,
                overwrite=bool(source.get("overwrite", False)),
            )
            facts_out = events_dir / "02_extracted_facts.csv"
            expectations_out = events_dir / "02_extracted_expectations.csv"
            extracted_events_out = events_dir / "02_extracted_events.csv"
            facts, expectations, events, extract_diag = run_document_extraction(
                docs_manifest,
                facts_out=facts_out,
                expectations_out=expectations_out,
                events_out=extracted_events_out,
            )
            # Merge extracted expectations back into extracted events where possible.
            if len(expectations):
                merge_external_expectations(extracted_events_out, expectations_out, events_out, fill_labels=True)
            else:
                pd.read_csv(extracted_events_out).to_csv(events_out, index=False)
            step.outputs.update({"source_documents": str(docs_manifest), "facts": str(facts_out), "extracted_expectations": str(expectations_out)})
            step.metrics.update({"source_doc_rows": int(len(docs)), "source_doc_diag": _diagnostics_dict(docs_diag), "extraction_diag": _diagnostics_dict(extract_diag)})
            return events
        if mode in {"local_ingestion", "ingestion"}:
            ingestion_csv = _as_path(source.get("ingestion_csv"))
            if not ingestion_csv:
                raise ValueError("source.mode=local_ingestion requires source.ingestion_csv")
            docs_manifest = events_dir / "01_source_documents.csv"
            docs, docs_diag = ingest_source_document_manifest(
                ingestion_csv,
                docs_manifest,
                docs_dir,
                user_agent=source.get("user_agent"),
                requests_per_second=float(source.get("requests_per_second", 2.0)),
                overwrite=bool(source.get("overwrite", False)),
            )
            facts_out = events_dir / "02_extracted_facts.csv"
            expectations_out = events_dir / "02_extracted_expectations.csv"
            extracted_events_out = events_dir / "02_extracted_events.csv"
            facts, expectations, events, extract_diag = run_document_extraction(
                docs_manifest,
                facts_out=facts_out,
                expectations_out=expectations_out,
                events_out=extracted_events_out,
            )
            if len(expectations):
                merge_external_expectations(extracted_events_out, expectations_out, events_out, fill_labels=True)
            else:
                pd.read_csv(extracted_events_out).to_csv(events_out, index=False)
            facts_out = facts_out
            step.outputs.update({"source_documents": str(docs_manifest), "facts": str(facts_out), "extracted_expectations": str(expectations_out)})
            step.metrics.update({"source_doc_rows": int(len(docs)), "source_doc_diag": _diagnostics_dict(docs_diag), "extraction_diag": _diagnostics_dict(extract_diag)})
            return events
        if mode == "source_documents":
            docs_manifest = _as_path(source.get("source_documents_csv"))
            if not docs_manifest:
                raise ValueError("source.mode=source_documents requires source.source_documents_csv")
            facts_out = events_dir / "02_extracted_facts.csv"
            expectations_out = events_dir / "02_extracted_expectations.csv"
            extracted_events_out = events_dir / "02_extracted_events.csv"
            facts, expectations, events, extract_diag = run_document_extraction(
                docs_manifest,
                facts_out=facts_out,
                expectations_out=expectations_out,
                events_out=extracted_events_out,
            )
            if len(expectations):
                merge_external_expectations(extracted_events_out, expectations_out, events_out, fill_labels=True)
            else:
                pd.read_csv(extracted_events_out).to_csv(events_out, index=False)
            step.outputs.update({"facts": str(facts_out), "extracted_expectations": str(expectations_out)})
            step.metrics.update({"extraction_diag": _diagnostics_dict(extract_diag)})
            return events
        raise ValueError(f"Unsupported source.mode={mode!r}")

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["events"] = str(events_out)
    state.artifacts["candidate_events"] = str(events_out)
    if facts_out:
        state.artifacts["extracted_facts"] = str(facts_out)
    return events_out, facts_out


def _review_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path, facts_path: Path | None) -> Path:
    source = cfg.get("source", {}) or {}
    review_out = paths["events_dir"] / "03_review_queue.csv"
    step = state.add(PipelineStep("review_queue"))

    def run():
        df, diag = make_review_queue(
            events_path,
            review_out,
            facts_path=facts_path,
            auto_accept_min_confidence=source.get("auto_accept_review_threshold"),
        )
        step.metrics.update(_diagnostics_dict(diag))
        return df

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["review_queue"] = str(review_out)
    state.artifacts["review_queue"] = str(review_out)
    if bool(source.get("stop_after_review_queue", False)):
        state.warnings.append("Pipeline stopped after review queue by config. Edit the review queue, then rerun with source.mode=manual_events and source.events_csv pointing to the reviewed queue.")
    return review_out


def _merge_expectation_sources(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path) -> Path:
    exp_cfg = cfg.get("expectations", {}) or {}
    current = events_path
    step = state.add(PipelineStep("merge_expectation_sources"))
    outputs = []

    def run():
        nonlocal current
        i = 0
        external = _as_path(exp_cfg.get("external_expectations_csv"))
        if external:
            i += 1
            out = paths["events_dir"] / f"04_{i:02d}_external_expectations.csv"
            merge_external_expectations(current, external, out, fill_labels=bool(exp_cfg.get("fill_labels_from_expectations", True)))
            current = out
            outputs.append(out)
        release_times = _as_path(exp_cfg.get("release_times_csv"))
        if release_times:
            i += 1
            out = paths["events_dir"] / f"04_{i:02d}_release_times.csv"
            merge_release_times(current, release_times, out)
            current = out
            outputs.append(out)
        options = _as_path(exp_cfg.get("options_csv"))
        if options:
            i += 1
            out = paths["events_dir"] / f"04_{i:02d}_options.csv"
            merge_options_implied_moves(current, options, out)
            current = out
            outputs.append(out)
        revisions = _as_path(exp_cfg.get("analyst_revisions_csv"))
        if revisions:
            i += 1
            out = paths["events_dir"] / f"04_{i:02d}_analyst_revisions.csv"
            metrics = tuple(v.strip() for v in str(exp_cfg.get("analyst_revision_metrics", "eps,revenue,gross_margin,forward_revenue")).split(",") if v.strip())
            windows = tuple(int(v.strip()) for v in str(exp_cfg.get("analyst_revision_windows", "7,30")).split(",") if v.strip())
            merge_analyst_revisions(current, revisions, out, windows=windows, metrics=metrics)
            current = out
            outputs.append(out)
        return current

    _safe_run(step, run, dry_run=state.dry_run)
    if not outputs:
        step.message = "No external expectation files supplied."
    step.outputs["events"] = str(current)
    for p in outputs:
        step.outputs[p.stem] = str(p)
    state.artifacts["events_after_expectation_merges"] = str(current)
    return current


def _corpus_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path) -> Path:
    corpus_cfg = cfg.get("corpus", {}) or {}
    out = paths["events_dir"] / "05_curated_corpus.csv"
    validation_out = paths["artifacts_dir"] / "corpus_validation.csv"
    step = state.add(PipelineStep("curated_corpus"))

    def run():
        if corpus_cfg.get("validate_only"):
            df, diag = validate_corpus_csv(events_path, validation_out, domain=cfg.get("domain"), min_materiality=float(corpus_cfg.get("min_materiality", 0.0)))
            df.to_csv(out, index=False)
        else:
            df, diag = build_curated_corpus(
                [events_path],
                out,
                domain=cfg.get("domain"),
                corpus_name=cfg.get("corpus_name") or cfg.get("run_id"),
                require_reviewed=bool(corpus_cfg.get("require_reviewed", False)),
                min_materiality=float(corpus_cfg.get("min_materiality", 0.0)),
            )
            validate_corpus_csv(out, validation_out, domain=cfg.get("domain"), min_materiality=float(corpus_cfg.get("min_materiality", 0.0)))
        step.metrics.update({"diagnostics": _diagnostics_dict(diag), "quality": corpus_quality_summary(df)})
        return df

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs.update({"corpus": str(out), "validation": str(validation_out)})
    state.artifacts["corpus"] = str(out)
    state.artifacts["corpus_validation"] = str(validation_out)
    return out


def _prices_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path) -> Path:
    price_cfg = cfg.get("prices", {}) or {}
    provider = str(price_cfg.get("provider", "yfinance")).lower().strip()
    existing = _as_path(price_cfg.get("prices_dir"))
    out_dir = existing if provider in {"existing", "local"} and existing else paths["prices_dir"]
    step = state.add(PipelineStep("prices"))

    def run():
        if provider in {"existing", "local"}:
            if not out_dir or not Path(out_dir).exists():
                raise ValueError("prices.provider=existing/local requires prices.prices_dir pointing to CSV price files")
            return []
        if provider != "yfinance":
            raise ValueError(f"Unsupported prices.provider={provider!r}")
        events = load_events(events_path)
        tickers = event_tickers(events, benchmark=str(cfg.get("benchmark") or "SPY"))
        written = fetch_yfinance_prices(tickers, price_cfg.get("start") or cfg.get("start"), price_cfg.get("end") or cfg.get("end"), out_dir)
        step.metrics["tickers"] = tickers
        step.metrics["files_written"] = len(written)
        return written

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["prices_dir"] = str(out_dir)
    state.artifacts["prices_dir"] = str(out_dir)
    return Path(out_dir)


def _enrich_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path, prices_dir: Path) -> Path:
    out = paths["events_dir"] / "06_enriched_events.csv"
    step = state.add(PipelineStep("price_expectation_enrichment"))

    def run():
        df = enrich_expectations(events_path, prices_dir, out, benchmark_ticker=str(cfg.get("benchmark") or "SPY"))
        status_col = "expectation_feature_status" if "expectation_feature_status" in df.columns else "price_expectation_status"
        if status_col in df.columns:
            step.metrics["status_counts"] = df[status_col].value_counts(dropna=False).to_dict()
        return df

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["events"] = str(out)
    state.artifacts["enriched_events"] = str(out)
    return out


def _event_study_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path, prices_dir: Path, *, label: str = "main") -> Path:
    study_cfg = cfg.get("event_study", {}) or {}
    out = paths["artifacts_dir"] / f"{label}_event_study.csv"
    step = state.add(PipelineStep(f"event_study_{label}"))

    def run():
        df, diag = run_event_study(
            events_path,
            prices_dir,
            benchmark_ticker=str(cfg.get("benchmark") or "SPY"),
            horizons=tuple(int(v) for v in study_cfg.get("horizons", [1, 3, 10])),
            estimation_window=int(study_cfg.get("estimation_window", 120)),
            estimation_gap=int(study_cfg.get("estimation_gap", 5)),
            min_estimation_observations=int(study_cfg.get("min_estimation_observations", 60)),
        )
        df.to_csv(ensure_parent(out), index=False)
        step.metrics.update(_diagnostics_dict(diag))
        return df

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["event_study"] = str(out)
    state.artifacts[f"{label}_event_study"] = str(out)
    return out


def _controls_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, events_path: Path, prices_dir: Path) -> dict[str, Path]:
    controls_cfg = cfg.get("controls", {}) or {}
    outputs: dict[str, Path] = {}
    if bool(controls_cfg.get("make_placebo", True)):
        step = state.add(PipelineStep("placebo_controls"))
        placebo_events = paths["controls_dir"] / "placebo_events.csv"

        def run_placebo():
            df, diag = make_placebo_events(
                events_path,
                prices_dir,
                placebo_events,
                n_per_event=int(controls_cfg.get("placebo_n_per_event", 1)),
                mode=str(controls_cfg.get("placebo_mode", "random")),
                seed=int((cfg.get("backtest", {}) or {}).get("seed", 42)),
            )
            step.metrics.update(_diagnostics_dict(diag))
            return df

        _safe_run(step, run_placebo, dry_run=state.dry_run)
        step.outputs["placebo_events"] = str(placebo_events)
        state.artifacts["placebo_events"] = str(placebo_events)
        outputs["placebo_events"] = placebo_events
        if _csv_has_rows(placebo_events):
            outputs["placebo_event_study"] = _event_study_stage(cfg, paths, state, placebo_events, prices_dir, label="placebo")
    if bool(controls_cfg.get("make_peer_controls", True)):
        step = state.add(PipelineStep("peer_controls"))
        peer_events = paths["controls_dir"] / "peer_events.csv"

        def run_peer():
            df, diag = make_peer_control_events(
                events_path,
                peer_events,
                peer_map=_as_path(controls_cfg.get("peer_map_csv")),
                universe=_as_path(controls_cfg.get("universe_csv")),
            )
            step.metrics.update(_diagnostics_dict(diag))
            return df

        try:
            _safe_run(step, run_peer, dry_run=state.dry_run)
            step.outputs["peer_events"] = str(peer_events)
            state.artifacts["peer_events"] = str(peer_events)
            outputs["peer_events"] = peer_events
            if _csv_has_rows(peer_events):
                outputs["peer_event_study"] = _event_study_stage(cfg, paths, state, peer_events, prices_dir, label="peer")
        except Exception as exc:
            step.status = "warning"
            step.message = f"Peer controls skipped: {exc}"
            state.warnings.append(step.message)
    return outputs


def _run_backtests(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, event_studies: dict[str, Path]) -> dict[str, Any]:
    bt = cfg.get("backtest", {}) or {}
    if not bool(bt.get("enabled", True)):
        state.warnings.append("Backtest disabled by config.")
        return {}
    reports: dict[str, Any] = {}
    for label, study_path in event_studies.items():
        step = state.add(PipelineStep(f"research_backtest_{label}"))
        out_dir = paths["backtest_dir"] / label

        def run_one(sp=study_path, od=out_dir):
            return run_research_backtest(
                sp,
                od,
                horizon=int(bt.get("horizon", 1)),
                min_train=int(bt.get("min_train", 40)),
                purge_days=bt.get("purge_days"),
                probability_threshold=float(bt.get("probability_threshold", 0.60)),
                allow_short=bool(bt.get("allow_short", False)),
                cost_bps=float(bt.get("cost_bps", 0.0)),
                slippage_bps=float(bt.get("slippage_bps", 0.0)),
                calibration_bins=int(bt.get("calibration_bins", 10)),
                null_iterations=int(bt.get("null_iterations", 500)),
                seed=int(bt.get("seed", 42)),
            )

        try:
            report = _safe_run(step, run_one, dry_run=state.dry_run)
            if report:
                reports[label] = report
                step.outputs.update({k: str(v) for k, v in report.get("artifacts", {}).items()})
                step.metrics.update({"n_predictions": report.get("walk_forward", {}).get("n_predictions"), "n_trades": report.get("strategy", {}).get("n_trades")})
        except Exception as exc:
            step.status = "warning"
            step.message = f"Backtest skipped/failed for {label}: {exc}"
            state.warnings.append(step.message)
    return reports


def _base_rates_stage(cfg: dict[str, Any], paths: dict[str, Path], state: PipelineState, event_study_path: Path) -> Path:
    out = paths["artifacts_dir"] / "base_rates.csv"
    step = state.add(PipelineStep("base_rates"))

    def run():
        df = base_rate_table(event_study_path, horizon=int((cfg.get("backtest", {}) or {}).get("horizon", 1)), out_path=out, min_count=1)
        step.metrics["rows"] = int(len(df))
        return df

    _safe_run(step, run, dry_run=state.dry_run)
    step.outputs["base_rates"] = str(out)
    state.artifacts["base_rates"] = str(out)
    return out


def _research_report_markdown(state: PipelineState, reports: dict[str, Any], out_path: str | Path) -> None:
    lines: list[str] = []
    lines.append(f"# Market Reaction Engine Research Run: {state.run_id}\n")
    lines.append(f"Package version: `{_now_version()}`\n")
    lines.append("## Decision\n")
    lines.append(f"`{state.decision.get('decision', 'unknown')}`\n")
    if state.decision.get("checks"):
        lines.append("| Check | Passed | Value | Threshold | Notes |")
        lines.append("|---|---:|---:|---:|---|")
        for check in state.decision["checks"]:
            lines.append(f"| {check.get('name')} | {check.get('passed')} | {check.get('value')} | {check.get('threshold')} | {check.get('notes','')} |")
        lines.append("")
    lines.append("## Steps\n")
    lines.append("| Step | Status | Message |")
    lines.append("|---|---|---|")
    for step in state.steps:
        lines.append(f"| {step.name} | {step.status} | {step.message.replace('|', '/')} |")
    lines.append("")
    lines.append("## Key artifacts\n")
    for k, v in sorted(state.artifacts.items()):
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")
    if reports:
        lines.append("## Backtest summaries\n")
        for label, report in reports.items():
            strat = report.get("strategy", {})
            null = report.get("null_shuffle", {})
            cal = report.get("calibration", {})
            lines.append(f"### {label}\n")
            lines.append(f"- Predictions: `{report.get('walk_forward', {}).get('n_predictions')}`")
            lines.append(f"- Trades: `{strat.get('n_trades')}`")
            lines.append(f"- Mean net event return: `{strat.get('mean_net_event_return')}`")
            lines.append(f"- Cumulative net return: `{strat.get('cumulative_net_return')}`")
            lines.append(f"- Null one-sided p-value: `{null.get('one_sided_p_value_actual_ge_null')}`")
            lines.append(f"- ECE: `{cal.get('expected_calibration_error')}`\n")
    if state.warnings:
        lines.append("## Warnings\n")
        for w in state.warnings:
            lines.append(f"- {w}")
    ensure_parent(out_path).write_text("\n".join(lines))


def evaluate_signal_gates(cfg: dict[str, Any], reports: dict[str, Any]) -> dict[str, Any]:
    gates = cfg.get("gates", {}) or {}
    real = reports.get("main") or {}
    strategy = real.get("strategy", {})
    calibration = real.get("calibration", {})
    null = real.get("null_shuffle", {})
    walk = real.get("walk_forward", {})
    checks = []

    def add(name: str, passed: bool, value: Any, threshold: Any, notes: str = ""):
        checks.append({"name": name, "passed": bool(passed), "value": value, "threshold": threshold, "notes": notes})

    n_predictions = walk.get("n_predictions", 0) or 0
    add("minimum_predictions", n_predictions >= int(gates.get("min_predictions", 30)), n_predictions, gates.get("min_predictions", 30))
    n_trades = strategy.get("n_trades", 0) or 0
    add("minimum_trades", n_trades >= int(gates.get("min_trades", 5)), n_trades, gates.get("min_trades", 5))
    ece = calibration.get("expected_calibration_error")
    add("calibration_ece", ece is not None and float(ece) <= float(gates.get("max_calibration_ece", 0.20)), ece, gates.get("max_calibration_ece", 0.20))
    pval = null.get("one_sided_p_value_actual_ge_null")
    add("null_shuffle_p_value", pval is not None and float(pval) <= float(gates.get("max_null_p_value", 0.10)), pval, gates.get("max_null_p_value", 0.10))
    mean_net = strategy.get("mean_net_event_return")
    if bool(gates.get("require_positive_net_return", True)):
        add("positive_mean_net_event_return", mean_net is not None and float(mean_net) > 0, mean_net, ">0")

    real_net = float(mean_net) if mean_net is not None else None
    control_limit = float(gates.get("control_max_relative_net_return", 0.75))
    for label in ["placebo", "peer"]:
        rep = reports.get(label)
        if not rep:
            continue
        c_net = rep.get("strategy", {}).get("mean_net_event_return")
        if real_net is None or c_net is None:
            add(f"{label}_control_not_stronger", False, c_net, f"< {control_limit} * real", "Missing real/control metric")
        else:
            add(f"{label}_control_not_stronger", float(c_net) < control_limit * real_net, c_net, f"< {control_limit} * {real_net}")

    if not real:
        decision = "no_backtest"
    elif all(c["passed"] for c in checks):
        decision = "promising_needs_fresh_data"
    elif any(c["name"].endswith("control_not_stronger") and not c["passed"] for c in checks):
        decision = "failed_control_test"
    elif n_predictions < int(gates.get("min_predictions", 30)):
        decision = "inconclusive_too_few_predictions"
    else:
        decision = "not_promising_yet"
    return {"decision": decision, "checks": checks}


def run_pipeline(config_path: str | Path, *, dry_run: bool = False, stages: Iterable[str] | None = None) -> dict[str, Any]:
    cfg = load_pipeline_config(config_path)
    paths = _run_paths(cfg)
    for p in [paths["run_dir"], paths["events_dir"], paths["docs_dir"], paths["prices_dir"], paths["artifacts_dir"], paths["controls_dir"], paths["backtest_dir"]]:
        ensure_dir(p)
    state = PipelineState(config_path=str(config_path), run_id=str(cfg.get("run_id")), run_dir=str(paths["run_dir"]), dry_run=bool(dry_run))
    requested = {str(s).strip() for s in (stages or []) if str(s).strip()}

    def wants(stage: str) -> bool:
        return not requested or stage in requested or "all" in requested

    events_path, facts_path = _source_candidates(cfg, paths, state)
    review_path = _review_stage(cfg, paths, state, events_path, facts_path)
    if bool((cfg.get("source", {}) or {}).get("stop_after_review_queue", False)):
        report_path = paths["run_dir"] / "pipeline_report.json"
        _write_json(report_path, state.to_dict())
        state.artifacts["pipeline_report"] = str(report_path)
        return state.to_dict()
    merged_path = _merge_expectation_sources(cfg, paths, state, review_path)
    corpus_path = _corpus_stage(cfg, paths, state, merged_path)
    prices_dir = _prices_stage(cfg, paths, state, corpus_path)
    enriched_path = _enrich_stage(cfg, paths, state, corpus_path, prices_dir)
    main_study = _event_study_stage(cfg, paths, state, enriched_path, prices_dir, label="main")
    _base_rates_stage(cfg, paths, state, main_study)
    report_md = paths["artifacts_dir"] / "event_study_report.md"
    try:
        event_study_report(main_study, report_md, horizon=int((cfg.get("backtest", {}) or {}).get("horizon", 1)))
        state.artifacts["event_study_report_md"] = str(report_md)
    except Exception as exc:
        state.warnings.append(f"Event study markdown report skipped: {exc}")
    controls = _controls_stage(cfg, paths, state, enriched_path, prices_dir)
    studies = {"main": main_study}
    if "placebo_event_study" in controls:
        studies["placebo"] = controls["placebo_event_study"]
    if "peer_event_study" in controls:
        studies["peer"] = controls["peer_event_study"]
    reports = _run_backtests(cfg, paths, state, studies)
    state.decision = evaluate_signal_gates(cfg, reports)
    state.artifacts["run_dir"] = str(paths["run_dir"])
    report_path = paths["run_dir"] / "pipeline_report.json"
    md_path = paths["run_dir"] / "research_report.md"
    _research_report_markdown(state, reports, md_path)
    state.artifacts["research_report_md"] = str(md_path)
    _write_json(report_path, state.to_dict())
    state.artifacts["pipeline_report"] = str(report_path)
    _write_json(report_path, state.to_dict())
    return state.to_dict()
