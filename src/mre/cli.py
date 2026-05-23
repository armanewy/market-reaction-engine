from __future__ import annotations

import argparse
import json
from pathlib import Path

from .demo import generate_demo_data
from .earnings import build_alpha_vantage_earnings_corpus, build_earnings_corpus_from_sec, build_yfinance_earnings_corpus, write_manual_earnings_template
from .earnings_demo import generate_earnings_demo_data
from .event_study import run_event_study
from .events import event_tickers, load_events, make_event_template
from .expectations import enrich_expectations, make_expectations_template, merge_external_expectations
from .modeling import find_analogs, predict_direction, train_direction_model, walk_forward_direction_model
from .paths import ensure_parent
from .prices import fetch_yfinance_prices
from .reports import event_study_report
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mre",
        description="Market Reaction Engine: event-study workbench for abnormal market reactions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

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
