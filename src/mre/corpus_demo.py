from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .corpus import build_curated_corpus
from .expectations import apply_expectations_to_events
from .options import merge_options_implied_moves
from .paths import ensure_dir
from .prices import PRICE_COLUMNS

DEMO_TICKERS = ["PHAR", "MEDI", "TECH", "AUTO"]
DEMO_BENCHMARKS = ["SPY", "XBI", "XLK", "CARZ"]
DOMAIN_SEQUENCE = ["earnings_guidance", "fda_biotech", "regulatory_legal", "cyber_incident", "recall_safety"]


def _write_price_csv(prices_dir: Path, ticker: str, dates: pd.DatetimeIndex, log_returns: np.ndarray, *, seed_price: float = 100.0) -> None:
    adj = seed_price * np.exp(np.cumsum(log_returns))
    df = pd.DataFrame(
        {
            "date": dates,
            "open": adj * 0.995,
            "high": adj * 1.01,
            "low": adj * 0.99,
            "close": adj,
            "adj_close": adj,
            "volume": 1_000_000,
        },
        columns=PRICE_COLUMNS,
    )
    df.to_csv(prices_dir / f"{ticker}.csv", index=False)


def generate_corpus_demo_data(root: str | Path, seed: int = 11) -> dict[str, Path]:
    """Generate a synthetic multi-domain corpus and price data.

    This is an offline demo for M6/M7 plumbing.  Synthetic price shocks are
    deliberately tied to curated, point-in-time event features so the event-study
    and backtest harness can be verified without relying on live data.
    """
    rng = np.random.default_rng(seed)
    root = Path(root)
    prices_dir = ensure_dir(root / "prices")
    events_raw = root / "multi_domain_events_raw.csv"
    curated_path = root / "multi_domain_curated_corpus.csv"
    expectations_path = root / "multi_domain_expectations.csv"
    options_path = root / "multi_domain_options.csv"
    options_enriched_path = root / "multi_domain_events_options.csv"
    events_enriched = root / "multi_domain_events_enriched.csv"
    validation_path = root / "multi_domain_corpus_validated.csv"

    dates = pd.bdate_range("2018-01-02", "2025-03-31")
    n = len(dates)
    spy = rng.normal(0.00015, 0.009, n)
    xbi = 0.00005 + 1.10 * spy + rng.normal(0, 0.012, n)
    xlk = 0.00012 + 1.05 * spy + rng.normal(0, 0.007, n)
    carz = 0.00006 + 1.00 * spy + rng.normal(0, 0.010, n)
    logs = {"SPY": spy, "XBI": xbi, "XLK": xlk, "CARZ": carz}
    ticker_sector = {"PHAR": "XBI", "MEDI": "XBI", "TECH": "XLK", "AUTO": "CARZ"}
    for i, ticker in enumerate(DEMO_TICKERS):
        sector = logs[ticker_sector[ticker]]
        logs[ticker] = 0.00005 + 0.55 * spy + 0.55 * sector + rng.normal(0, 0.014 + 0.002 * i, n)

    rows: list[dict[str, object]] = []
    expectation_rows: list[dict[str, object]] = []
    option_rows: list[dict[str, object]] = []
    event_dates = pd.bdate_range("2018-07-02", "2024-12-20", freq="21B")
    for idx, d in enumerate(event_dates):
        ticker = DEMO_TICKERS[idx % len(DEMO_TICKERS)]
        family = DOMAIN_SEQUENCE[idx % len(DOMAIN_SEQUENCE)]
        session = "after_close" if idx % 3 == 0 else "before_open"
        event_time = pd.Timestamp(d) + (pd.Timedelta(hours=16, minutes=15) if session == "after_close" else pd.Timedelta(hours=8, minutes=30))
        reaction_pos = dates.searchsorted(pd.Timestamp(d), side="right" if session == "after_close" else "left")
        if reaction_pos >= len(dates):
            continue
        event_id = f"multi_{idx+1:04d}_{ticker}_{family}"
        base = {
            "event_id": event_id,
            "ticker": ticker,
            "event_time": event_time.isoformat(),
            "event_type": "earnings" if family == "earnings_guidance" else ("recall" if family == "recall_safety" else "regulatory" if family in {"fda_biotech", "regulatory_legal"} else "cybersecurity"),
            "event_subtype": family,
            "event_family": family,
            "summary": f"Synthetic {family} event for {ticker}.",
            "source_type": "synthetic_demo",
            "source_url": f"synthetic://{event_id}",
            "release_session": session,
            "expectedness": "surprise" if idx % 4 else "partial_surprise",
            "surprise_direction": "unknown",
            "surprise_magnitude": "unknown",
            "materiality": float(np.clip(rng.normal(0.62, 0.18), 0.10, 1.0)),
            "sector_benchmark": ticker_sector[ticker],
            "notes": "Synthetic multi-domain corpus row. Do not use for financial conclusions.",
            "corpus_name": "synthetic_multi_domain_v1",
            "review_status": "reviewed",
            "label_quality": "high",
            "source_doc_ids": f"doc_{event_id}",
            "evidence_status": "verified",
        }
        direction = rng.choice([-1, 1])
        surprise_strength = float(np.clip(abs(rng.normal(0.0, 0.75)), 0.10, 1.75))
        shock_scale = 0.018
        if family == "earnings_guidance":
            eps_surprise_pct = direction * rng.uniform(0.015, 0.12)
            revenue_surprise_pct = direction * rng.uniform(0.005, 0.07)
            guidance_surprise_pct = direction * rng.uniform(0.01, 0.10)
            base.update(
                {
                    "primary_surprise_metric": "guidance_revenue_surprise_pct",
                    "consensus_eps": 1.0 + idx * 0.005,
                    "actual_eps": (1.0 + idx * 0.005) * (1 + eps_surprise_pct),
                    "eps_surprise_pct": eps_surprise_pct,
                    "consensus_revenue": 1000 + idx * 8,
                    "actual_revenue": (1000 + idx * 8) * (1 + revenue_surprise_pct),
                    "revenue_surprise_pct": revenue_surprise_pct,
                    "consensus_forward_revenue": 1020 + idx * 8,
                    "guidance_revenue_mid": (1020 + idx * 8) * (1 + guidance_surprise_pct),
                    "guidance_revenue_surprise_pct": guidance_surprise_pct,
                    "implied_move_pct": rng.uniform(0.03, 0.09),
                    "analyst_count": int(rng.integers(6, 24)),
                }
            )
            shock = direction * shock_scale * surprise_strength * base["materiality"] + rng.normal(0, 0.006)
            expectation_rows.append({k: base.get(k, "") for k in ["event_id", "ticker", "event_time", "consensus_eps", "actual_eps", "eps_surprise_pct", "consensus_revenue", "actual_revenue", "revenue_surprise_pct", "consensus_forward_revenue", "guidance_revenue_mid", "guidance_revenue_surprise_pct", "implied_move_pct", "analyst_count"]})
        elif family == "fda_biotech":
            success = bool(direction > 0)
            base.update(
                {
                    "agency": "FDA",
                    "drug_or_device": f"Therapy-{idx % 7}",
                    "indication": "oncology",
                    "trial_phase": rng.choice(["phase_2", "phase_3", "pdufa"]),
                    "trial_result": "positive" if success else "negative",
                    "primary_endpoint_met": success,
                    "secondary_endpoint_signal": "supportive" if success else "mixed",
                    "safety_signal": "clean" if success else rng.choice(["imbalance", "adverse_events"]),
                    "pdufa_decision": "approved" if success and idx % 3 == 0 else "not_applicable",
                    "approval_status": "approved" if success and idx % 3 == 0 else ("rejected" if not success and idx % 3 == 0 else "pending"),
                    "market_size_estimate": float(rng.uniform(500, 5500)),
                    "pipeline_concentration_pct": float(rng.uniform(0.25, 0.90)),
                    "cash_runway_months": float(rng.uniform(6, 36)),
                    "prior_probability": float(rng.uniform(0.25, 0.70)),
                }
            )
            shock = direction * 0.032 * surprise_strength * base["materiality"] * base["pipeline_concentration_pct"] + rng.normal(0, 0.008)
        elif family == "regulatory_legal":
            severity = float(rng.uniform(0.2, 1.0))
            base.update(
                {
                    "agency": rng.choice(["FTC", "DOJ", "EU Commission", "SEC"]),
                    "jurisdiction": rng.choice(["US", "EU", "UK"]),
                    "action_type": rng.choice(["investigation", "complaint", "settlement", "fine"]),
                    "case_or_docket_id": f"CASE-{idx:05d}",
                    "affected_business_line": rng.choice(["ads", "cloud", "payments", "marketplace"]),
                    "fine_or_penalty_amount": float(severity * rng.uniform(50, 2000)),
                    "remedy_risk": "high" if severity > 0.7 else "medium",
                    "injunction_risk": bool(severity > 0.75),
                    "novelty": "new" if idx % 3 else "known_update",
                    "appeal_status": "not_applicable",
                    "expected_resolution_window": "multi_quarter",
                }
            )
            shock = -0.020 * severity * surprise_strength * base["materiality"] + rng.normal(0, 0.006)
            direction = -1
        elif family == "cyber_incident":
            severity = float(rng.uniform(0.2, 1.0))
            base.update(
                {
                    "incident_type": rng.choice(["breach", "ransomware", "outage"]),
                    "breach_confirmed": bool(severity > 0.35),
                    "systems_affected": rng.choice(["corporate", "customer_portal", "production", "unknown"]),
                    "customer_data_exposed": bool(severity > 0.55),
                    "ransomware": bool(severity > 0.65),
                    "operational_disruption": bool(severity > 0.45),
                    "disclosure_delay_days": int(rng.integers(0, 30)),
                    "estimated_cost": float(severity * rng.uniform(10, 600)),
                    "insurance_coverage_known": bool(idx % 4 == 0),
                    "regulatory_notification_required": bool(severity > 0.50),
                    "severity_score": severity,
                }
            )
            shock = -0.018 * severity * surprise_strength * base["materiality"] + rng.normal(0, 0.006)
            direction = -1
        else:
            severity = float(rng.uniform(0.2, 1.0))
            base.update(
                {
                    "agency": rng.choice(["NHTSA", "CPSC", "FDA"]),
                    "product_or_model": f"Model-{idx % 8}",
                    "recall_class": rng.choice(["class_i", "class_ii", "safety_recall"]),
                    "recall_units": int(severity * rng.uniform(5_000, 1_000_000)),
                    "safety_risk": "high" if severity > 0.65 else "medium",
                    "injuries_or_deaths_reported": bool(severity > 0.75),
                    "remedy_available": bool(severity < 0.75),
                    "estimated_cost": float(severity * rng.uniform(20, 900)),
                    "affected_revenue_pct": float(severity * rng.uniform(0.005, 0.08)),
                    "production_halt": bool(severity > 0.80),
                    "geography": rng.choice(["US", "global", "EU"]),
                }
            )
            shock = -0.022 * severity * surprise_strength * base["materiality"] + rng.normal(0, 0.006)
            direction = -1
        base["surprise_direction"] = "positive" if direction > 0 else "negative"
        base["surprise_magnitude"] = "high" if abs(shock) > 0.025 else "medium" if abs(shock) > 0.012 else "low"
        rows.append(base)
        logs[ticker][reaction_pos] += shock
        if reaction_pos + 1 < n:
            logs[ticker][reaction_pos + 1] += 0.20 * shock + rng.normal(0, 0.003)
        underlying = 50 + idx * 0.25
        implied = float(np.clip(abs(shock) * rng.uniform(1.5, 2.7) + 0.025, 0.015, 0.15))
        call_mid = implied * underlying * rng.uniform(0.45, 0.55)
        option_rows.append(
            {
                "event_id": event_id,
                "ticker": ticker,
                "quote_time": (event_time - pd.Timedelta(minutes=25)).isoformat(),
                "expiration": (pd.Timestamp(d) + pd.Timedelta(days=5)).date().isoformat(),
                "underlying_price": underlying,
                "strike": round(underlying / 5) * 5,
                "call_mid": call_mid,
                "put_mid": implied * underlying - call_mid,
                "option_source_type": "synthetic_demo",
            }
        )

    events = pd.DataFrame(rows)
    events.to_csv(events_raw, index=False)
    curated, _ = build_curated_corpus([events_raw], curated_path, corpus_name="synthetic_multi_domain_v1", min_materiality=0.0)
    pd.DataFrame(expectation_rows).to_csv(expectations_path, index=False)
    if not pd.DataFrame(expectation_rows).empty:
        apply_expectations_to_events(curated_path, expectations_path, events_enriched, fill_labels=False)
    else:
        curated.to_csv(events_enriched, index=False)
    pd.DataFrame(option_rows).to_csv(options_path, index=False)
    merged_options, _ = merge_options_implied_moves(events_enriched, options_path, options_enriched_path, max_quote_age_days=14)
    merged_options.to_csv(events_enriched, index=False)

    for ticker, log_values in logs.items():
        _write_price_csv(prices_dir, ticker, dates, log_values, seed_price=100 + len(ticker))

    # Validate after the final enriched version is written.
    from .corpus import validate_corpus_csv

    validate_corpus_csv(events_enriched, validation_path)
    return {
        "events_raw": events_raw,
        "curated_corpus": curated_path,
        "expectations": expectations_path,
        "options": options_path,
        "events_enriched": events_enriched,
        "validation": validation_path,
        "prices_dir": prices_dir,
    }
