from __future__ import annotations

import pandas as pd

from mre.corpus import normalize_domain
from mre.government_contracts import (
    build_government_contract_human_audit,
    build_government_contract_parser_gold_template,
    build_government_contract_public_announcement_candidates,
    build_government_contract_source_documents,
    enrich_government_contract_context,
    government_contract_mapping_audit,
    government_contract_readiness_summary,
    load_government_contract_documents,
    map_recipient_to_ticker,
    parse_government_contract_document,
    parse_government_contract_manifest,
    validate_government_contract_public_links,
    validate_government_contract_parser,
    write_government_contract_recipient_ticker_map,
)


def _source_row(**overrides):
    row = {
        "source_doc_id": "pltr_task_order_doc",
        "ticker": "PLTR",
        "event_id": "PLTR_task_order_2024",
        "event_time": "2024-06-18T12:00:00",
        "event_type": "government_contract",
        "event_subtype": "dod_contract_announcement",
        "release_session": "unknown",
        "source_type": "dod_contract_announcement",
        "source_url": "https://defense.gov/test-contracts",
        "title": "Army task order award",
        "path": "",
        "text": (
            "The Department of the Army awarded Palantir USG Inc. a $292.7 million task order "
            "for Maven Smart System prototype support, with $50 million obligated at award. "
            "Contract W911QX24D0012, task order W911QX24F0053. NAICS 541715. PSC AC35."
        ),
        "fiscal_period_end": "",
        "sector_benchmark": "",
        "notes": "",
        "recipient_name": "PALANTIR USG INC",
        "mapped_ticker": "PLTR",
        "parent_company_name": "Palantir Technologies Inc.",
        "subsidiary_name": "",
        "mapping_type": "exact",
        "recipient_mapping_confidence": 0.95,
        "agency": "Department of Defense",
        "sub_agency": "Department of the Army",
        "award_amount": 292_700_000,
        "obligated_amount": 50_000_000,
        "contract_ceiling": pd.NA,
        "award_type": "DELIVERY ORDER",
        "contract_type": "delivery order",
        "contract_number": "W911QX24D0012",
        "task_order_number": "W911QX24F0053",
        "modification_number": "",
        "period_of_performance_start": "2024-06-18",
        "period_of_performance_end": "2026-05-31",
        "product_or_service_description": "Maven Smart System prototype support",
        "naics_code": "541715",
        "psc_code": "AC35",
        "location": "",
        "prime_or_sub": "prime",
    }
    row.update(overrides)
    return row


def test_corpus_domain_and_mapping_template(tmp_path):
    assert normalize_domain("government-contracts") == "government_contract_awards"
    mapping = write_government_contract_recipient_ticker_map(tmp_path / "map.csv")
    mapped = map_recipient_to_ticker("SIKORSKY AIRCRAFT CORP", mapping)
    assert mapped["mapped_ticker"] == "LMT"
    assert mapped["mapping_type"] == "known_subsidiary"
    assert mapped["recipient_mapping_confidence"] >= 0.9
    assert "source_url" in mapping.columns


def test_parse_task_order_distinguishes_funded_amount(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame([_source_row()]).to_csv(manifest, index=False)
    doc = load_government_contract_documents(manifest)[0]
    facts = parse_government_contract_document(doc)
    by_name = {fact.fact_name: fact for fact in facts}

    assert by_name["government_contract_event_type"].value == "task_order_award"
    assert by_name["award_amount"].value == 292_700_000
    assert by_name["obligated_amount"].value == 50_000_000
    assert by_name["actual_funded_award_flag"].value is True
    assert by_name["ceiling_only_flag"].value is False
    assert by_name["new_work_flag"].value is True


def test_parse_idiq_ceiling_is_not_funded(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            _source_row(
                source_doc_id="ktos_idiq_doc",
                ticker="KTOS",
                event_id="KTOS_idiq_ceiling_2025",
                event_time="2025-01-10T12:00:00",
                title="IDIQ vehicle award",
                text=(
                    "The Air Force awarded Kratos Defense & Security Solutions an indefinite-delivery/"
                    "indefinite-quantity contract vehicle with a ceiling of $1.0 billion. "
                    "No funds are obligated at the time of award."
                ),
                recipient_name="KRATOS DEFENSE & SECURITY SOLUTIONS",
                mapped_ticker="KTOS",
                parent_company_name="Kratos Defense & Security Solutions, Inc.",
                award_amount=pd.NA,
                obligated_amount=pd.NA,
                contract_ceiling=1_000_000_000,
                award_type="INDEFINITE DELIVERY / INDEFINITE QUANTITY",
                contract_type="IDIQ",
                task_order_number="",
                product_or_service_description="IDIQ contract vehicle",
            )
        ]
    ).to_csv(manifest, index=False)

    _, features, events = parse_government_contract_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    assert features.loc[0, "government_contract_event_type"] == "idiq_vehicle_award"
    assert features.loc[0, "ceiling_only_flag"] == True
    assert features.loc[0, "actual_funded_award_flag"] == False
    assert features.loc[0, "contract_ceiling"] == 1_000_000_000
    assert events.loc[0, "government_contract_event_type"] == "idiq_vehicle_award"


def test_ambiguous_jv_mapping_does_not_emit_model_ticker(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            _source_row(
                source_doc_id="ula_doc",
                ticker="",
                event_id="ULA_award_2025",
                text="United Launch Alliance was awarded a $200 million production contract.",
                recipient_name="UNITED LAUNCH ALLIANCE",
                mapped_ticker="BA;LMT",
                parent_company_name="United Launch Alliance",
                mapping_type="ambiguous",
                recipient_mapping_confidence=0.45,
                award_amount=200_000_000,
                obligated_amount=200_000_000,
                contract_ceiling=pd.NA,
                award_type="DEFINITIVE CONTRACT",
                contract_type="definitive contract",
            )
        ]
    ).to_csv(manifest, index=False)

    _, features, events = parse_government_contract_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    assert features.loc[0, "model_eligible_candidate_flag"] == False
    assert features.loc[0, "recipient_mapping_confidence"] == 0.45
    assert pd.isna(events.loc[0, "ticker"]) or events.loc[0, "ticker"] == ""


def test_high_confidence_ineligible_mapping_type_is_not_model_eligible(tmp_path):
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            _source_row(
                source_doc_id="jv_doc",
                ticker="LMT",
                event_id="JV_award_2025",
                text="Example Defense JV was awarded a $50 million contract.",
                recipient_name="EXAMPLE DEFENSE JV",
                mapped_ticker="LMT",
                parent_company_name="Lockheed Martin Corporation",
                mapping_type="joint_venture",
                recipient_mapping_confidence=0.95,
                award_amount=50_000_000,
                obligated_amount=50_000_000,
            )
        ]
    ).to_csv(manifest, index=False)

    _, features, events = parse_government_contract_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )
    detail, summary = government_contract_mapping_audit(
        pd.read_csv(manifest),
        pd.DataFrame(
            [
                {
                    "recipient_name_pattern": "EXAMPLE DEFENSE JV",
                    "ticker": "LMT",
                    "public_company_name": "Lockheed Martin Corporation",
                    "subsidiary_name": "",
                    "mapping_type": "joint_venture",
                    "confidence": 0.95,
                    "source_url": "",
                    "notes": "JV needs event-specific support.",
                }
            ]
        ),
    )

    assert features.loc[0, "model_eligible_candidate_flag"] == False
    assert pd.isna(events.loc[0, "ticker"]) or events.loc[0, "ticker"] == ""
    assert detail.loc[0, "model_eligible_mapping_flag"] == False
    assert summary["model_eligible_recipients"] == 0


def test_validate_government_contract_parser_scores_gold_rows():
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "government_contract_event_type", "value": "task_order_award", "unit": "category", "confidence": 0.9, "evidence_text": "task order"},
            {"event_id": "E1", "fact_name": "mapped_ticker", "value": "PLTR", "unit": "text", "confidence": 0.9, "evidence_text": "recipient"},
            {"event_id": "E1", "fact_name": "obligated_amount", "value": 50_000_000, "unit": "usd", "confidence": 0.9, "evidence_text": "obligated"},
        ]
    )
    gold = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "government_contract_event_type", "expected_value": "task_order_award", "unit": "category"},
            {"event_id": "E1", "fact_name": "mapped_ticker", "expected_value": "PLTR", "unit": "text"},
            {"event_id": "E1", "fact_name": "obligated_amount", "expected_value": 50_000_000, "unit": "usd"},
        ]
    )
    errors, report = validate_government_contract_parser(facts, gold)
    assert report["correct_rows"] == 3
    assert set(errors["status"]) == {"ok"}
    assert report["audit_gate_results"]["gold_set_60_rows"] is False


def test_validate_government_contract_parser_rejects_unreviewed_gold_template(tmp_path):
    facts = pd.DataFrame(
        [
            {"event_id": "E1", "fact_name": "government_contract_event_type", "value": "task_order_award", "unit": "category", "confidence": 0.9, "evidence_text": "task order"},
            {"event_id": "E1", "fact_name": "mapped_ticker", "value": "PLTR", "unit": "text", "confidence": 0.9, "evidence_text": "recipient"},
        ]
    )
    features = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "government_contract_event_type": "task_order_award",
                "mapped_ticker": "PLTR",
                "recipient_mapping_confidence": 0.90,
                "award_amount": 100_000_000,
                "obligated_amount": 50_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "option_exercise_flag": False,
                "modification_flag": False,
                "new_work_flag": True,
                "source_type": "usaspending_api",
            }
        ]
    )
    gold = build_government_contract_parser_gold_template(features, tmp_path / "gold.csv", target_events=1)

    errors, report = validate_government_contract_parser(facts, gold)

    assert report["status"] == "gold_set_requires_human_review"
    assert report["parser_audit_pass"] is False
    assert report["audit_gate_results"]["gold_set_human_reviewed"] is False
    assert set(errors["status"]) == {"gold_not_reviewed"}


def test_human_audit_marks_usaspending_only_rows_not_model_eligible(tmp_path):
    mapping = write_government_contract_recipient_ticker_map(tmp_path / "map.csv")
    manifest = tmp_path / "sources.csv"
    pd.DataFrame(
        [
            _source_row(
                source_type="usaspending_api",
                release_session="unknown",
                source_url="https://www.usaspending.gov/award/CONT_AWD_TEST",
            )
        ]
    ).to_csv(manifest, index=False)
    _, features, events = parse_government_contract_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )

    audit, gold, mapping_errors, funded_errors, audited_events, summary = build_government_contract_human_audit(
        pd.read_csv(manifest),
        features,
        mapping,
        events=events,
        target_events=1,
    )

    assert len(audit) == 1
    assert audit.loc[0, "recipient_mapping_correct_flag"] == True
    assert audit.loc[0, "timestamp_suitable_flag"] == False
    assert audit.loc[0, "public_awareness_evidence_status"] == "usaspending_record_only_not_market_timestamp"
    assert audit.loc[0, "model_eligible_after_audit"] == False
    assert audit.loc[0, "review_status"] == "rejected"
    assert set(gold["gold_review_status"]) == {"reviewed"}
    assert mapping_errors.empty
    assert funded_errors.empty
    assert audited_events.loc[0, "review_status"] == "rejected"
    assert summary["verdict"] == "timestamp/public-awareness insufficient"


def test_enrich_government_contract_context_computes_ratios_and_runup(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "event_time": "2024-03-29T12:00:00",
                "release_session": "unknown",
                "award_amount": 100_000_000,
                "obligated_amount": 20_000_000,
                "contract_ceiling": pd.NA,
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    ktos_prices = pd.DataFrame(
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
    spy_prices = ktos_prices.copy()
    spy_prices["close"] = 10.0
    spy_prices["adj_close"] = 10.0
    ktos_prices.to_csv(prices_dir / "KTOS.csv", index=False)
    spy_prices.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "KTOS", "asof_date": "2024-03-01", "market_cap_before_event": 1_000_000_000}]).to_csv(tmp_path / "market_caps.csv", index=False)
    pd.DataFrame([{"ticker": "KTOS", "asof_date": "2024-03-01", "revenue_ltm_if_available": 500_000_000}]).to_csv(tmp_path / "revenue.csv", index=False)

    enriched = enrich_government_contract_context(
        events_path,
        prices_dir,
        tmp_path / "enriched.csv",
        market_caps_path=tmp_path / "market_caps.csv",
        revenue_path=tmp_path / "revenue.csv",
    )
    assert enriched.loc[0, "last_close_before_event"] > 10.0
    assert enriched.loc[0, "award_amount_pct_market_cap"] == 0.1
    assert enriched.loc[0, "obligated_amount_pct_market_cap"] == 0.02
    assert enriched.loc[0, "award_amount_pct_revenue"] == 0.2
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])
    assert enriched.loc[0, "small_cap_flag"] == True


def test_readiness_summary_can_be_model_ready_only_after_non_modeling_gates():
    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "review_status": "reviewed",
                "release_session": "before_open",
                "actual_funded_award_flag": i < 70,
                "ceiling_only_flag": i >= 70,
                "modification_flag": False,
                "option_exercise_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
                "obligated_amount_pct_market_cap": 0.04,
                "contract_ceiling_pct_market_cap": pd.NA,
                "pre_event_market_adjusted_return_20d": 0.01,
                "pre_event_market_adjusted_return_60d": 0.02,
                "company_size_bucket": "small_cap" if i < 35 else "large_cap",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 60})
    summary = government_contract_readiness_summary(pd.DataFrame(rows), min_train=40, parser_errors=parser_errors)
    assert summary["decision"] == "model-ready"
    assert summary["gates"]["actual_funded_award_events_60"] is True
    assert summary["likely_oos_predictions_min_train"] == 60


def test_readiness_summary_blocks_when_public_timestamp_gate_fails():
    rows = []
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "review_status": "approved",
                "release_session": "unknown",
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "modification_flag": False,
                "option_exercise_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
                "obligated_amount_pct_market_cap": 0.04,
                "pre_event_market_adjusted_return_20d": 0.01,
                "company_size_bucket": "small_cap" if i < 35 else "large_cap",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 120})
    summary = government_contract_readiness_summary(pd.DataFrame(rows), min_train=40, parser_errors=parser_errors)
    assert summary["gates"]["parser_audit_pass"] is True
    assert summary["gates"]["clear_event_timestamps"] is False
    assert summary["decision"] == "timestamp/public-awareness insufficient"


def test_public_announcement_candidates_prioritize_material_small_cap_rows():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W1",
                "event_time": "2024-01-02T12:00:00",
                "source_type": "usaspending_api",
                "source_url": "https://www.usaspending.gov/award/W1",
                "award_amount": 50_000_000,
                "obligated_amount": 50_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
                "obligated_amount_pct_market_cap": 0.05,
                "company_size_bucket": "small_cap",
                "small_cap_flag": True,
            },
            {
                "event_id": "E2",
                "ticker": "LMT",
                "recipient_name": "LOCKHEED MARTIN",
                "contract_number": "W2",
                "event_time": "2024-01-02T12:00:00",
                "source_type": "usaspending_api",
                "source_url": "https://www.usaspending.gov/award/W2",
                "award_amount": 10_000_000,
                "obligated_amount": 10_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.0001,
                "obligated_amount_pct_market_cap": 0.0001,
                "company_size_bucket": "large_cap",
                "small_cap_flag": False,
            },
        ]
    )
    candidates = build_government_contract_public_announcement_candidates(events)
    assert candidates.iloc[0]["event_id"] == "E1"
    assert candidates.iloc[0]["public_announcement_link_status"] == "needs_public_announcement_link"


def test_validate_public_announcement_links_builds_eligible_primary_and_duplicate():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "agency": "Department of Defense",
                "product_or_service_description": "drone command and control systems",
                "award_amount": 50_000_000,
                "obligated_amount": 50_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
                "obligated_amount_pct_market_cap": 0.05,
                "release_session": "unknown",
                "event_time": "2024-01-02T12:00:00",
            },
            {
                "event_id": "E2",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "agency": "Department of Defense",
                "product_or_service_description": "drone command and control systems",
                "award_amount": 50_000_000,
                "obligated_amount": 50_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
                "obligated_amount_pct_market_cap": 0.05,
                "release_session": "unknown",
                "event_time": "2024-01-03T12:00:00",
            },
        ]
    )
    links = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "announcement_time": "2024-01-02T08:30:00",
                "announcement_source_type": "company_press_release",
                "announcement_source_url": "https://example.com/ktos-award",
                "announcement_title": "Kratos receives Department of Defense award",
                "announcement_text_excerpt": "Kratos Defense received a $50 million Department of Defense award for drone command and control systems under contract W911TEST.",
                "source_confidence": 0.95,
                "link_confidence": 0.95,
            },
            {
                "event_id": "E2",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "announcement_time": "2024-01-02T08:30:00",
                "announcement_source_type": "company_press_release",
                "announcement_source_url": "https://example.com/ktos-award",
                "announcement_title": "Kratos receives Department of Defense award",
                "announcement_text_excerpt": "Kratos Defense received a $50 million Department of Defense award for drone command and control systems under contract W911TEST.",
                "source_confidence": 0.95,
                "link_confidence": 0.90,
            },
        ]
    )
    parser_errors = pd.DataFrame({"status": ["ok"] * 80})
    validated, audit, eligible, summary = validate_government_contract_public_links(
        events,
        links,
        parser_errors=parser_errors,
        audit_candidates=build_government_contract_public_announcement_candidates(events),
        target_audit_rows=2,
    )
    assert validated.loc[0, "duplicate_status"] == "primary"
    assert validated.loc[1, "duplicate_status"] == "duplicate"
    assert validated.loc[0, "model_eligible_public_announcement_flag"] == True
    assert validated.loc[1, "model_eligible_public_announcement_flag"] == False
    assert len(eligible) == 1
    assert eligible.loc[0, "event_id"] == "E1"
    assert eligible.loc[0, "event_time"] == "2024-01-02T08:30:00"
    assert eligible.loc[0, "release_session"] == "before_open"
    assert summary["gates"]["no_duplicate_award_counted_twice"] is False


def test_validate_public_announcement_links_rejects_usaspending_source():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "agency": "Department of Defense",
                "award_amount": 50_000_000,
                "obligated_amount": 50_000_000,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "recipient_mapping_confidence": 0.95,
                "award_amount_pct_market_cap": 0.05,
            }
        ]
    )
    links = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "recipient_name": "KRATOS DEFENSE",
                "contract_number": "W911TEST",
                "announcement_time": "2024-01-02T12:00:00",
                "announcement_source_type": "usaspending_api",
                "announcement_source_url": "https://www.usaspending.gov/award/W911TEST",
                "announcement_title": "USAspending award",
                "announcement_text_excerpt": "Kratos Defense Department of Defense award W911TEST $50 million.",
                "source_confidence": 0.95,
                "link_confidence": 0.95,
            }
        ]
    )
    validated, _, eligible, summary = validate_government_contract_public_links(events, links, parser_errors=pd.DataFrame({"status": ["ok"] * 80}))
    assert validated.loc[0, "valid_public_announcement_link_flag"] == False
    assert "announcement_source_not_public_market_source" in validated.loc[0, "validation_notes"]
    assert "timestamp_source_type_usaspending_only" in validated.loc[0, "validation_notes"]
    assert eligible.empty
    assert summary["gates"]["no_usaspending_only_model_eligible"] is True


def test_source_builder_merges_paginated_usaspending_rows(monkeypatch, tmp_path):
    seen_pages = []

    def fake_query(search_term, codes, **kwargs):
        page = kwargs.get("page", 1)
        seen_pages.append((search_term, codes[0], page))
        if search_term != "PALANTIR" or codes[0] != "A":
            return []
        if page == 1:
            return [
                {
                    "internal_id": 1,
                    "generated_internal_id": "CONT_AWD_W911QX24F0053_9700",
                    "Award ID": "W911QX24F0053",
                    "Recipient Name": "PALANTIR USG INC",
                    "Start Date": "2024-06-18",
                    "End Date": "2026-05-31",
                    "Award Amount": 292_700_000,
                    "Awarding Agency": "Department of Defense",
                    "Awarding Sub Agency": "Department of the Army",
                    "Contract Award Type": "DELIVERY ORDER",
                    "NAICS": {"code": "541715", "description": "R&D"},
                    "PSC": {"code": "AC35", "description": "R&D services"},
                    "Description": "TASK ORDER FOR MAVEN SMART SYSTEM",
                }
            ]
        if page == 2:
            return [
                {
                    "internal_id": 2,
                    "generated_internal_id": "CONT_AWD_W911QX24F0054_9700",
                    "Award ID": "W911QX24F0054",
                    "Recipient Name": "PALANTIR USG INC",
                    "Start Date": "2024-07-18",
                    "End Date": "2026-07-31",
                    "Award Amount": 42_000_000,
                    "Awarding Agency": "Department of Defense",
                    "Awarding Sub Agency": "Department of the Army",
                    "Contract Award Type": "DELIVERY ORDER",
                    "NAICS": {"code": "541715", "description": "R&D"},
                    "PSC": {"code": "AC35", "description": "R&D services"},
                    "Description": "TASK ORDER FOR DATA INTEGRATION",
                }
            ]
        return []

    monkeypatch.setattr("mre.government_contracts._query_usaspending_group", fake_query)
    df, diag = build_government_contract_source_documents(
        tmp_path / "sources.csv",
        mapping_path=tmp_path / "map.csv",
        use_usaspending=True,
        tickers=["PLTR"],
        limit_per_recipient=1,
        pages_per_recipient=2,
    )
    assert diag["usaspending_rows"] == 2
    assert df.loc[0, "ticker"] == "PLTR"
    assert df.loc[0, "source_type"] == "usaspending_api"
    assert "TASK ORDER" in df.loc[0, "text"]
    assert ("PALANTIR", "A", 2) in seen_pages
