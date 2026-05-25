from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..analyst_revisions import make_analyst_revisions_template, merge_analyst_revisions
from ..activist_13d import (
    audit_activist_13d_timestamps_and_duplicates,
    build_activist_13d_sec_source_documents,
    enrich_activist_13d_context,
    parse_activist_13d_manifest,
    validate_activist_13d_parser,
    write_activist_13d_readiness_report,
)
from ..backtest import (
    calibration_table,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    purged_walk_forward_direction_model,
    run_research_backtest,
    simulate_event_strategy,
)
from ..base_rates import base_rate_table
from ..biotech_catalysts import (
    build_biotech_catalyst_gold_template,
    build_biotech_catalyst_source_documents,
    parse_biotech_catalyst_manifest,
    validate_biotech_catalyst_parser,
    write_biotech_catalyst_parser_audit_report,
    write_biotech_catalyst_readiness_report,
)
from ..biotech_falsification import run_biotech_catalyst_falsification_pass
from ..biotech_negative_catalyst import (
    run_biotech_negative_catalyst_confirmation,
    run_biotech_negative_catalyst_corrected_confirmation,
    run_biotech_negative_catalyst_timestamp_repair,
)
from ..capital_raises import (
    build_capital_raise_sec_source_documents,
    build_sec_shares_outstanding_context,
    enrich_capital_raise_context,
    parse_capital_raise_manifest,
    validate_capital_raise_parser,
    write_capital_raise_readiness_report,
    write_capital_raise_parser_audit_report,
)
from ..government_contracts import (
    build_government_contract_human_audit,
    build_government_contract_parser_gold_template,
    build_government_contract_public_announcement_candidates,
    build_government_contract_source_documents,
    enrich_government_contract_context,
    load_recipient_ticker_map,
    parse_government_contract_manifest,
    validate_government_contract_public_links,
    validate_government_contract_parser,
    write_government_contract_human_audit_report,
    write_government_contract_mapping_audit_report,
    write_government_contract_parser_audit_report,
    write_government_contract_public_awareness_report,
    write_government_contract_readiness_report,
)
from ..government_contract_falsification import run_government_contract_falsification_pass
from ..corpus import build_curated_corpus, corpus_quality_summary, list_corpus_domains, make_domain_event_template, validate_corpus_csv
from ..corpus_demo import generate_corpus_demo_data
from ..claim_review import make_claim_review_queue
from ..cyber_8k_dataset import build_cyber_8k_dataset
from ..cyber_8k_digest import build_cyber_8k_digest
from ..cyber_8k_parser import run_cyber_8k_parse_manifest
from ..cyber_8k_pipeline import run_cyber_8k_pipeline, write_cyber_8k_pipeline_template
from ..cyber_8k_quality import build_cyber_8k_quality_report
from ..cyber_8k_site import build_cyber_8k_static_site
from ..cyber_8k_sources import build_cyber_8k_source_documents
from ..demo import generate_demo_data
from ..domain_registry import (
    DEFAULT_REGISTRY_PATH,
    format_domain_status,
    format_intake_score,
    format_revisit_triggers,
    intake_score_to_json,
    load_domain_registry,
    records_to_json,
    score_intake,
    monitor_records,
    write_domain_final_report,
)
from ..generic.pipeline import run_generic_pipeline, write_generic_pipeline_template
from ..generic.publishers import build_generic_digest, build_generic_static_site, export_generic_api
from ..generic.quality import build_generic_quality_report
from ..generic.review import make_generic_claim_review_queue
from ..extraction import build_extraction_packets, run_document_extraction, validate_llm_facts_jsonl
from ..extraction_demo import generate_extraction_demo_data
from ..ingestion import build_sec_source_document_manifest, ingest_source_document_manifest, make_ingestion_template
from ..source_ingestion_demo import generate_source_ingestion_demo_data
from ..earnings import build_alpha_vantage_earnings_corpus, build_earnings_corpus_from_sec, build_yfinance_earnings_corpus, write_manual_earnings_template
from ..earnings_demo import generate_earnings_demo_data
from ..event_study import run_event_study
from ..events import event_tickers, load_events, make_event_template
from ..exhibit99_parser import parse_exhibit99_manifest, pivot_parsed_facts, validate_parser_against_gold
from ..expectations import enrich_expectations, make_expectations_template, merge_external_expectations
from ..sec_context import add_sec_context
from ..sec_readiness import build_readiness, write_readiness_report
from ..sec_review import create_review_template
from ..sec_timestamps import audit_timestamps
from ..source_docs import SecClient as SecSourceClient, write_sec_source_documents
from ..management_guidance import (
    build_management_guidance_bridge,
    validate_management_guidance_bridge,
    write_management_guidance_period_audit,
    write_management_guidance_bridge_report,
    write_management_guidance_expansion_report,
    write_management_guidance_validation_report,
)
from ..modeling import find_analogs, predict_direction, train_direction_model, walk_forward_direction_model
from ..options import make_options_template, merge_options_implied_moves
from ..pipeline import run_pipeline, write_pipeline_template
from ..pipeline_demo import generate_pipeline_demo
from ..release_times import make_release_times_template, merge_release_times
from ..paths import ensure_parent
from ..prices import fetch_yfinance_prices
from ..reports import event_study_report
from ..review import make_review_queue
from ..source_docs import make_source_docs_template
from ..sec import SecClient, filings_to_event_template
from ..sectors import get_preset, list_presets, parse_ticker_list


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


def cmd_sec_domain_source_docs(args: argparse.Namespace) -> None:
    client = SecSourceClient(user_agent=args.sec_user_agent)
    rows = write_sec_source_documents(
        args.out,
        domain=args.domain,
        tickers=args.tickers,
        ticker_csv=args.ticker_csv,
        forms=args.forms,
        items=args.items,
        start=args.start,
        end=args.end,
        docs_dir=args.docs_dir,
        client=client,
    )
    print(json.dumps({"rows": len(rows), "out": str(args.out)}, indent=2))


def cmd_sec_domain_review_template(args: argparse.Namespace) -> None:
    rows = create_review_template(args.input, args.out)
    print(json.dumps({"rows": len(rows), "out": str(args.out)}, indent=2))


def cmd_sec_domain_context(args: argparse.Namespace) -> None:
    rows = add_sec_context(
        args.input,
        args.out,
        prices_dir=args.prices_dir,
        benchmark_ticker=args.benchmark_ticker,
        shares_outstanding_path=args.shares_outstanding,
        market_cap_path=args.market_cap,
    )
    print(json.dumps({"rows": len(rows), "out": str(args.out)}, indent=2))


def cmd_sec_domain_timestamp_audit(args: argparse.Namespace) -> None:
    rows = audit_timestamps(args.input, args.out, has_intraday_prices=args.has_intraday_prices)
    print(json.dumps({"rows": len(rows), "out": str(args.out)}, indent=2))


def cmd_sec_domain_readiness_report(args: argparse.Namespace) -> None:
    readiness = build_readiness(
        domain=args.domain,
        sources_path=args.sources,
        parsed_path=args.parsed,
        review_path=args.review,
        parser_audit_path=args.parser_audit,
        timestamp_audit_path=args.timestamp_audit,
        context_path=args.context,
        min_train=args.min_train,
    )
    write_readiness_report(args.out, readiness)
    print(json.dumps(readiness, indent=2, default=str))


def cmd_domain_status(args: argparse.Namespace) -> None:
    records = load_domain_registry(args.registry)
    if args.json:
        print(records_to_json(records))
    else:
        print(format_domain_status(records))


def cmd_domain_intake_score(args: argparse.Namespace) -> None:
    score = score_intake(args.input)
    if args.json:
        print(intake_score_to_json(score))
    else:
        print(format_intake_score(score))


def cmd_revisit_triggers(args: argparse.Namespace) -> None:
    records = load_domain_registry(args.registry)
    if args.json:
        print(records_to_json(monitor_records(records)))
    else:
        print(format_revisit_triggers(records))


def cmd_domain_final_report(args: argparse.Namespace) -> None:
    record = write_domain_final_report(
        domain=args.domain,
        out_path=args.out,
        registry_path=args.registry,
        readiness_report=args.readiness_report,
        parser_audit=args.parser_audit,
        timestamp_audit=args.timestamp_audit,
        falsification_report=args.falsification_report,
        fresh_confirmation_report=args.fresh_confirmation_report,
        execution_audit=args.execution_audit,
        overwrite=args.overwrite,
    )
    print(json.dumps({"domain": record.domain, "status": record.status, "out": str(args.out)}, indent=2))



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


def cmd_parse_exhibit99(args: argparse.Namespace) -> None:
    facts = parse_exhibit99_manifest(args.documents, args.facts_out, min_confidence=args.min_confidence)
    features = pivot_parsed_facts(facts, args.features_out, min_confidence=args.usable_confidence)
    payload = {
        "documents": args.documents,
        "fact_rows": int(len(facts)),
        "feature_rows": int(len(features)),
        "facts_out": str(args.facts_out),
        "features_out": str(args.features_out),
        "fact_counts": facts["fact_name"].value_counts(dropna=False).to_dict() if not facts.empty else {},
        "period_role_counts": facts["period_role"].value_counts(dropna=False).to_dict() if not facts.empty else {},
        "warning": "Specialized Exhibit 99 parser output still requires gold-set validation before modeling.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_validate_exhibit99_parser(args: argparse.Namespace) -> None:
    facts = Path(args.facts)
    gold = Path(args.gold)
    facts_df = __import__("pandas").read_csv(facts)
    gold_df = __import__("pandas").read_csv(gold)
    errors, report = validate_parser_against_gold(facts_df, gold_df, out_errors=args.errors_out)
    report_path = ensure_parent(args.report_out)
    lines = [
        "# Exhibit 99 Parser Validation Report",
        "",
        f"- facts: `{facts}`",
        f"- gold: `{gold}`",
        f"- errors: `{args.errors_out}`",
        "",
        "## Metrics",
        "",
        f"- gold_rows: {report.get('gold_rows', 0)}",
        f"- correct_rows: {report.get('correct_rows', 0)}",
        f"- row_accuracy: {report.get('row_accuracy', 0):.3f}" if "row_accuracy" in report else f"- status: {report.get('status', 'unknown')}",
        "",
        "## By Fact",
        "",
    ]
    for fact_name, metrics in (report.get("by_fact", {}) or {}).items():
        lines.append(f"- {fact_name}: {metrics}")
    if not errors.empty and (errors["status"] != "ok").any():
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in errors[errors["status"] != "ok"].head(50).iterrows():
            lines.append(f"- {row['event_id']} / {row['fact_name']} / {row['period_role']}: {row['status']} expected={row['expected_value']} actual={row['actual_value']}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "errors": str(args.errors_out), **report}, indent=2, default=str))


def cmd_management_guidance_bridge(args: argparse.Namespace) -> None:
    bridge, diag = build_management_guidance_bridge(
        args.features,
        args.out,
        events_path=args.events,
        failures_path=args.failures_out,
        min_confidence=args.min_confidence,
        min_prior_event_gap_days=args.min_prior_event_gap_days,
        max_prior_event_gap_days=args.max_prior_event_gap_days,
        min_actual_to_prior_ratio=args.min_actual_to_prior_ratio,
        max_actual_to_prior_ratio=args.max_actual_to_prior_ratio,
        require_period_alignment=not args.no_require_period_alignment,
    )
    if args.report_out:
        write_management_guidance_bridge_report(bridge, diag, args.report_out)
    if args.period_audit_out:
        write_management_guidance_period_audit(bridge, args.period_audit_out)
    if args.expansion_report_out:
        write_management_guidance_expansion_report(bridge, diag, args.expansion_report_out, event_study_path=args.event_study)
    print(json.dumps({"rows": int(len(bridge)), "out": str(args.out), "report": str(args.report_out or ""), "diagnostics": diag.to_dict()}, indent=2, default=str))


def cmd_validate_management_guidance_bridge(args: argparse.Namespace) -> None:
    report = validate_management_guidance_bridge(
        args.bridge,
        min_ready_rows=args.min_ready_rows,
        preferred_ready_rows=args.preferred_ready_rows,
        min_tickers=args.min_tickers,
        max_single_ticker_share=args.max_single_ticker_share,
        min_gap_days=args.min_prior_event_gap_days,
        max_gap_days=args.max_prior_event_gap_days,
        min_confidence=args.min_confidence,
    )
    write_management_guidance_validation_report(report, args.report_out)
    print(json.dumps({"report": str(args.report_out), **report}, indent=2, default=str))


def cmd_biotech_catalyst_source_docs(args: argparse.Namespace) -> None:
    tickers: set[str] = set(parse_ticker_list(getattr(args, "tickers", []) or []))
    benchmark = (getattr(args, "benchmark", "") or "").upper().strip() or "SPY"
    sector_benchmark = (getattr(args, "sector_benchmark", "") or "").upper().strip()
    if args.preset:
        preset = get_preset(args.preset)
        tickers.update(preset.tickers)
        if not sector_benchmark:
            sector_benchmark = preset.sector_benchmark
        if not benchmark:
            benchmark = preset.benchmark
    forms = [v.strip().upper() for v in args.forms.split(",") if v.strip()]
    client = None
    if tickers and not args.no_sec:
        client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    df, diag = build_biotech_catalyst_source_documents(
        client,
        tickers=sorted(tickers),
        out_manifest=args.out,
        docs_dir=args.docs_dir,
        start=args.start,
        end=args.end,
        forms=forms,
        item_filter=args.item_filter,
        limit_per_ticker=args.limit_per_ticker,
        sector_benchmark=sector_benchmark,
        source_manifests=args.source_manifests,
        include_sec=not args.no_sec,
        overwrite=args.overwrite,
        min_text_chars=args.min_text_chars,
    )
    print(
        json.dumps(
            {
                "provider": "sec-edgar + manifest",
                "tickers": sorted(tickers),
                "benchmark": benchmark,
                "sector_benchmark": sector_benchmark,
                "rows": int(len(df)),
                "diagnostics": diag.to_dict(),
                "out": str(args.out),
                "docs_dir": str(args.docs_dir),
                "warning": "Biotech catalyst source documents are candidates; FDA/ClinicalTrials/openFDA rows should be added through reviewed source manifests before modeling.",
            },
            indent=2,
            default=str,
        )
    )


def cmd_parse_biotech_catalysts(args: argparse.Namespace) -> None:
    facts, features, events = parse_biotech_catalyst_manifest(
        args.documents,
        args.facts_out,
        args.features_out,
        args.events_out,
        min_confidence=args.min_confidence,
        usable_confidence=args.usable_confidence,
    )
    payload = {
        "documents": args.documents,
        "fact_rows": int(len(facts)),
        "feature_rows": int(len(features)),
        "event_rows": int(len(events)),
        "facts_out": str(args.facts_out),
        "features_out": str(args.features_out),
        "events_out": str(args.events_out),
        "fact_counts": facts["fact_name"].value_counts(dropna=False).to_dict() if not facts.empty else {},
        "biotech_catalyst_event_type_counts": features["biotech_catalyst_event_type"].value_counts(dropna=False).to_dict() if "biotech_catalyst_event_type" in features.columns else {},
        "warning": "Biotech catalyst parser output is a review queue, not a model-ready corpus.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_validate_biotech_catalyst_parser(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    facts_df = pd.read_csv(args.facts)
    gold_path = Path(args.gold)
    if args.build_gold_template or not gold_path.exists():
        gold = build_biotech_catalyst_gold_template(facts_df, gold_path)
        report = {
            "gold_rows": int(len(gold)),
            "status": "gold_template_created_requires_human_review",
            "parser_audit_pass": False,
            "gates": {"human_reviewed_gold_set_exists": False},
        }
        report_path = write_biotech_catalyst_parser_audit_report(report, pd.DataFrame(), args.report_out)
        ensure_parent(args.errors_out)
        pd.DataFrame(columns=["event_id", "fact_name", "expected_value", "actual_value", "unit", "status"]).to_csv(args.errors_out, index=False)
        print(json.dumps({"report": str(report_path), "gold": str(gold_path), "errors": str(args.errors_out), **report}, indent=2, default=str))
        return
    gold_df = pd.read_csv(gold_path)
    errors, report = validate_biotech_catalyst_parser(facts_df, gold_df, out_errors=args.errors_out)
    report_path = write_biotech_catalyst_parser_audit_report(report, errors, args.report_out)
    print(json.dumps({"report": str(report_path), "errors": str(args.errors_out), **report}, indent=2, default=str))


def cmd_biotech_catalyst_readiness_report(args: argparse.Namespace) -> None:
    summary = write_biotech_catalyst_readiness_report(
        args.events,
        args.out,
        min_train=args.min_train,
        source_documents_path=args.source_documents,
        parser_errors_path=args.parser_errors,
    )
    print(json.dumps({"report": str(args.out), **summary}, indent=2, default=str))


def cmd_biotech_catalyst_falsification_pass(args: argparse.Namespace) -> None:
    report = run_biotech_catalyst_falsification_pass(
        events_path=args.events,
        features_path=args.features,
        prices_dir=args.prices_dir,
        out_dir=args.out_dir,
        benchmark=args.benchmark,
        sector_benchmark=args.sector_benchmark,
        horizons=comma_ints(args.horizons),
        min_train=args.min_train,
        purge_days=args.purge_days,
        probability_threshold=args.probability_threshold,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
        null_iterations=args.null_iterations,
        seed=args.seed,
        estimation_window=args.estimation_window,
        estimation_gap=args.estimation_gap,
        min_estimation_observations=args.min_estimation_observations,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_biotech_negative_catalyst_confirmation(args: argparse.Namespace) -> None:
    report = run_biotech_negative_catalyst_confirmation(
        original_event_study_path=args.original_event_study,
        fresh_event_study_path=args.fresh_event_study,
        original_source_documents_path=args.original_source_documents,
        fresh_source_documents_path=args.fresh_source_documents,
        prices_dir=args.prices_dir,
        out_dir=args.out_dir,
        benchmark=args.benchmark,
        horizons=comma_ints(args.horizons),
        seed=args.seed,
        estimation_window=args.estimation_window,
        estimation_gap=args.estimation_gap,
        min_estimation_observations=args.min_estimation_observations,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_biotech_negative_catalyst_timestamp_repair(args: argparse.Namespace) -> None:
    report = run_biotech_negative_catalyst_timestamp_repair(
        original_event_study_path=args.original_event_study,
        fresh_event_study_path=args.fresh_event_study,
        original_source_documents_path=args.original_source_documents,
        fresh_source_documents_path=args.fresh_source_documents,
        prices_dir=args.prices_dir,
        out_dir=args.out_dir,
        horizons=comma_ints(args.horizons),
        min_train=args.min_train,
        sector_benchmark=args.sector_benchmark,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_biotech_negative_catalyst_corrected_confirmation(args: argparse.Namespace) -> None:
    report = run_biotech_negative_catalyst_corrected_confirmation(
        repaired_events_path=args.repaired_events,
        timestamp_audit_path=args.timestamp_audit,
        duplicate_audit_path=args.duplicate_audit,
        prices_dir=args.prices_dir,
        out_dir=args.out_dir,
        benchmark=args.benchmark,
        sector_benchmark=args.sector_benchmark,
        horizons=comma_ints(args.horizons),
        seed=args.seed,
        estimation_window=args.estimation_window,
        estimation_gap=args.estimation_gap,
        min_estimation_observations=args.min_estimation_observations,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_government_contract_falsification_pass(args: argparse.Namespace) -> None:
    report = run_government_contract_falsification_pass(
        events_path=args.events,
        prices_dir=args.prices_dir,
        out_dir=args.out_dir,
        benchmark=args.benchmark,
        horizons=comma_ints(args.horizons),
        min_train=args.min_train,
        purge_days=args.purge_days,
        probability_threshold=args.probability_threshold,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
        null_iterations=args.null_iterations,
        seed=args.seed,
        estimation_window=args.estimation_window,
        estimation_gap=args.estimation_gap,
        min_estimation_observations=args.min_estimation_observations,
    )
    print(json.dumps(report, indent=2, default=str))


def cmd_parse_capital_raises(args: argparse.Namespace) -> None:
    facts, features, events = parse_capital_raise_manifest(
        args.documents,
        args.facts_out,
        args.features_out,
        args.events_out,
        min_confidence=args.min_confidence,
        usable_confidence=args.usable_confidence,
    )
    payload = {
        "documents": args.documents,
        "fact_rows": int(len(facts)),
        "feature_rows": int(len(features)),
        "event_rows": int(len(events)),
        "facts_out": str(args.facts_out),
        "features_out": str(args.features_out),
        "events_out": str(args.events_out),
        "fact_counts": facts["fact_name"].value_counts(dropna=False).to_dict() if not facts.empty else {},
        "financing_event_type_counts": features["financing_event_type"].value_counts(dropna=False).to_dict() if "financing_event_type" in features.columns else {},
        "warning": "Capital-raise parser output is a review queue, not a model-ready corpus.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_capital_raise_sec_source_docs(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    forms = [v.strip().upper() for v in args.forms.split(",") if v.strip()]
    df, diag = build_capital_raise_sec_source_documents(
        client,
        tickers=tickers,
        out_manifest=args.out,
        docs_dir=args.docs_dir,
        start=args.start,
        end=args.end,
        forms=forms,
        item_filter=args.item_filter,
        limit_per_ticker=args.limit_per_ticker,
        sector_benchmark=sector_benchmark,
        overwrite=args.overwrite,
        min_text_chars=args.min_text_chars,
    )
    print(
        json.dumps(
            {
                "provider": "sec-edgar",
                "tickers": tickers,
                "benchmark": benchmark,
                "sector_benchmark": sector_benchmark,
                "rows": int(len(df)),
                "diagnostics": diag.to_dict(),
                "out": str(args.out),
                "docs_dir": str(args.docs_dir),
                "warning": "Capital-raise SEC documents are source candidates; review parser output before modeling.",
            },
            indent=2,
            default=str,
        )
    )


def cmd_capital_raise_shares_context(args: argparse.Namespace) -> None:
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    df, diagnostics = build_sec_shares_outstanding_context(client, args.events, args.out)
    print(json.dumps({"rows": int(len(df)), "out": str(args.out), "diagnostics": diagnostics}, indent=2, default=str))


def cmd_validate_capital_raise_parser(args: argparse.Namespace) -> None:
    facts_df = __import__("pandas").read_csv(args.facts)
    gold_df = __import__("pandas").read_csv(args.gold)
    errors, report = validate_capital_raise_parser(facts_df, gold_df, out_errors=args.errors_out)
    report_path = write_capital_raise_parser_audit_report(report, errors, args.report_out)
    print(json.dumps({"report": str(report_path), "errors": str(args.errors_out), **report}, indent=2, default=str))


def cmd_enrich_capital_raise_context(args: argparse.Namespace) -> None:
    df = enrich_capital_raise_context(
        args.events,
        args.prices_dir,
        args.out,
        benchmark_ticker=args.benchmark,
        market_caps_path=args.market_caps,
        shares_outstanding_path=args.shares_outstanding,
    )
    status_counts = df["capital_raise_context_status"].value_counts(dropna=False).to_dict() if "capital_raise_context_status" in df.columns else {}
    payload = {
        "rows": int(len(df)),
        "out": str(args.out),
        "status_counts": status_counts,
        "rows_with_discount": int(df["discount_to_last_close_pct"].notna().sum()) if "discount_to_last_close_pct" in df.columns else 0,
        "rows_with_market_cap_ratio": int(df["financing_amount_pct_market_cap"].notna().sum()) if "financing_amount_pct_market_cap" in df.columns else 0,
        "warning": "Capital-raise context enrichment is feature preparation only; review rows before modeling.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_capital_raise_readiness_report(args: argparse.Namespace) -> None:
    summary = write_capital_raise_readiness_report(args.events, args.out, min_train=args.min_train, parser_errors_path=args.parser_errors)
    print(json.dumps({"report": str(args.out), **summary}, indent=2, default=str))


def cmd_government_contract_source_docs(args: argparse.Namespace) -> None:
    df, diagnostics = build_government_contract_source_documents(
        args.out,
        mapping_path=args.mapping,
        manifest_paths=args.manifest,
        use_usaspending=args.use_usaspending,
        tickers=args.tickers,
        recipient_search=args.recipient_search,
        start=args.start,
        end=args.end,
        limit_per_recipient=args.limit_per_recipient,
        pages_per_recipient=args.pages_per_recipient,
        min_award_amount=args.min_award_amount,
        requests_per_second=args.requests_per_second,
    )
    print(
        json.dumps(
            {
                "rows": int(len(df)),
                "out": str(args.out),
                "mapping": str(args.mapping),
                "diagnostics": diagnostics,
                "warning": "Government-contract source rows are candidates; recipient mapping and funded-vs-ceiling classification require review before modeling.",
            },
            indent=2,
            default=str,
        )
    )


def cmd_parse_government_contracts(args: argparse.Namespace) -> None:
    facts, features, events = parse_government_contract_manifest(
        args.documents,
        args.facts_out,
        args.features_out,
        args.events_out,
        min_confidence=args.min_confidence,
        usable_confidence=args.usable_confidence,
    )
    payload = {
        "documents": args.documents,
        "fact_rows": int(len(facts)),
        "feature_rows": int(len(features)),
        "event_rows": int(len(events)),
        "facts_out": str(args.facts_out),
        "features_out": str(args.features_out),
        "events_out": str(args.events_out),
        "event_type_counts": features["government_contract_event_type"].value_counts(dropna=False).to_dict() if "government_contract_event_type" in features.columns else {},
        "warning": "Government-contract parser output is a review queue, not a model-ready corpus.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_government_contract_mapping_audit(args: argparse.Namespace) -> None:
    summary = write_government_contract_mapping_audit_report(
        args.source_documents,
        args.mapping,
        args.report_out,
        detail_out=args.detail_out,
    )
    print(json.dumps(summary, indent=2, default=str))


def cmd_government_contract_gold_template(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    features = pd.read_csv(args.features)
    gold = build_government_contract_parser_gold_template(features, args.out, target_events=args.target_events)
    print(
        json.dumps(
            {
                "rows": int(len(gold)),
                "events": int(gold["event_id"].nunique()) if "event_id" in gold.columns and not gold.empty else 0,
                "out": str(args.out),
                "warning": "Gold rows are machine-proposed and must be human-reviewed before parser audit can pass.",
            },
            indent=2,
            default=str,
        )
    )


def cmd_government_contract_human_audit(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    source_documents = pd.read_csv(args.source_documents)
    features = pd.read_csv(args.features)
    mapping = load_recipient_ticker_map(args.mapping)
    events = pd.read_csv(args.events) if args.events else None
    audit, gold, mapping_errors, funded_errors, audited_events, summary = build_government_contract_human_audit(
        source_documents,
        features,
        mapping,
        events=events,
        target_events=args.target_events,
    )
    audit.to_csv(args.audit_out, index=False)
    gold.to_csv(args.gold_out, index=False)
    mapping_errors.to_csv(args.mapping_errors_out, index=False)
    funded_errors.to_csv(args.funded_vs_ceiling_errors_out, index=False)
    if args.events_out and audited_events is not None:
        audited_events.to_csv(args.events_out, index=False)
        summary["events_out"] = str(args.events_out)
    report_path = write_government_contract_human_audit_report(summary, audit, mapping_errors, funded_errors, args.report_out)
    print(
        json.dumps(
            {
                "audit_out": str(args.audit_out),
                "gold_out": str(args.gold_out),
                "mapping_errors_out": str(args.mapping_errors_out),
                "funded_vs_ceiling_errors_out": str(args.funded_vs_ceiling_errors_out),
                "report_out": str(report_path),
                **summary,
                "warning": "Government-contract human audit is a corpus-quality review; no model, event study, or backtest was run.",
            },
            indent=2,
            default=str,
        )
    )


def _run_government_contract_public_link_validation(args: argparse.Namespace, links_df) -> dict:
    pd = __import__("pandas")
    events = pd.read_csv(args.events)
    parser_errors = pd.read_csv(args.parser_errors) if args.parser_errors else None
    candidates = build_government_contract_public_announcement_candidates(
        events,
        args.candidates_out,
        limit=args.candidate_limit,
    )
    validated, audit, eligible, summary = validate_government_contract_public_links(
        events,
        links_df,
        parser_errors=parser_errors,
        audit_candidates=candidates,
        target_audit_rows=args.target_audit_rows,
    )
    validated.to_csv(args.links_out, index=False)
    audit.to_csv(args.audit_out, index=False)
    eligible.to_csv(args.eligible_out, index=False)
    report_path = write_government_contract_public_awareness_report(summary, args.report_out)
    return {
        "candidates_out": str(args.candidates_out),
        "links_out": str(args.links_out),
        "audit_out": str(args.audit_out),
        "eligible_out": str(args.eligible_out),
        "report_out": str(report_path),
        **summary,
    }


def cmd_government_contract_public_announcements(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    if args.manifest:
        links_df = pd.read_csv(args.manifest)
    else:
        links_df = pd.DataFrame()
    payload = _run_government_contract_public_link_validation(args, links_df)
    print(json.dumps(payload, indent=2, default=str))


def cmd_validate_government_contract_public_links(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    links_df = pd.read_csv(args.links)
    payload = _run_government_contract_public_link_validation(args, links_df)
    print(json.dumps(payload, indent=2, default=str))


def cmd_validate_government_contract_parser(args: argparse.Namespace) -> None:
    facts_df = __import__("pandas").read_csv(args.facts)
    gold_df = __import__("pandas").read_csv(args.gold)
    errors, report = validate_government_contract_parser(facts_df, gold_df, out_errors=args.errors_out)
    report_path = write_government_contract_parser_audit_report(report, errors, args.report_out)
    print(json.dumps({"report": str(report_path), "errors": str(args.errors_out), **report}, indent=2, default=str))


def cmd_enrich_government_contract_context(args: argparse.Namespace) -> None:
    df = enrich_government_contract_context(
        args.events,
        args.prices_dir,
        args.out,
        benchmark_ticker=args.benchmark,
        market_caps_path=args.market_caps,
        revenue_path=args.revenue,
    )
    status_counts = df["government_contract_context_status"].value_counts(dropna=False).to_dict() if "government_contract_context_status" in df.columns else {}
    payload = {
        "rows": int(len(df)),
        "out": str(args.out),
        "status_counts": status_counts,
        "rows_with_award_amount_pct_market_cap": int(df["award_amount_pct_market_cap"].notna().sum()) if "award_amount_pct_market_cap" in df.columns else 0,
        "rows_with_obligated_amount_pct_market_cap": int(df["obligated_amount_pct_market_cap"].notna().sum()) if "obligated_amount_pct_market_cap" in df.columns else 0,
        "warning": "Government-contract context enrichment is feature preparation only; review rows before modeling.",
    }
    print(json.dumps(payload, indent=2, default=str))


def cmd_government_contract_readiness_report(args: argparse.Namespace) -> None:
    summary = write_government_contract_readiness_report(
        args.events,
        args.out,
        source_documents_path=args.source_documents,
        min_train=args.min_train,
        parser_errors_path=args.parser_errors,
    )
    print(json.dumps({"report": str(args.out), **summary}, indent=2, default=str))


def cmd_activist_13d_source_docs(args: argparse.Namespace) -> None:
    tickers, benchmark, sector_benchmark = resolve_tickers_and_sector(args)
    client = SecClient(user_agent=args.user_agent, requests_per_second=args.requests_per_second)
    forms = [v.strip().upper() for v in args.forms.split(",") if v.strip()]
    df, diag = build_activist_13d_sec_source_documents(
        client,
        tickers=tickers,
        out_manifest=args.out,
        docs_dir=args.docs_dir,
        start=args.start,
        end=args.end,
        forms=forms,
        limit_per_ticker=args.limit_per_ticker,
        sector_benchmark=sector_benchmark,
        overwrite=args.overwrite,
        min_text_chars=args.min_text_chars,
    )
    print(json.dumps({"provider": "sec-edgar", "rows": int(len(df)), "tickers": tickers, "benchmark": benchmark, "sector_benchmark": sector_benchmark, "out": str(args.out), "docs_dir": str(args.docs_dir), "diagnostics": diag.to_dict()}, indent=2, default=str))


def cmd_parse_activist_13d(args: argparse.Namespace) -> None:
    facts, features, events = parse_activist_13d_manifest(
        args.documents,
        args.facts_out,
        args.features_out,
        args.events_out,
        min_confidence=args.min_confidence,
        usable_confidence=args.usable_confidence,
    )
    print(json.dumps({"fact_rows": int(len(facts)), "feature_rows": int(len(features)), "event_rows": int(len(events)), "events_out": str(args.events_out)}, indent=2))


def cmd_validate_activist_13d_parser(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    errors, report = validate_activist_13d_parser(pd.read_csv(args.facts), pd.read_csv(args.gold), out_errors=args.errors_out)
    out = ensure_parent(args.report_out)
    lines = [
        "# Activist 13D Parser Audit Report",
        "",
        "This validates parser facts against a reviewed gold set. It is a parser-quality report, not a model result.",
        "",
        "## Metrics",
        "",
        f"- gold_rows: {report.get('gold_rows', 0)}",
        f"- correct_rows: {report.get('correct_rows', 0)}",
        f"- row_accuracy: {report.get('row_accuracy', 0):.3f}",
        f"- event_type_precision: {report.get('event_type_precision', 0):.3f}",
        f"- parser_audit_pass: {report.get('parser_audit_pass', False)}",
        f"- status: {report.get('status', 'unknown')}",
        "",
        "## Gates",
        "",
    ]
    for gate, passed in (report.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            lines.append(f"- {row['event_id']} / {row['fact_name']}: {row['status']} expected={row['expected_value']} actual={row['actual_value']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out), "errors": str(args.errors_out), **report}, indent=2, default=str))


def cmd_activist_13d_timestamp_audit(args: argparse.Namespace) -> None:
    pd = __import__("pandas")
    audited, summary = audit_activist_13d_timestamps_and_duplicates(pd.read_csv(args.events), out_path=args.out)
    print(json.dumps({"rows": int(len(audited)), "out": str(args.out), **summary}, indent=2, default=str))


def cmd_enrich_activist_13d_context(args: argparse.Namespace) -> None:
    enriched = enrich_activist_13d_context(
        args.events,
        args.prices_dir,
        args.out,
        benchmark_ticker=args.benchmark,
        market_caps_path=args.market_caps,
        prior_activity_path=args.prior_activity,
        liquidity_path=args.liquidity,
    )
    print(json.dumps({"rows": int(len(enriched)), "out": str(args.out)}, indent=2, default=str))


def cmd_activist_13d_readiness_report(args: argparse.Namespace) -> None:
    summary = write_activist_13d_readiness_report(
        args.events,
        args.out,
        min_train=args.min_train,
        source_documents_path=args.source_documents,
        parser_errors_path=args.parser_errors,
    )
    print(json.dumps({"report": str(args.out), **summary}, indent=2, default=str))


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


def cmd_cyber_8k_template(args: argparse.Namespace) -> None:
    path = write_cyber_8k_pipeline_template(
        args.out,
        source_documents_csv=args.source_documents_csv,
        out_dir=args.out_dir,
        tickers=args.tickers,
        start=args.start,
        end=args.end,
    )
    print(f"Wrote Cyber 8-K Watch pipeline template: {path}")


def cmd_cyber_8k_source_docs(args: argparse.Namespace) -> None:
    client = SecClient(args.user_agent, requests_per_second=args.requests_per_second)
    df, diagnostics = build_cyber_8k_source_documents(
        client,
        tickers=args.tickers,
        out_manifest=args.out,
        docs_dir=args.docs_dir,
        start=args.start,
        end=args.end,
        limit_per_ticker=args.limit_per_ticker,
        include_primary=not args.no_primary,
        include_exhibits=not args.no_exhibits,
        overwrite=args.overwrite,
        min_text_chars=args.min_text_chars,
    )
    print(f"Wrote {len(df)} Cyber 8-K source document row(s): {args.out}")
    print(json.dumps(diagnostics.to_dict(), indent=2, sort_keys=True))


def cmd_cyber_8k_parse(args: argparse.Namespace) -> None:
    claims, evidence, diagnostics = run_cyber_8k_parse_manifest(args.documents, claims_out=args.claims_out, evidence_out=args.evidence_out)
    print(f"Wrote {len(claims)} claim row(s) and {len(evidence)} evidence span row(s).")
    print(json.dumps(diagnostics, indent=2, sort_keys=True))


def cmd_cyber_8k_review_queue(args: argparse.Namespace) -> None:
    queue, diagnostics = make_claim_review_queue(
        args.claims,
        args.evidence_spans,
        out_path=args.out,
        auto_accept_min_confidence=args.auto_accept_min_confidence,
        require_evidence=not args.allow_missing_evidence,
    )
    print(f"Wrote {len(queue)} claim review row(s): {args.out}")
    print(json.dumps(diagnostics, indent=2, sort_keys=True))


def cmd_cyber_8k_build_dataset(args: argparse.Namespace) -> None:
    summary = build_cyber_8k_dataset(
        args.documents,
        claims_csv=args.claims,
        evidence_spans_csv=args.evidence_spans,
        review_queue_csv=args.review_queue,
        filings_csv=args.filings,
        out_dir=args.out_dir,
        run_manifest_path=args.run_manifest,
        auto_accept_min_confidence=args.auto_accept_min_confidence,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))


def cmd_cyber_8k_build_site(args: argparse.Namespace) -> None:
    result = build_cyber_8k_static_site(
        args.events,
        args.claims,
        args.evidence_spans,
        args.out_dir,
        title=args.title,
        source_documents_csv=args.source_documents,
        source_docs_dir=args.source_docs_dir,
        review_queue_csv=args.review_queue,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_cyber_8k_digest(args: argparse.Namespace) -> None:
    digest = build_cyber_8k_digest(
        args.events,
        args.claims,
        args.evidence_spans,
        start_date=args.start_date,
        end_date=args.end_date,
        out_path=args.out,
        title=args.title,
    )
    if args.out:
        print(f"Wrote Cyber 8-K digest: {args.out}")
    else:
        print(digest)


def cmd_cyber_8k_quality_report(args: argparse.Namespace) -> None:
    report = build_cyber_8k_quality_report(
        args.events,
        args.claims,
        args.evidence_spans,
        args.review_queue,
        out_json=args.out_json,
        out_md=args.out_md,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def cmd_cyber_8k_run(args: argparse.Namespace) -> None:
    report = run_cyber_8k_pipeline(args.config, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def cmd_generic_template(args: argparse.Namespace) -> None:
    path = write_generic_pipeline_template(
        args.out,
        out_dir=args.out_dir,
        adapter=args.adapter,
        auto_accept_min_confidence=args.auto_accept_min_confidence,
    )
    print(f"Wrote generic evidence pipeline template: {path}")


def cmd_generic_run(args: argparse.Namespace) -> None:
    report = run_generic_pipeline(args.config, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def cmd_generic_review_queue(args: argparse.Namespace) -> None:
    queue, diagnostics = make_generic_claim_review_queue(
        args.claims,
        args.evidence_spans,
        args.out,
        auto_accept_min_confidence=args.auto_accept_min_confidence,
        require_evidence=not args.allow_missing_evidence,
    )
    print(f"Wrote {len(queue)} generic claim review row(s): {args.out}")
    print(json.dumps(diagnostics, indent=2, sort_keys=True, default=str))


def _read_optional_csv(path: str | None):
    if not path:
        return None
    import pandas as pd

    return pd.read_csv(path)


def cmd_generic_quality_report(args: argparse.Namespace) -> None:
    import pandas as pd

    report = build_generic_quality_report(
        events=_read_optional_csv(args.events),
        claims=pd.read_csv(args.claims),
        evidence_spans=pd.read_csv(args.evidence_spans),
        review_queue=_read_optional_csv(args.review_queue),
        out_json=args.out_json,
        out_md=args.out_md,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def cmd_generic_build_site(args: argparse.Namespace) -> None:
    import pandas as pd

    result = build_generic_static_site(
        events=_read_optional_csv(args.events),
        claims=pd.read_csv(args.claims),
        evidence_spans=pd.read_csv(args.evidence_spans),
        review_queue=_read_optional_csv(args.review_queue),
        out_dir=args.out_dir,
        title=args.title,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


def cmd_generic_api_export(args: argparse.Namespace) -> None:
    import pandas as pd

    result = export_generic_api(
        events=_read_optional_csv(args.events),
        claims=pd.read_csv(args.claims),
        evidence_spans=pd.read_csv(args.evidence_spans),
        review_queue=_read_optional_csv(args.review_queue),
        out_dir=args.out_dir,
        include_evidence=not args.omit_evidence,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


def cmd_generic_digest(args: argparse.Namespace) -> None:
    import pandas as pd

    digest = build_generic_digest(
        events=_read_optional_csv(args.events),
        claims=pd.read_csv(args.claims),
        evidence_spans=pd.read_csv(args.evidence_spans),
        review_queue=_read_optional_csv(args.review_queue),
        out_path=args.out,
        title=args.title,
    )
    if args.out:
        print(f"Wrote generic digest: {args.out}")
    else:
        print(digest)
