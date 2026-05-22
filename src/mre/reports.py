from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import ensure_parent


def _fmt_pct(x: float | int | None) -> str:
    if pd.isna(x):
        return "n/a"
    return f"{100 * float(x):.2f}%"


def event_study_report(event_study_path: str | Path, out_path: str | Path, horizon: int = 1) -> str:
    df = pd.read_csv(event_study_path)
    car_col = f"car_market_model_h{horizon}"
    z_col = f"z_h{horizon}"
    sig_col = f"significant_95_h{horizon}"
    ok = df[df.get("event_status", "ok") == "ok"].copy()

    lines: list[str] = []
    lines.append("# Market Reaction Engine Report")
    lines.append("")
    lines.append("This report measures event-window abnormal returns. It is not investment advice and does not prove predictive edge.")
    lines.append("")
    lines.append("## Coverage")
    lines.append(f"- Total event rows: {len(df)}")
    lines.append(f"- Usable event rows: {len(ok)}")
    if len(df) != len(ok) and "skip_reason" in df.columns:
        skips = df[df.get("event_status") != "ok"]["skip_reason"].value_counts().head(10)
        lines.append("- Top skip reasons:")
        for reason, count in skips.items():
            lines.append(f"  - {reason}: {count}")
    lines.append("")

    if ok.empty or car_col not in ok.columns:
        lines.append("No usable events or missing CAR column.")
        text = "\n".join(lines)
        ensure_parent(out_path).write_text(text)
        return text

    lines.append(f"## Event-type base rates, horizon={horizon} trading day(s)")
    grouped = ok.groupby("event_type").agg(
        n=("event_id", "count"),
        mean_car=(car_col, "mean"),
        median_car=(car_col, "median"),
        mean_abs_z=(z_col, lambda s: s.abs().mean()),
        significant_rate=(sig_col, "mean"),
    )
    grouped = grouped.sort_values("n", ascending=False)
    lines.append("| event_type | n | mean CAR | median CAR | mean abs z | significant rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for event_type, r in grouped.iterrows():
        lines.append(
            f"| {event_type} | {int(r['n'])} | {_fmt_pct(r['mean_car'])} | {_fmt_pct(r['median_car'])} | "
            f"{float(r['mean_abs_z']):.2f} | {_fmt_pct(r['significant_rate'])} |"
        )
    lines.append("")

    lines.append("## Largest absolute abnormal reactions")
    top = ok.assign(abs_car=ok[car_col].abs()).sort_values("abs_car", ascending=False).head(10)
    lines.append("| event_id | ticker | reaction_start | event_type | CAR | z | summary |")
    lines.append("|---|---|---|---|---:|---:|---|")
    for _, r in top.iterrows():
        summary = str(r.get("summary", "")).replace("|", " ")[:160]
        lines.append(
            f"| {r.get('event_id')} | {r.get('ticker')} | {r.get('reaction_start')} | {r.get('event_type')} | "
            f"{_fmt_pct(r.get(car_col))} | {float(r.get(z_col, 0)):.2f} | {summary} |"
        )
    lines.append("")
    lines.append("## Interpretation guardrails")
    lines.append("- Positive backtest metrics are not evidence of tradable alpha unless they survive walk-forward validation, transaction costs, and pre-registered feature definitions.")
    lines.append("- Event labels must be created without looking at the price reaction.")
    lines.append("- yfinance/demo data is acceptable for plumbing; serious research needs point-in-time data and corporate-action hygiene.")

    text = "\n".join(lines)
    ensure_parent(out_path).write_text(text)
    return text
