from __future__ import annotations

import argparse
import json
from pathlib import Path

from .demo import generate_demo_data
from .event_study import run_event_study
from .events import event_tickers, load_events, make_event_template
from .modeling import find_analogs, predict_direction, train_direction_model
from .paths import ensure_parent
from .prices import fetch_yfinance_prices
from .reports import event_study_report
from .sec import SecClient, filings_to_event_template


def comma_ints(value: str) -> tuple[int, ...]:
    return tuple(int(v.strip()) for v in value.split(",") if v.strip())


def cmd_make_template(args: argparse.Namespace) -> None:
    make_event_template(args.out)
    print(f"Wrote event template: {args.out}")


def cmd_init_demo(args: argparse.Namespace) -> None:
    paths = generate_demo_data(args.out, seed=args.seed)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


def cmd_fetch_prices(args: argparse.Namespace) -> None:
    tickers = args.tickers
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mre",
        description="Market Reaction Engine: event-study workbench for abnormal market reactions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("make-template", help="Create an empty event CSV template.")
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

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
