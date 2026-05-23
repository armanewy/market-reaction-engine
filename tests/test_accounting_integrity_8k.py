from __future__ import annotations

import pandas as pd

from mre.accounting_integrity_8k import (
    accounting_integrity_readiness_summary,
    audit_accounting_integrity_timestamps_and_duplicates,
    build_accounting_integrity_parser_gold_template,
    classify_accounting_integrity_execution_survivability,
    enrich_accounting_integrity_context,
    parse_accounting_integrity_manifest,
    validate_accounting_integrity_parser,
)
from mre.corpus import normalize_domain


def _source_row(**overrides):
    row = {
        "source_doc_id": "acme_402_doc",
        "ticker": "ACME",
        "event_id": "ACME_2024_402",
        "event_time": "2024-06-18T16:10:00",
        "event_type": "accounting_integrity",
        "event_subtype": "sec_8k_item_4",
        "release_session": "after_close",
        "source_type": "sec_8k",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/test.htm",
        "title": "Item 4.02 Non-Reliance",
        "path": "",
        "text": (
            "Item 4.02 Non-Reliance on Previously Issued Financial Statements. "
            "The audit committee concluded that the financial statements for the fiscal year ended December 31, 2023 "
            "should no longer be relied upon due to an error in revenue recognition and a material weakness in internal control."
        ),
        "fiscal_period_end": "",
        "sector_benchmark": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def test_domain_alias_registered():
    assert normalize_domain("accounting integrity") == "accounting_integrity_8k"
    assert normalize_domain("non-reliance") == "accounting_integrity_8k"


def test_parse_non_reliance_402_as_high_severity_immediate_gap(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame([_source_row()]).to_csv(manifest, index=False)

    facts, features, events = parse_accounting_integrity_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    by_name = {row["fact_name"]: row["value"] for _, row in facts.iterrows()}
    assert by_name["accounting_integrity_event_type"] == "non_reliance_financial_statements"
    assert by_name["non_reliance_flag"] == True
    assert features.loc[0, "severity_pre_price"] == "high"
    assert features.loc[0, "execution_survivability_class"] == "immediate-gap"
    assert events.loc[0, "surprise_direction"] == "negative"


def test_routine_auditor_dismissal_without_disagreement_is_explanation_only(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            _source_row(
                event_id="ACME_2024_401",
                event_time="2024-07-01T08:05:00",
                release_session="before_open",
                title="Item 4.01 Auditor Change",
                text=(
                    "Item 4.01 Changes in Registrant's Certifying Accountant. "
                    "The company dismissed Old & Co. and appointed New LLP as its independent registered public accounting firm. "
                    "During the two most recent fiscal years there were no disagreements with Old & Co. on any matter of accounting principles or practices."
                ),
            )
        ]
    ).to_csv(manifest, index=False)

    _, features, events = parse_accounting_integrity_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    assert features.loc[0, "accounting_integrity_event_type"] == "routine_auditor_change"
    assert features.loc[0, "hard_negative_flag"] == True
    assert features.loc[0, "severity_pre_price"] == "low"
    assert features.loc[0, "execution_survivability_class"] == "explanation-only"
    assert events.loc[0, "surprise_direction"] == "neutral"


def test_validate_parser_rejects_unreviewed_gold_template(tmp_path):
    features = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "ACME",
                "accounting_integrity_event_type": "non_reliance_financial_statements",
                "item_number": "4.02",
                "non_reliance_flag": True,
                "auditor_change_type": "none",
                "disagreement_flag": False,
                "reportable_event_flag": False,
                "auditor_letter_present": False,
                "auditor_letter_agrees": False,
                "severity_pre_price": "high",
            }
        ]
    )
    gold = build_accounting_integrity_parser_gold_template(features, tmp_path / "gold.csv", target_events=1)
    facts = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "fact_name": "accounting_integrity_event_type",
                "value": "non_reliance_financial_statements",
                "confidence": 0.9,
            }
        ]
    )

    errors, report = validate_accounting_integrity_parser(facts, gold)

    assert report["status"] == "gold_set_requires_human_review"
    assert report["parser_audit_pass"] is False
    assert set(errors["status"]) == {"gold_not_reviewed"}


def test_context_enrichment_adds_market_context_and_execution_class(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "ACME",
                "event_time": "2024-03-29T16:05:00",
                "release_session": "after_close",
                "accounting_integrity_event_type": "non_reliance_financial_statements",
                "severity_pre_price": "high",
                "non_reliance_flag": True,
                "disagreement_flag": False,
                "reportable_event_flag": False,
                "hard_negative_flag": False,
                "prior_auditor": "Deloitte & Touche LLP",
                "new_auditor": "",
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    acme_prices = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 70,
            "high": [10.0] * 70,
            "low": [10.0] * 70,
            "close": [10.0 + i * 0.1 for i in range(70)],
            "adj_close": [10.0 + i * 0.1 for i in range(70)],
            "volume": [1000] * 70,
        }
    )
    spy_prices = acme_prices.copy()
    spy_prices["close"] = 10.0
    spy_prices["adj_close"] = 10.0
    acme_prices.to_csv(prices_dir / "ACME.csv", index=False)
    spy_prices.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "ACME", "asof_date": "2024-03-01", "market_cap_before_event": 1_000_000_000}]).to_csv(tmp_path / "market_caps.csv", index=False)

    enriched = enrich_accounting_integrity_context(
        events_path,
        prices_dir,
        tmp_path / "enriched.csv",
        market_caps_path=tmp_path / "market_caps.csv",
    )

    assert enriched.loc[0, "market_cap_before_event"] == 1_000_000_000
    assert enriched.loc[0, "company_size_bucket"] == "small_cap"
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])
    assert pd.notna(enriched.loc[0, "pre_event_volatility_20d"])
    assert enriched.loc[0, "auditor_big4_flag"] == True
    assert enriched.loc[0, "execution_survivability_class"] == "immediate-gap"


def test_timestamp_duplicate_audit_marks_duplicate():
    events = pd.DataFrame(
        [
            {"event_id": "E1", "ticker": "ACME", "event_time": "2024-01-02T16:10:00", "release_session": "after_close", "item_number": "4.02", "affected_periods": "2023"},
            {"event_id": "E2", "ticker": "ACME", "event_time": "2024-01-02T16:20:00", "release_session": "after_close", "item_number": "4.02", "affected_periods": "2023"},
        ]
    )
    audit, summary = audit_accounting_integrity_timestamps_and_duplicates(events)
    assert summary["duplicates"] == 1
    assert audit.loc[1, "duplicate_status"] == "duplicate"


def test_readiness_requires_execution_survivability_before_model_ready():
    rows = []
    for i in range(80):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "review_status": "reviewed",
                "release_session": "after_close",
                "severity_pre_price": "high" if i < 55 else "medium",
                "non_reliance_flag": i < 35,
                "auditor_change_type": "resignation" if 35 <= i < 55 else "none",
                "disagreement_flag": False,
                "reportable_event_flag": False,
                "market_cap_before_event": 1_000_000_000,
                "pre_event_market_adjusted_return_20d": 0.01,
                "pre_event_volatility_20d": 0.03,
                "execution_survivability_class": "immediate-gap",
            }
        )
    events = pd.DataFrame(rows)
    source_documents = pd.DataFrame({"source_doc_id": [f"D{i}" for i in range(100)]})
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    timestamp_audit = pd.DataFrame({"timestamp_status": ["clear"] * 80, "duplicate_status": ["primary"] * 80})

    blocked = accounting_integrity_readiness_summary(
        events,
        source_documents=source_documents,
        parser_errors=parser_errors,
        timestamp_audit=timestamp_audit,
    )
    assert blocked["decision"] == "execution survivability insufficient"
    assert blocked["gates"]["next_open_and_stress_ready_before_tradeability"] is False

    events["next_open_return"] = -0.02
    events["close_to_close_return"] = -0.03
    events["next_open_return_stress_25bps"] = -0.0225
    events["next_open_return_stress_50bps"] = -0.025
    events["next_open_return_stress_100bps"] = -0.03
    ready = accounting_integrity_readiness_summary(
        events,
        source_documents=source_documents,
        parser_errors=parser_errors,
        timestamp_audit=timestamp_audit,
    )
    assert ready["decision"] == "model-ready"
    assert ready["gates"]["next_open_and_stress_ready_before_tradeability"] is True


def test_execution_classifier_explains_delayed_digestion():
    result = classify_accounting_integrity_execution_survivability(
        {
            "accounting_integrity_event_type": "restatement_warning",
            "severity_pre_price": "medium",
            "release_session": "intraday",
            "non_reliance_flag": True,
        }
    )
    assert result["execution_survivability_class"] == "delayed-digestion"
    assert result["next_open_required_flag"] is True
