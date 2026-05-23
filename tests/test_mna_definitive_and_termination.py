from __future__ import annotations

import pandas as pd

from mre.corpus import normalize_domain
from mre.mna_definitive_and_termination import (
    MnaSourceDocument,
    audit_mna_timestamps_and_duplicates,
    classify_execution_survivability,
    enrich_mna_context,
    execution_survivability_summary,
    mna_readiness_summary,
    parse_mna_document,
    parse_mna_manifest,
    validate_mna_parser,
    write_mna_final_report,
)


def _doc(text: str, **overrides) -> MnaSourceDocument:
    row = {
        "source_doc_id": "mna_doc",
        "ticker": "TGT",
        "event_id": "TGT_mna_2024",
        "event_time": pd.Timestamp("2024-01-02 08:30:00"),
        "event_type": "corporate_action",
        "event_subtype": "mna_candidate",
        "release_session": "before_open",
        "source_type": "sec_8k",
        "source_url": "https://sec.test/8k.htm",
        "title": "TGT enters definitive merger agreement",
        "text": text,
        "target_ticker": "TGT",
        "acquirer_ticker": "ACQ",
        "target_or_acquirer_role": "target",
    }
    row.update(overrides)
    return MnaSourceDocument(**row)


def _by_name(facts):
    return {fact.fact_name: fact for fact in facts}


def test_corpus_alias_registers_mna_domain():
    assert normalize_domain("mna") == "mna_definitive_and_termination"
    assert normalize_domain("deal-breaks") == "mna_definitive_and_termination"


def test_parse_definitive_merger_agreement_terms():
    facts = parse_mna_document(
        _doc(
            "TargetCo entered into an Agreement and Plan of Merger under which ACQ will acquire "
            "all outstanding shares for $42.00 in cash per share. The transaction is valued at "
            "approximately $2.4 billion and represents a premium of 35% to the prior close. "
            "The transaction is subject to regulatory approvals under the HSR Act."
        )
    )
    by_name = _by_name(facts)
    assert by_name["mna_event_type"].value == "definitive_merger_agreement"
    assert by_name["target_ticker"].value == "TGT"
    assert by_name["acquirer_ticker"].value == "ACQ"
    assert by_name["target_or_acquirer_role"].value == "target"
    assert by_name["payment_method_cash_stock_mixed"].value == "cash"
    assert by_name["deal_price_per_share"].value == 42.0
    assert by_name["deal_value"].value == 2_400_000_000
    assert by_name["premium_to_prior_close"].value == 0.35
    assert by_name["regulatory_approval_required"].value is True


def test_parse_hard_negative_licensing_and_nonbinding_loi():
    licensing = _by_name(
        parse_mna_document(
            _doc(
                "The company entered into a license agreement and commercial supply agreement for a product candidate.",
                target_ticker="",
                acquirer_ticker="",
                target_or_acquirer_role="unknown",
            )
        )
    )
    loi = _by_name(parse_mna_document(_doc("The parties signed a non-binding letter of intent to explore a possible acquisition.")))

    assert licensing["mna_event_type"].value == "ordinary_material_agreement_control"
    assert licensing["hard_negative_flag"].value is True
    assert licensing["hard_negative_reason"].value == "ordinary_commercial_agreement"
    assert loi["hard_negative_flag"].value is True
    assert loi["hard_negative_reason"].value == "nonbinding_loi"


def test_parse_regulatory_block_and_execution_classification():
    facts = parse_mna_document(
        _doc(
            "The merger agreement was terminated after the FTC blocked the transaction and the parties "
            "could not obtain antitrust approval.",
            title="TGT merger terminated after FTC block",
            event_subtype="deal_termination",
        )
    )
    by_name = _by_name(facts)
    assert by_name["mna_event_type"].value == "regulatory_block"
    assert by_name["termination_reason"].value == "regulatory_block"

    klass, reason, plausible = classify_execution_survivability(
        {"mna_event_type": "regulatory_block", "target_or_acquirer_role": "target", "termination_reason": "regulatory_block"}
    )
    assert klass == "delayed-digestion"
    assert "standalone value" in reason
    assert plausible is True


def test_parse_manifest_writes_events_and_rejects_hard_negative(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            {
                "source_doc_id": "TGT_doc",
                "ticker": "TGT",
                "event_id": "TGT_mna_2024",
                "event_time": "2024-01-02T08:30:00",
                "event_type": "corporate_action",
                "event_subtype": "mna_candidate",
                "release_session": "before_open",
                "source_type": "sec_8k",
                "source_url": "https://sec.test/8k.htm",
                "title": "TGT merger agreement",
                "text": "TGT entered into a definitive merger agreement to be acquired by ACQ for $20.00 in cash per share.",
                "target_ticker": "TGT",
                "acquirer_ticker": "ACQ",
                "target_or_acquirer_role": "target",
            },
            {
                "source_doc_id": "TGT_license_doc",
                "ticker": "TGT",
                "event_id": "TGT_license_2024",
                "event_time": "2024-01-03T08:30:00",
                "event_type": "corporate_action",
                "event_subtype": "mna_candidate",
                "release_session": "before_open",
                "source_type": "sec_8k",
                "source_url": "https://sec.test/8k2.htm",
                "title": "TGT license agreement",
                "text": "TGT entered into a license agreement and supply agreement.",
            },
        ]
    ).to_csv(manifest, index=False)

    _, features, events = parse_mna_manifest(manifest, tmp_path / "facts.csv", tmp_path / "features.csv", tmp_path / "events.csv")

    assert set(features["mna_event_type"]) == {"definitive_merger_agreement", "ordinary_material_agreement_control"}
    assert events.loc[events["event_id"].eq("TGT_mna_2024"), "ticker"].iloc[0] == "TGT"
    assert events.loc[events["event_id"].eq("TGT_license_2024"), "review_status"].iloc[0] == "rejected"


def test_timestamp_duplicate_audit_marks_primary_and_duplicate():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "TGT",
                "event_time": "2024-01-02T08:30:00",
                "release_session": "before_open",
                "target_ticker": "TGT",
                "acquirer_ticker": "ACQ",
                "mna_event_type": "definitive_merger_agreement",
                "deal_price_per_share": 20.0,
            },
            {
                "event_id": "E2",
                "ticker": "TGT",
                "event_time": "2024-01-02T08:31:00",
                "release_session": "before_open",
                "target_ticker": "TGT",
                "acquirer_ticker": "ACQ",
                "mna_event_type": "definitive_merger_agreement",
                "deal_price_per_share": 20.0,
            },
        ]
    )
    audited, summary = audit_mna_timestamps_and_duplicates(events)
    assert list(audited["duplicate_status"]) == ["primary", "duplicate"]
    assert audited["timestamp_suitable_flag"].all()
    assert summary["duplicate_rows"] == 1
    assert summary["gates"]["no_duplicate_events"] is False


def test_enrich_mna_context_computes_deal_value_scale_and_runup(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "TGT",
                "event_time": "2024-03-29T08:30:00",
                "release_session": "before_open",
                "target_ticker": "TGT",
                "acquirer_ticker": "ACQ",
                "deal_value": 500_000_000,
                "premium_to_prior_close": 0.25,
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    tgt = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 70,
            "high": [10.0] * 70,
            "low": [10.0] * 70,
            "close": [10.0 + i * 0.1 for i in range(70)],
            "adj_close": [10.0 + i * 0.1 for i in range(70)],
            "volume": [1000 + i for i in range(70)],
        }
    )
    spy = tgt.copy()
    spy["adj_close"] = 10.0
    spy["close"] = 10.0
    tgt.to_csv(prices_dir / "TGT.csv", index=False)
    spy.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "TGT", "asof_date": "2024-03-01", "market_cap_before_event": 1_000_000_000},
            {"ticker": "ACQ", "asof_date": "2024-03-01", "market_cap_before_event": 5_000_000_000},
        ]
    ).to_csv(tmp_path / "market_caps.csv", index=False)

    enriched = enrich_mna_context(events_path, prices_dir, tmp_path / "enriched.csv", market_caps_path=tmp_path / "market_caps.csv")

    assert enriched.loc[0, "target_market_cap_before_event"] == 1_000_000_000
    assert enriched.loc[0, "acquirer_market_cap_before_event"] == 5_000_000_000
    assert enriched.loc[0, "deal_value_pct_acquirer_market_cap"] == 0.1
    assert enriched.loc[0, "premium_pct"] == 25.0
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])
    assert pd.notna(enriched.loc[0, "liquidity"])


def test_validate_parser_and_readiness_stop_before_modeling_without_execution_gate(tmp_path):
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "mna_event_type", "value": "deal_termination", "confidence": 0.9},
            {"event_id": "E1", "fact_name": "hard_negative_flag", "value": False, "confidence": 0.9},
            {"event_id": "E1", "fact_name": "target_or_acquirer_role", "value": "target", "confidence": 0.9},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "mna_event_type", "expected_value": "deal_termination"},
            {"event_id": "E1", "fact_name": "hard_negative_flag", "expected_value": False},
            {"event_id": "E1", "fact_name": "target_or_acquirer_role", "expected_value": "target"},
        ]
    )
    errors, report = validate_mna_parser(facts, gold)
    assert report["correct_rows"] == 3
    assert report["parser_audit_pass"] is False

    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "event_time": f"2024-01-{(i % 20) + 1:02d}T08:30:00",
                "review_status": "reviewed",
                "release_session": "before_open",
                "mna_event_type": "deal_termination" if i < 35 else "definitive_merger_agreement",
                "target_or_acquirer_role": "target",
                "payment_method_cash_stock_mixed": "cash",
                "duplicate_status": "primary",
                "deal_value_pct_acquirer_market_cap": 0.1,
                "premium_pct": 30.0,
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 80})
    summary = mna_readiness_summary(pd.DataFrame(rows), parser_errors=parser_errors)
    assert summary["gates"]["parser_audit_pass"] is True
    assert summary["gates"]["execution_survivability_gate"] is False
    assert summary["decision"] == "execution survivability not established"

    report_path = write_mna_final_report(tmp_path / "mna_report.md", readiness=summary)
    text = report_path.read_text(encoding="utf-8")
    assert "Execution Survivability Gate" in text
    assert "25/50/100 bps" in text
    assert "No modeling is permitted" in text


def test_execution_survivability_gate_requires_next_open_and_stress():
    rows = []
    for i in range(45):
        rows.append(
            {
                "mna_event_type": "regulatory_block",
                "target_or_acquirer_role": "target",
                "termination_reason": "regulatory_block",
            }
        )
    no_execution = execution_survivability_summary(pd.DataFrame(rows))
    assert no_execution["gate_pass"] is False
    assert "next-open" in no_execution["reason"]

    with_execution = pd.DataFrame(rows).assign(
        next_open_abnormal_return=-0.02,
        close_to_close_abnormal_return=-0.03,
        stress_25bps_next_open=-0.0225,
        stress_50bps_next_open=-0.025,
        stress_100bps_next_open=-0.03,
    )
    summary = execution_survivability_summary(with_execution)
    assert summary["gate_pass"] is True
