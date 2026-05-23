from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyst_revisions import make_analyst_revisions_template, merge_analyst_revisions
from .backtest import (
    calibration_table,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    purged_walk_forward_direction_model,
    run_research_backtest,
    simulate_event_strategy,
)
from .base_rates import base_rate_table
from .corpus import build_curated_corpus, corpus_quality_summary, list_corpus_domains, make_domain_event_template, validate_corpus_csv
from .corpus_demo import generate_corpus_demo_data
from .demo import generate_demo_data
from .extraction import build_extraction_packets, run_document_extraction, validate_llm_facts_jsonl
from .extraction_demo import generate_extraction_demo_data
from .ingestion import build_sec_source_document_manifest, ingest_source_document_manifest, make_ingestion_template
from .source_ingestion_demo import generate_source_ingestion_demo_data
from .earnings import build_alpha_vantage_earnings_corpus, build_earnings_corpus_from_sec, build_yfinance_earnings_corpus, write_manual_earnings_template
from .earnings_demo import generate_earnings_demo_data
from .event_study import run_event_study
from .events import event_tickers, load_events, make_event_template
from .expectations import enrich_expectations, make_expectations_template, merge_external_expectations
from .modeling import find_analogs, predict_direction, train_direction_model, walk_forward_direction_model
from .options import make_options_template, merge_options_implied_moves
from .pipeline import run_pipeline, write_pipeline_template
from .pipeline_demo import generate_pipeline_demo
from .release_times import make_release_times_template, merge_release_times
from .paths import ensure_parent
from .prices import fetch_yfinance_prices
from .reports import event_study_report
from .review import make_review_queue
from .source_docs import make_source_docs_template
from .sec import SecClient, filings_to_event_template
from .sectors import get_preset, list_presets, parse_ticker_list


def comma_ints(value: str) -> tuple[int, ...]:
    return tuple(int(v.strip()) for v in value.split(",") if v.strip())


def resolve_tickers_and_sector(args: argparse.Namespace) -> tuple[list[str], str, str]:
    tickers: set[str] = set(parse_ticker_list(getattr(args, "tickers", []) or []))
    benchmark = (getattr(args, "benchmark", "") or "").upper().strip()
    sector_benchmark = (getattr(args, "sector_benchmark", "") or "").upper().strip()
    preset_name = getattr(args, "preset", None)
    if preset_name:
        preset = get_preset(preset_name)
        tickers.update(preset.tickers)
        if not benchmark:
            benchmark = preset.benchmark
        if not sector_benchmark:
            sector_benchmark = preset.sector_benchmark
    if not tickers:
        raise SystemExit("No tickers supplied. Use --preset or --tickers.")
    if not benchmark:
        benchmark = "SPY"
    return sorted(tickers), benchmark, sector_benchmark



def cmd_pipeline_template(args: argparse.Namespace) -> None:
    cfg = write_pipeline_template(
        args.out,
        run_id=args.run_id,
        domain=args.domain,
        preset=args.preset,
        tickers=args.tickers,
        source_mode=args.source_mode,
    )
    print(json.dumps({"out": str(args.out), "run_id": cfg["run_id"], "domain": cfg["domain"], "source_mode": cfg["source"]["mode"]}, indent=2))


def cmd_run_pipeline(args: argparse.Namespace) -> None:
    report = run_pipeline(args.config, dry_run=args.dry_run, stages=args.stages)
    print(json.dumps(report, indent=2, default=str))


def cmd_review_queue(args: argparse.Namespace) -> None:
    df, diag = make_review_queue(
        args.events,
        args.out,
        facts_path=args.facts,
        auto_accept_min_confidence=args.auto_accept_min_confidence,
        auto_accept_min_facts=args.auto_accept_min_facts,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out)}, indent=2, default=str))


def cmd_pipeline_demo(args: argparse.Namespace) -> None:
    paths = generate_pipeline_demo(Path(args.root), seed=args.seed)
    print("Pipeline automation demo complete.")
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))

def cmd_sector_presets(args: argparse.Namespace) -> None:
    print(json.dumps(list_presets(), indent=2))


def cmd_earnings_template(args: argparse.Namespace) -> None:
    tickers = []
    if args.preset or args.tickers:
        tickers, _, _ = resolve_tickers_and_sector(args)
    df = write_manual_earnings_template(args.out, tickers=tickers)
    print(f"Wrote manual earnings/guidance template with {len(df)} row(s): {args.out}")


def cmd_expectations_template(args: argparse.Namespace) -> None:
    df = make_expectations_template(args.events, args.out)
    print(f"Wrote expectation template with {len(df)} row(s): {args.out}")


def cmd_earnings_corpus(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    df = build_alpha_vantage_earnings_corpus(
        tickers=tickers,
        out_path=args.out,
        api_key=args.api_key,
        sector_benchmark=sector_benchmark,
        start=args.start,
        end=args.end,
        limit_per_ticker=args.limit_per_ticker,
        requests_per_minute=args.requests_per_minute,
        release_session=args.release_session,
    )
    print(
        json.dumps(
            {
                "provider": "alpha-vantage",
                "events_written": int(len(df)),
                "tickers": tickers,
                "benchmark": benchmark,
                "sector_benchmark": sector_benchmark,
                "out": str(args.out),
                "warning": "Alpha Vantage EPS history is useful for an MVP but is not a trading-grade point-in-time estimates feed; curate release timing and add revenue/guidance/options expectations.",
            },
            indent=2,
        )
    )


def cmd_yfinance_earnings_corpus(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    df, diag = build_yfinance_earnings_corpus(
        tickers=tickers,
        out_path=args.out,
        sector_benchmark=sector_benchmark,
        start=args.start,
        end=args.end,
        limit_per_ticker=args.limit_per_ticker,
        sleep_seconds=args.sleep_seconds,
    )
    print(
        json.dumps(
            {
                "provider": "yfinance",
                "events_written": int(len(df)),
                "tickers": tickers,
                "benchmark": benchmark,
                "sector_benchmark": sector_benchmark,
                "out": str(args.out),
                "diagnostics": diag.to_dict(),
                "warning": "yfinance earnings rows are bootstrap data for research plumbing; verify release timestamps and point-in-time estimates before serious use.",
            },
            indent=2,
            default=str,
        )
    )


def cmd_sec_earnings_corpus(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    df = build_earnings_corpus_from_sec(
        client=client,
        tickers=tickers,
        out_path=args.out,
        start=args.start,
        end=args.end,
        sector_benchmark=sector_benchmark,
        limit_per_ticker=args.limit_per_ticker,
        include_periodic=args.include_periodic,
        include_guidance_candidates=args.include_guidance_candidates,
    )
    print(
        json.dumps(
            {
                "provider": "sec-edgar",
                "events_written": int(len(df)),
                "tickers": tickers,
                "benchmark": benchmark,
                "sector_benchmark": sector_benchmark,
                "out": str(args.out),
                "warning": "SEC rows are primary-source event candidates. They do not include analyst consensus, revenue/guidance surprise, or options implied move unless merged later.",
            },
            indent=2,
        )
    )



def cmd_source_docs_template(args: argparse.Namespace) -> None:
    df = make_source_docs_template(args.out)
    print(f"Wrote source-document manifest template with {len(df)} row(s): {args.out}")


def cmd_ingestion_template(args: argparse.Namespace) -> None:
    df = make_ingestion_template(args.out)
    print(f"Wrote source-ingestion template with {len(df)} row(s): {args.out}")


def cmd_ingest_source_docs(args: argparse.Namespace) -> None:
    df, diag = ingest_source_document_manifest(
        args.input,
        args.out,
        args.docs_dir,
        user_agent=args.user_agent,
        requests_per_second=args.requests_per_second,
        overwrite=args.overwrite,
        include_inline_text=args.include_inline_text,
        min_text_chars=args.min_text_chars,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out), "docs_dir": str(args.docs_dir)}, indent=2, default=str))


def cmd_sec_source_docs(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    forms = [v.strip().upper() for v in args.forms.split(",") if v.strip()]
    df, diag = build_sec_source_document_manifest(
        client,
        tickers=tickers,
        out_manifest=args.out,
        docs_dir=args.docs_dir,
        forms=forms,
        start=args.start,
        end=args.end,
        item_filter=None if args.item_filter.lower() in {"", "none", "all"} else args.item_filter,
        limit_per_ticker=args.limit_per_ticker,
        include_primary=not args.no_primary,
        include_exhibits=not args.no_exhibits,
        exhibit_pattern=args.exhibit_pattern,
        sector_benchmark=sector_benchmark,
        overwrite=args.overwrite,
        min_text_chars=args.min_text_chars,
    )
    print(json.dumps({
        "provider": "sec-edgar",
        "tickers": tickers,
        "benchmark": benchmark,
        "sector_benchmark": sector_benchmark,
        "rows": int(len(df)),
        "diagnostics": diag.to_dict(),
        "out": str(args.out),
        "docs_dir": str(args.docs_dir),
        "warning": "SEC source documents are primary-source downloads, but extraction labels should still be reviewed before modeling.",
    }, indent=2, default=str))



def cmd_extract_facts(args: argparse.Namespace) -> None:
    facts, expectations, events, diag = run_document_extraction(
        args.documents,
        facts_out=args.facts_out,
        expectations_out=args.expectations_out,
        events_out=args.events_out,
    )
    print(json.dumps({
        "documents": args.documents,
        "facts_rows": int(len(facts)),
        "expectation_rows": int(len(expectations)),
        "event_rows": int(len(events)),
        "facts_out": str(args.facts_out) if args.facts_out else "",
        "expectations_out": str(args.expectations_out) if args.expectations_out else "",
        "events_out": str(args.events_out) if args.events_out else "",
        "diagnostics": diag.to_dict(),
    }, indent=2, default=str))


def cmd_extraction_packets(args: argparse.Namespace) -> None:
    rows = build_extraction_packets(args.documents, args.out, max_chars=args.max_chars)
    print(json.dumps({"packets": int(rows), "out": str(args.out)}, indent=2))


def cmd_validate_llm_facts(args: argparse.Namespace) -> None:
    df = validate_llm_facts_jsonl(
        args.documents,
        args.llm_jsonl,
        args.out,
        require_evidence_in_text=not args.allow_missing_evidence,
    )
    print(json.dumps({"fact_rows": int(len(df)), "out": str(args.out)}, indent=2))

def cmd_enrich_expectations(args: argparse.Namespace) -> None:
    df = enrich_expectations(
        events_path=args.events,
        prices_dir=args.prices_dir,
        out_path=args.out,
        benchmark_ticker=args.benchmark,
    )
    status_col = "expectation_feature_status" if "expectation_feature_status" in df.columns else "price_expectation_status"
    counts = df[status_col].value_counts(dropna=False).to_dict() if status_col in df.columns else {}
    print(json.dumps({"rows": int(len(df)), "status_counts": counts, "out": str(args.out)}, indent=2, default=str))


def cmd_merge_expectations(args: argparse.Namespace) -> None:
    df = merge_external_expectations(args.events, args.expectations, args.out, fill_labels=args.fill_labels)
    print(json.dumps({"rows": int(len(df)), "out": str(args.out)}, indent=2))


def cmd_release_times_template(args: argparse.Namespace) -> None:
    df = make_release_times_template(args.events, args.out)
    print(f"Wrote release-time template with {len(df)} row(s): {args.out}")


def cmd_merge_release_times(args: argparse.Namespace) -> None:
    df = merge_release_times(args.events, args.release_times, args.out, key=args.key, require_all_events=args.require_all_events)
    counts = df["release_time_status"].value_counts(dropna=False).to_dict() if "release_time_status" in df.columns else {}
    print(json.dumps({"rows": int(len(df)), "status_counts": counts, "out": str(args.out)}, indent=2, default=str))


def cmd_options_template(args: argparse.Namespace) -> None:
    df = make_options_template(args.events, args.out)
    print(f"Wrote options/implied-move template with {len(df)} row(s): {args.out}")


def cmd_merge_options(args: argparse.Namespace) -> None:
    df, diag = merge_options_implied_moves(
        args.events,
        args.options,
        args.out,
        max_quote_age_days=None if args.max_quote_age_days < 0 else args.max_quote_age_days,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out)}, indent=2, default=str))


def cmd_analyst_revisions_template(args: argparse.Namespace) -> None:
    df = make_analyst_revisions_template(args.events, args.out)
    print(f"Wrote analyst-revisions template with {len(df)} row(s): {args.out}")


def cmd_merge_analyst_revisions(args: argparse.Namespace) -> None:
    metrics = tuple(m.strip() for m in args.metrics.split(",") if m.strip())
    df, diag = merge_analyst_revisions(
        args.events,
        args.revisions,
        args.out,
        windows=comma_ints(args.windows),
        metrics=metrics,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out)}, indent=2, default=str))


def cmd_make_template(args: argparse.Namespace) -> None:
    make_event_template(args.out)
    print(f"Wrote event template: {args.out}")


def cmd_init_demo(args: argparse.Namespace) -> None:
    paths = generate_demo_data(args.out, seed=args.seed)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


def cmd_fetch_prices(args: argparse.Namespace) -> None:
    tickers = parse_ticker_list(args.tickers)
    if args.events:
        events = load_events(args.events)
        tickers = sorted(set(tickers) | set(event_tickers(events, benchmark=args.benchmark)))
    if not tickers:
        raise SystemExit("No tickers supplied. Use --tickers or --events.")
    paths = fetch_yfinance_prices(tickers, args.start, args.end, args.out_dir)
    print("Wrote price files:")
    for p in paths:
        print(f"- {p}")


def cmd_run_event_study(args: argparse.Namespace) -> None:
    df, diag = run_event_study(
        events_path=args.events,
        prices_dir=args.prices_dir,
        benchmark_ticker=args.benchmark,
        horizons=comma_ints(args.horizons),
        estimation_window=args.estimation_window,
        estimation_gap=args.estimation_gap,
        min_estimation_observations=args.min_estimation_observations,
    )
    out = ensure_parent(args.out)
    df.to_csv(out, index=False)
    print(f"Wrote event-study results: {out}")
    print(
        json.dumps(
            {
                "events_total": diag.events_total,
                "events_ok": diag.events_ok,
                "events_skipped": diag.events_skipped,
                "skipped_reasons": diag.skipped_reasons,
            },
            indent=2,
        )
    )


def cmd_train(args: argparse.Namespace) -> None:
    report = train_direction_model(
        event_study_path=args.event_study,
        horizon=args.horizon,
        out_model=args.out_model,
        out_report=args.out_report,
        test_size=args.test_size,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_walk_forward(args: argparse.Namespace) -> None:
    report = walk_forward_direction_model(
        event_study_path=args.event_study,
        horizon=args.horizon,
        min_train=args.min_train,
        out_predictions=args.out_predictions,
        out_report=args.out_report,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_predict(args: argparse.Namespace) -> None:
    df = predict_direction(args.model, args.event_study, out_path=args.out)
    print(f"Predicted {len(df)} rows")
    if args.out:
        print(f"Wrote predictions: {args.out}")
    else:
        cols = [c for c in ["event_id", "ticker", "event_type", "predicted_positive_probability", "predicted_direction"] if c in df.columns]
        print(df[cols].head(args.head).to_string(index=False))


def cmd_analogs(args: argparse.Namespace) -> None:
    out = find_analogs(
        event_study_path=args.event_study,
        event_id=args.event_id,
        k=args.k,
        horizon=args.horizon,
        out_path=args.out,
    )
    if args.out:
        print(f"Wrote analogs: {args.out}")
    print(out.head(args.k).to_string(index=False))


def cmd_report(args: argparse.Namespace) -> None:
    event_study_report(args.event_study, args.out, horizon=args.horizon)
    print(f"Wrote report: {args.out}")


def cmd_sec_template(args: argparse.Namespace) -> None:
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    forms = [f.strip().upper() for f in args.forms.split(",") if f.strip()]
    filings = client.recent_filings(args.ticker, forms=forms)
    if args.start:
        filings = filings[pd_to_datetime(filings["filingDate"]) >= pd_to_datetime_scalar(args.start)]
    if args.end:
        filings = filings[pd_to_datetime(filings["filingDate"]) <= pd_to_datetime_scalar(args.end)]
    events = filings_to_event_template(filings, args.out, limit=args.limit)
    print(f"Wrote {len(events)} SEC-derived event template rows: {args.out}")
    print("Curate materiality/expectedness/surprise_direction before using these as modeling labels.")


def pd_to_datetime(value):
    import pandas as pd

    return pd.to_datetime(value, errors="coerce")


def pd_to_datetime_scalar(value):
    import pandas as pd

    return pd.Timestamp(pd.to_datetime(value, errors="coerce"))


def cmd_demo(args: argparse.Namespace) -> None:
    root = Path(args.root)
    data_paths = generate_demo_data(root / "data" / "demo", seed=args.seed)
    event_study_out = root / "artifacts" / "demo_event_study.csv"
    model_out = root / "artifacts" / "demo_reaction_direction.joblib"
    model_report = root / "artifacts" / "demo_model_report.json"
    report_out = root / "artifacts" / "demo_report.md"
    analogs_out = root / "artifacts" / "demo_analogs.csv"

    df, diag = run_event_study(
        data_paths["events"],
        data_paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1, 3, 10),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    ensure_parent(event_study_out)
    df.to_csv(event_study_out, index=False)
    train_direction_model(event_study_out, horizon=1, out_model=model_out, out_report=model_report)
    event_study_report(event_study_out, report_out, horizon=1)
    ok = df[df["event_status"] == "ok"]
    if not ok.empty:
        find_analogs(event_study_out, ok.iloc[0]["event_id"], k=5, horizon=1, out_path=analogs_out)
    print("Demo complete.")
    print(json.dumps(
        {
            "events": str(data_paths["events"]),
            "prices_dir": str(data_paths["prices_dir"]),
            "event_study": str(event_study_out),
            "model": str(model_out),
            "model_report": str(model_report),
            "report": str(report_out),
            "analogs": str(analogs_out),
            "diagnostics": {
                "events_total": diag.events_total,
                "events_ok": diag.events_ok,
                "events_skipped": diag.events_skipped,
                "skipped_reasons": diag.skipped_reasons,
            },
        },
        indent=2,
    ))


def cmd_earnings_demo(args: argparse.Namespace) -> None:
    root = Path(args.root)
    data_paths = generate_earnings_demo_data(root / "data" / "earnings_demo", seed=args.seed)
    event_study_out = root / "artifacts" / "earnings_demo_event_study.csv"
    model_out = root / "artifacts" / "earnings_demo_reaction_direction.joblib"
    model_report = root / "artifacts" / "earnings_demo_model_report.json"
    report_out = root / "artifacts" / "earnings_demo_report.md"
    analogs_out = root / "artifacts" / "earnings_demo_analogs.csv"
    walk_preds = root / "artifacts" / "earnings_demo_walk_forward_predictions.csv"
    walk_report = root / "artifacts" / "earnings_demo_walk_forward_report.json"

    df, diag = run_event_study(
        data_paths["events_enriched"],
        data_paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1, 3, 10),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    ensure_parent(event_study_out)
    df.to_csv(event_study_out, index=False)
    train_direction_model(event_study_out, horizon=1, out_model=model_out, out_report=model_report)
    # Walk-forward may fail on too few events; the synthetic set is large enough.
    walk_forward_direction_model(event_study_out, horizon=1, min_train=20, out_predictions=walk_preds, out_report=walk_report)
    event_study_report(event_study_out, report_out, horizon=1)
    ok = df[df["event_status"] == "ok"]
    if not ok.empty:
        find_analogs(event_study_out, ok.iloc[-1]["event_id"], k=8, horizon=1, out_path=analogs_out)
    print("Earnings demo complete.")
    print(json.dumps(
        {
            "events_raw": str(data_paths["events_raw"]),
            "expectations": str(data_paths["expectations"]),
            "release_times": str(data_paths.get("release_times", "")),
            "option_snapshots": str(data_paths.get("option_snapshots", "")),
            "analyst_revisions": str(data_paths.get("analyst_revisions", "")),
            "events_enriched": str(data_paths["events_enriched"]),
            "prices_dir": str(data_paths["prices_dir"]),
            "event_study": str(event_study_out),
            "model": str(model_out),
            "model_report": str(model_report),
            "walk_forward_predictions": str(walk_preds),
            "walk_forward_report": str(walk_report),
            "report": str(report_out),
            "analogs": str(analogs_out),
            "diagnostics": {
                "events_total": diag.events_total,
                "events_ok": diag.events_ok,
                "events_skipped": diag.events_skipped,
                "skipped_reasons": diag.skipped_reasons,
            },
        },
        indent=2,
    ))



def cmd_extraction_demo(args: argparse.Namespace) -> None:
    paths = generate_extraction_demo_data(Path(args.root) / "data" / "extraction_demo")
    print("Extraction demo complete.")
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))

def cmd_source_ingestion_demo(args: argparse.Namespace) -> None:
    paths = generate_source_ingestion_demo_data(Path(args.root) / "data" / "source_ingestion_demo")
    print("Source ingestion demo complete.")
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


def cmd_corpus_domains(args: argparse.Namespace) -> None:
    df = list_corpus_domains()
    print(df.to_string(index=False))


def cmd_domain_template(args: argparse.Namespace) -> None:
    df = make_domain_event_template(
        args.domain,
        args.out,
        tickers=args.tickers,
        corpus_name=args.corpus_name,
        rows_per_ticker=args.rows_per_ticker,
    )
    print(json.dumps({"rows": int(len(df)), "domain": args.domain, "out": str(args.out)}, indent=2))


def cmd_build_corpus(args: argparse.Namespace) -> None:
    df, diag = build_curated_corpus(
        args.inputs,
        args.out,
        domain=args.domain,
        corpus_name=args.corpus_name,
        require_reviewed=args.require_reviewed,
        min_materiality=args.min_materiality,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "quality": corpus_quality_summary(df), "out": str(args.out)}, indent=2, default=str))


def cmd_validate_corpus(args: argparse.Namespace) -> None:
    df, diag = validate_corpus_csv(args.events, args.out, domain=args.domain, min_materiality=args.min_materiality)
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "quality": corpus_quality_summary(df), "out": str(args.out)}, indent=2, default=str))


def cmd_base_rates(args: argparse.Namespace) -> None:
    df = base_rate_table(
        args.event_study,
        horizon=args.horizon,
        group_by=args.group_by,
        min_count=args.min_count,
        out_path=args.out,
    )
    if args.out:
        print(f"Wrote base-rate table: {args.out}")
    print(df.head(args.head).to_string(index=False))


def cmd_calibrate(args: argparse.Namespace) -> None:
    table, report = calibration_table(
        args.predictions,
        probability_column=args.probability_column,
        target_column=args.target_column,
        bins=args.bins,
        out_path=args.out,
    )
    print(json.dumps({"report": report, "out": str(args.out)}, indent=2, default=str))
    print(table.to_string(index=False))


def cmd_simulate_strategy(args: argparse.Namespace) -> None:
    _, report = simulate_event_strategy(
        args.predictions,
        horizon=args.horizon,
        probability_column=args.probability_column,
        return_column=args.return_column,
        long_threshold=args.long_threshold,
        short_threshold=args.short_threshold,
        allow_short=args.allow_short,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
        out_trades=args.out_trades,
    )
    if args.out_report:
        ensure_parent(args.out_report).write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(args.out_report)
    print(json.dumps(report, indent=2, default=str))


def cmd_null_shuffle(args: argparse.Namespace) -> None:
    _, report = null_shuffle_strategy_test(
        args.predictions,
        horizon=args.horizon,
        n_iter=args.n_iter,
        seed=args.seed,
        probability_column=args.probability_column,
        return_column=args.return_column,
        long_threshold=args.long_threshold,
        short_threshold=args.short_threshold,
        allow_short=args.allow_short,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
        out_path=args.out,
    )
    if args.out_report:
        ensure_parent(args.out_report).write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(args.out_report)
    print(json.dumps(report, indent=2, default=str))


def cmd_purged_walk_forward(args: argparse.Namespace) -> None:
    _, report = purged_walk_forward_direction_model(
        args.event_study,
        horizon=args.horizon,
        min_train=args.min_train,
        purge_days=args.purge_days,
        out_predictions=args.out_predictions,
        out_report=args.out_report,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_research_backtest(args: argparse.Namespace) -> None:
    report = run_research_backtest(
        args.event_study,
        args.out_dir,
        horizon=args.horizon,
        min_train=args.min_train,
        purge_days=args.purge_days,
        probability_threshold=args.probability_threshold,
        allow_short=args.allow_short,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
        calibration_bins=args.calibration_bins,
        null_iterations=args.null_iterations,
        seed=args.seed,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_make_placebo_events(args: argparse.Namespace) -> None:
    df, diag = make_placebo_events(
        args.events,
        args.prices_dir,
        args.out,
        n_per_event=args.n_per_event,
        mode=args.mode,
        shift_days=comma_ints(args.shift_days),
        avoid_window_days=args.avoid_window_days,
        seed=args.seed,
    )
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out)}, indent=2, default=str))


def cmd_make_peer_controls(args: argparse.Namespace) -> None:
    df, diag = make_peer_control_events(args.events, args.out, peer_map=args.peer_map, universe=args.universe)
    print(json.dumps({"rows": int(len(df)), "diagnostics": diag.to_dict(), "out": str(args.out)}, indent=2, default=str))


def cmd_corpus_demo(args: argparse.Namespace) -> None:
    root = Path(args.root)
    data_paths = generate_corpus_demo_data(root / "data" / "corpus_demo", seed=args.seed)
    event_study_out = root / "artifacts" / "corpus_demo_event_study.csv"
    placebo_events = root / "artifacts" / "corpus_demo_placebo_events.csv"
    placebo_study_out = root / "artifacts" / "corpus_demo_placebo_event_study.csv"
    peer_events = root / "artifacts" / "corpus_demo_peer_events.csv"
    backtest_dir = root / "artifacts" / "corpus_demo_backtest"
    df, diag = run_event_study(
        data_paths["events_enriched"],
        data_paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1, 3, 10),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    ensure_parent(event_study_out)
    df.to_csv(event_study_out, index=False)
    make_placebo_events(data_paths["events_enriched"], data_paths["prices_dir"], placebo_events, n_per_event=1, seed=args.seed)
    placebo_df, placebo_diag = run_event_study(
        placebo_events,
        data_paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1, 3, 10),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    placebo_df.to_csv(placebo_study_out, index=False)
    make_peer_control_events(data_paths["events_enriched"], peer_events)
    backtest_report = run_research_backtest(
        event_study_out,
        backtest_dir,
        horizon=1,
        min_train=30,
        purge_days=3,
        probability_threshold=0.58,
        allow_short=True,
        cost_bps=5.0,
        slippage_bps=5.0,
        null_iterations=100,
        seed=args.seed,
    )
    print("Corpus/backtest demo complete.")
    print(json.dumps({
        "events_enriched": str(data_paths["events_enriched"]),
        "corpus_validation": str(data_paths["validation"]),
        "prices_dir": str(data_paths["prices_dir"]),
        "event_study": str(event_study_out),
        "placebo_events": str(placebo_events),
        "placebo_event_study": str(placebo_study_out),
        "peer_events": str(peer_events),
        "backtest_report": backtest_report,
        "diagnostics": {"event_study": diag.__dict__, "placebo_event_study": placebo_diag.__dict__},
    }, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mre",
        description="Market Reaction Engine: event-study workbench for abnormal market reactions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pipeline-template", help="Create a JSON config for an automated corpus/falsification research run.")
    p.add_argument("--run-id", default="semis_earnings_research_v1")
    p.add_argument("--domain", default="earnings_guidance")
    p.add_argument("--preset", default="semiconductors")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--source-mode", default="yfinance_earnings", choices=["manual_events", "yfinance_earnings", "alpha_vantage_earnings", "sec_earnings", "sec_docs", "local_ingestion", "source_documents"])
    p.add_argument("--out", default="research_pipeline.json")
    p.set_defaults(func=cmd_pipeline_template)

    p = sub.add_parser("run-pipeline", help="Run an automated research loop: source candidates, review queue, corpus, event study, controls, backtests, and gates.")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stages", nargs="*", default=[], help="Reserved for future partial execution; current implementation runs the full ordered loop.")
    p.set_defaults(func=cmd_run_pipeline)

    p = sub.add_parser("review-queue", help="Create a human-review queue from candidate events and optional extracted facts.")
    p.add_argument("--events", required=True)
    p.add_argument("--facts", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--auto-accept-min-confidence", type=float, default=None, help="Prototype only: mark rows reviewed if evidence confidence exceeds this threshold.")
    p.add_argument("--auto-accept-min-facts", type=int, default=1)
    p.set_defaults(func=cmd_review_queue)

    p = sub.add_parser("pipeline-demo", help="Run the offline automation pipeline demo.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=cmd_pipeline_demo)

    p = sub.add_parser("corpus-domains", help="List supported narrow-domain corpus schemas.")
    p.set_defaults(func=cmd_corpus_domains)

    p = sub.add_parser("domain-template", help="Create a domain-specific curated event template.")
    p.add_argument("--domain", required=True, help="earnings_guidance, fda_biotech, regulatory_legal, cyber_incident, or recall_safety")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--corpus-name", default=None)
    p.add_argument("--rows-per-ticker", type=int, default=1)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_domain_template)

    p = sub.add_parser("build-corpus", help="Merge and validate curated event CSVs into one narrow-domain corpus.")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--domain", default=None)
    p.add_argument("--corpus-name", default=None)
    p.add_argument("--require-reviewed", action="store_true", help="Keep only rows that pass corpus validation.")
    p.add_argument("--min-materiality", type=float, default=0.0)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_build_corpus)

    p = sub.add_parser("validate-corpus", help="Validate a narrow-domain event corpus for missing review/evidence fields.")
    p.add_argument("--events", required=True)
    p.add_argument("--domain", default=None)
    p.add_argument("--min-materiality", type=float, default=0.0)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_validate_corpus)

    p = sub.add_parser("base-rates", help="Summarize abnormal-return base rates by event metadata bins.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--group-by", default="event_family,event_subtype,surprise_direction,surprise_magnitude")
    p.add_argument("--min-count", type=int, default=3)
    p.add_argument("--head", type=int, default=20)
    p.add_argument("--out")
    p.set_defaults(func=cmd_base_rates)

    p = sub.add_parser("sector-presets", help="List built-in sector/ticker presets for earnings corpus bootstrapping.")
    p.set_defaults(func=cmd_sector_presets)

    p = sub.add_parser("earnings-template", help="Create a manual earnings/guidance event template.")
    p.add_argument("--preset", help="Optional preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--out", default="data/events/earnings_template.csv")
    p.set_defaults(func=cmd_earnings_template)

    p = sub.add_parser("expectations-template", help="Create a consensus/guidance/options expectation template for an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_expectations_template)

    p = sub.add_parser("earnings-corpus", help="Build an EPS-surprise earnings corpus from Alpha Vantage.")
    p.add_argument("--preset", help="Preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit-per-ticker", type=int, default=None)
    p.add_argument("--release-session", default="unknown", choices=["before_open", "intraday", "after_close", "unknown"])
    p.add_argument("--requests-per-minute", type=float, default=5.0)
    p.add_argument("--api-key", default=None, help="Alpha Vantage API key. Defaults to ALPHA_VANTAGE_API_KEY.")
    p.add_argument("--out", default="data/events/earnings_corpus.csv")
    p.set_defaults(func=cmd_earnings_corpus)

    p = sub.add_parser("yfinance-earnings-corpus", help="Build a prototype EPS-surprise earnings corpus from yfinance earnings dates.")
    p.add_argument("--preset", help="Preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit-per-ticker", type=int, default=40)
    p.add_argument("--sleep-seconds", type=float, default=0.2)
    p.add_argument("--out", default="data/events/yfinance_earnings_corpus.csv")
    p.set_defaults(func=cmd_yfinance_earnings_corpus)

    p = sub.add_parser("sec-earnings-corpus", help="Build primary-source earnings/guidance candidate events from SEC filings.")
    p.add_argument("--preset", help="Preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit-per-ticker", type=int, default=None)
    p.add_argument("--include-periodic", action="store_true", help="Also include 10-Q/10-K candidates; noisier.")
    p.add_argument("--include-guidance-candidates", action="store_true", help="Include noisy 8-K Item 7.01/8.01 guidance candidates.")
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=5.0)
    p.add_argument("--out", default="data/events/sec_earnings_candidates.csv")
    p.set_defaults(func=cmd_sec_earnings_corpus)


    p = sub.add_parser("source-docs-template", help="Create a raw source-document manifest template for extraction.")
    p.add_argument("--out", default="data/events/source_documents.csv")
    p.set_defaults(func=cmd_source_docs_template)

    p = sub.add_parser("ingestion-template", help="Create a URL/local/inline source-ingestion template.")
    p.add_argument("--out", default="data/events/source_ingestion_template.csv")
    p.set_defaults(func=cmd_ingestion_template)

    p = sub.add_parser("ingest-source-docs", help="Download/normalize URL, local-path, or inline source rows into extraction-ready text files.")
    p.add_argument("--input", required=True, help="Input CSV with source_url, path, or text plus ticker/event_time metadata.")
    p.add_argument("--out", required=True, help="Output source-document manifest compatible with extract-facts.")
    p.add_argument("--docs-dir", required=True, help="Directory for normalized text files.")
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=2.0)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--include-inline-text", action="store_true", help="Also include normalized text in the output CSV; usually leave off for large docs.")
    p.add_argument("--min-text-chars", type=int, default=20)
    p.set_defaults(func=cmd_ingest_source_docs)

    p = sub.add_parser("sec-source-docs", help="Download SEC filing primary docs and likely earnings-release exhibits into a source-document manifest.")
    p.add_argument("--preset", help="Preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--forms", default="8-K", help="Comma-separated SEC forms, default 8-K.")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--item-filter", default="2.02", help="Comma-separated 8-K item filter. Use 'all' to disable.")
    p.add_argument("--limit-per-ticker", type=int, default=None)
    p.add_argument("--no-primary", action="store_true", help="Do not include primary filing document.")
    p.add_argument("--no-exhibits", action="store_true", help="Do not include likely earnings-release exhibits.")
    p.add_argument("--exhibit-pattern", default=r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|earnings|results|press[-_ ]?release)")
    p.add_argument("--docs-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=5.0)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--min-text-chars", type=int, default=40)
    p.set_defaults(func=cmd_sec_source_docs)

    p = sub.add_parser("extract-facts", help="Extract evidence-grounded earnings/guidance facts from a source-document manifest.")
    p.add_argument("--documents", required=True, help="CSV manifest with source_doc_id, ticker, event_time, and text/path.")
    p.add_argument("--facts-out", required=True, help="Output extracted fact rows with evidence spans.")
    p.add_argument("--expectations-out", required=True, help="Output pivoted expectation-feature rows.")
    p.add_argument("--events-out", required=True, help="Output event rows generated from source documents.")
    p.set_defaults(func=cmd_extract_facts)

    p = sub.add_parser("extraction-packets", help="Create JSONL work packets for an external LLM extractor; does not call an LLM.")
    p.add_argument("--documents", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-chars", type=int, default=12000)
    p.set_defaults(func=cmd_extraction_packets)

    p = sub.add_parser("validate-llm-facts", help="Validate JSONL LLM extraction output against source-document evidence.")
    p.add_argument("--documents", required=True)
    p.add_argument("--llm-jsonl", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--allow-missing-evidence", action="store_true")
    p.set_defaults(func=cmd_validate_llm_facts)

    p = sub.add_parser("enrich-expectations", help="Add pre-event price/expectation context features to an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--prices-dir", required=True)
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_enrich_expectations)

    p = sub.add_parser("merge-expectations", help="Merge external point-in-time expectation fields into an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--expectations", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fill-labels", action="store_true")
    p.set_defaults(func=cmd_merge_expectations)

    p = sub.add_parser("release-times-template", help="Create a template for exact release timestamps.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_release_times_template)

    p = sub.add_parser("merge-release-times", help="Merge exact release timestamps into events and update release_session.")
    p.add_argument("--events", required=True)
    p.add_argument("--release-times", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--key", default="event_id")
    p.add_argument("--require-all-events", action="store_true")
    p.set_defaults(func=cmd_merge_release_times)

    p = sub.add_parser("options-template", help="Create an option snapshot template for ATM-straddle implied moves.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_options_template)

    p = sub.add_parser("merge-options", help="Estimate and merge pre-event implied move from option snapshot rows.")
    p.add_argument("--events", required=True)
    p.add_argument("--options", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-quote-age-days", type=int, default=14, help="Use -1 to disable quote-age filtering.")
    p.set_defaults(func=cmd_merge_options)

    p = sub.add_parser("analyst-revisions-template", help="Create a template for point-in-time analyst estimate revisions.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_analyst_revisions_template)

    p = sub.add_parser("merge-analyst-revisions", help="Compute and merge analyst revision features into events.")
    p.add_argument("--events", required=True)
    p.add_argument("--revisions", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--windows", default="7,30")
    p.add_argument("--metrics", default="eps,revenue,gross_margin,forward_revenue")
    p.set_defaults(func=cmd_merge_analyst_revisions)

    p = sub.add_parser("make-template", help="Create an empty generic event CSV template.")
    p.add_argument("--out", default="data/events/events_template.csv")
    p.set_defaults(func=cmd_make_template)

    p = sub.add_parser("init-demo", help="Generate deterministic synthetic demo prices/events.")
    p.add_argument("--out", default="data/demo")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_init_demo)

    p = sub.add_parser("fetch-prices", help="Fetch daily prices from yfinance into local CSV files.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--events", help="Optional event CSV; fetch all tickers appearing there.")
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out-dir", default="data/prices")
    p.set_defaults(func=cmd_fetch_prices)

    p = sub.add_parser("run-event-study", help="Compute raw and abnormal returns around events.")
    p.add_argument("--events", required=True)
    p.add_argument("--prices-dir", required=True)
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--horizons", default="1,3,10")
    p.add_argument("--estimation-window", type=int, default=120)
    p.add_argument("--estimation-gap", type=int, default=5)
    p.add_argument("--min-estimation-observations", type=int, default=60)
    p.add_argument("--out", default="artifacts/event_study.csv")
    p.set_defaults(func=cmd_run_event_study)

    p = sub.add_parser("train", help="Train a baseline chronological-split direction model.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--out-model", default="artifacts/reaction_direction.joblib")
    p.add_argument("--out-report", default="artifacts/model_report.json")
    p.add_argument("--test-size", type=float, default=0.3)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("walk-forward", help="Walk-forward event-by-event direction evaluation.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--min-train", type=int, default=40)
    p.add_argument("--out-predictions", default="artifacts/walk_forward_predictions.csv")
    p.add_argument("--out-report", default="artifacts/walk_forward_report.json")
    p.set_defaults(func=cmd_walk_forward)

    p = sub.add_parser("purged-walk-forward", help="Walk-forward direction evaluation with recent overlapping rows purged.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--min-train", type=int, default=40)
    p.add_argument("--purge-days", type=int, default=None)
    p.add_argument("--out-predictions", default="artifacts/purged_walk_forward_predictions.csv")
    p.add_argument("--out-report", default="artifacts/purged_walk_forward_report.json")
    p.set_defaults(func=cmd_purged_walk_forward)

    p = sub.add_parser("calibrate", help="Compute probability calibration bins from walk-forward predictions.")
    p.add_argument("--predictions", required=True)
    p.add_argument("--probability-column", default="predicted_positive_probability")
    p.add_argument("--target-column", default="y_true")
    p.add_argument("--bins", type=int, default=10)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("simulate-strategy", help="Apply thresholds, costs, and slippage to event-level predictions.")
    p.add_argument("--predictions", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--probability-column", default="predicted_positive_probability")
    p.add_argument("--return-column", default=None)
    p.add_argument("--long-threshold", type=float, default=0.60)
    p.add_argument("--short-threshold", type=float, default=None)
    p.add_argument("--allow-short", action="store_true")
    p.add_argument("--cost-bps", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--out-trades", default="artifacts/strategy_trades.csv")
    p.add_argument("--out-report", default="artifacts/strategy_report.json")
    p.set_defaults(func=cmd_simulate_strategy)

    p = sub.add_parser("null-shuffle", help="Shuffle realized returns to build a simple null distribution for a strategy.")
    p.add_argument("--predictions", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--n-iter", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--probability-column", default="predicted_positive_probability")
    p.add_argument("--return-column", default=None)
    p.add_argument("--long-threshold", type=float, default=0.60)
    p.add_argument("--short-threshold", type=float, default=None)
    p.add_argument("--allow-short", action="store_true")
    p.add_argument("--cost-bps", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--out", default="artifacts/null_shuffle_distribution.csv")
    p.add_argument("--out-report", default="artifacts/null_shuffle_report.json")
    p.set_defaults(func=cmd_null_shuffle)

    p = sub.add_parser("research-backtest", help="Run purged walk-forward, calibration, strategy simulation, and null shuffle in one harness.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--out-dir", default="artifacts/research_backtest")
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--min-train", type=int, default=40)
    p.add_argument("--purge-days", type=int, default=None)
    p.add_argument("--probability-threshold", type=float, default=0.60)
    p.add_argument("--allow-short", action="store_true")
    p.add_argument("--cost-bps", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--calibration-bins", type=int, default=10)
    p.add_argument("--null-iterations", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_research_backtest)

    p = sub.add_parser("make-placebo-events", help="Create random/shifted non-event placebo controls from an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--prices-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n-per-event", type=int, default=1)
    p.add_argument("--mode", default="random", choices=["random", "shift"])
    p.add_argument("--shift-days", default="30,60,90,-30,-60,-90")
    p.add_argument("--avoid-window-days", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_make_placebo_events)

    p = sub.add_parser("make-peer-controls", help="Create peer-control events by replacing the affected ticker with a peer.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--peer-map", default=None, help="Optional CSV with ticker,peer_ticker columns.")
    p.add_argument("--universe", default=None, help="Optional CSV with a ticker column; peers rotate through this list.")
    p.set_defaults(func=cmd_make_peer_controls)

    p = sub.add_parser("predict", help="Run a trained direction model on event-study rows.")
    p.add_argument("--model", required=True)
    p.add_argument("--event-study", required=True)
    p.add_argument("--out")
    p.add_argument("--head", type=int, default=10)
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("analogs", help="Find nearest historical analog events by pre-event/event metadata.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--event-id", required=True)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--out")
    p.set_defaults(func=cmd_analogs)

    p = sub.add_parser("report", help="Create a Markdown event-study summary report.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--out", default="artifacts/report.md")
    p.add_argument("--horizon", type=int, default=1)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("sec-template", help="Create an event template from recent SEC submissions.")
    p.add_argument("--ticker", required=True)
    p.add_argument("--forms", default="8-K,10-Q,10-K")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--out", required=True)
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=5.0)
    p.set_defaults(func=cmd_sec_template)

    p = sub.add_parser("demo", help="Run the full offline synthetic demo pipeline.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_demo)


    p = sub.add_parser("extraction-demo", help="Run the offline source-document extraction demo.")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd_extraction_demo)

    p = sub.add_parser("source-ingestion-demo", help="Run the offline source-ingestion + extraction demo.")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd_source_ingestion_demo)

    p = sub.add_parser("corpus-demo", help="Run the offline synthetic multi-domain corpus + backtest demo.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=11)
    p.set_defaults(func=cmd_corpus_demo)

    p = sub.add_parser("earnings-demo", help="Run the offline synthetic earnings/expectations demo pipeline.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_earnings_demo)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
