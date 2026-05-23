from __future__ import annotations

import pandas as pd

from mre.activist_13d import (
    ACTIVIST_13D_DOMAIN,
    activist_13d_readiness_summary,
    audit_activist_13d_timestamps_and_duplicates,
    build_activist_13d_sec_source_documents,
    classify_execution_survivability,
    enrich_activist_13d_context,
    parse_activist_13d_document,
    parse_activist_13d_manifest,
    validate_activist_13d_parser,
)
from mre.corpus import make_domain_event_template, normalize_domain
from mre.source_docs import SourceDocument, make_source_docs_template


def _doc(text: str, *, event_id: str = "XYZ_13d_2024", subtype: str = "SC 13D", title: str = "Schedule 13D") -> SourceDocument:
    return SourceDocument(
        source_doc_id=f"{event_id}_doc",
        ticker="XYZ",
        event_id=event_id,
        event_time=pd.Timestamp("2024-01-02 16:05:00"),
        event_type="ownership",
        event_subtype=subtype,
        release_session="after_close",
        source_type="sec_filing",
        source_url="https://sec.test/13d.htm",
        title=title,
        text=text,
    )


def test_corpus_template_contains_activist_13d_fields(tmp_path):
    assert normalize_domain("13d") == ACTIVIST_13D_DOMAIN
    df = make_domain_event_template("activist_13d", tmp_path / "template.csv", tickers=["XYZ"])
    assert df.loc[0, "event_family"] == ACTIVIST_13D_DOMAIN
    assert "item_4_purpose_text" in df.columns
    assert "execution_survivability_class" in df.columns


def test_parse_board_and_sale_pressure_13d():
    facts = parse_activist_13d_document(
        _doc(
            "SCHEDULE 13D\nName of Reporting Person: Starboard Value LP\n"
            "Aggregate amount beneficially owned: 1,250,000\n"
            "Percent of class represented by amount in Row 11: 7.5%\n"
            "Item 3. Source and Amount of Funds. The shares were purchased with working capital.\n"
            "Item 4. Purpose of Transaction. The Reporting Person intends to engage with management "
            "and the Board regarding strategic alternatives, including a potential sale of the company, "
            "and may nominate directors at the next annual meeting.\n"
            "Item 5. Interest in Securities of the Issuer."
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["activist_13d_event_type"].value == "sale_pressure"
    assert by_name["beneficial_owner_name"].value == "Starboard Value LP"
    assert by_name["ownership_pct"].value == 7.5
    assert by_name["board_language_flag"].value is True
    assert by_name["sale_or_strategic_alternatives_flag"].value is True
    assert by_name["financing_source_of_funds"].value == "working_capital"


def test_parse_13g_is_passive_control_not_activist():
    facts = parse_activist_13d_document(
        _doc(
            "SCHEDULE 13G\nName of Reporting Person: Large Passive Asset Management\n"
            "Percent of class represented by amount in Row 11: 6.2%\n"
            "The securities are held in the ordinary course and not with any purpose of changing control.",
            subtype="SC 13G",
            title="Schedule 13G",
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["activist_13d_event_type"].value == "passive_13g_control"
    assert by_name["hard_negative_flag"].value is True


def test_parse_decrease_amendment_is_hard_negative():
    facts = parse_activist_13d_document(
        _doc(
            "SCHEDULE 13D Amendment No. 2\nName of Reporting Person: Example Capital\n"
            "Item 4. Purpose of Transaction. No material change. This amendment is being filed solely "
            "to report that ownership decreased from 8.1% to 4.8%. The Reporting Person ceases to be "
            "a beneficial owner of more than five percent.\nItem 5. Interest in Securities.",
            subtype="SC 13D/A",
            title="Schedule 13D/A",
        )
    )
    by_name = {fact.fact_name: fact for fact in facts}
    assert by_name["initial_or_amendment"].value == "amendment"
    assert by_name["activist_13d_event_type"].value == "exit_amendment"
    assert by_name["ownership_change_pct"].value < 0
    assert by_name["hard_negative_flag"].value is True


def test_parse_manifest_writes_feature_and_review_event(tmp_path):
    manifest = tmp_path / "docs.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "XYZ_13d_doc",
                "ticker": "XYZ",
                "event_id": "XYZ_13d_2024",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "ownership",
                "event_subtype": "SC 13D",
                "release_session": "after_close",
                "source_type": "sec_filing",
                "source_url": "https://sec.test/13d.htm",
                "title": "Schedule 13D",
                "text": (
                    "SCHEDULE 13D\nName of Reporting Person: Elliott Investment Management\n"
                    "Percent of class represented by amount in Row 11: 9.1%\n"
                    "Item 4. Purpose of Transaction. The Reporting Person intends to engage with "
                    "management and the board to enhance shareholder value.\nItem 5. Interest in Securities."
                ),
            }
        ],
    )
    facts, features, events = parse_activist_13d_manifest(
        manifest,
        tmp_path / "facts.csv",
        tmp_path / "features.csv",
        tmp_path / "events.csv",
    )
    assert "activist_13d_event_type" in set(facts["fact_name"])
    assert features.loc[0, "activist_13d_event_type"] == "control_intent_13d"
    assert features.loc[0, "execution_survivability_class"] == "delayed-digestion"
    assert events.loc[0, "event_family"] == ACTIVIST_13D_DOMAIN
    assert events.loc[0, "review_status"] == "unreviewed"


def test_validate_parser_detects_passive_false_positive():
    facts = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "fact_name": "activist_13d_event_type",
                "value": "initial_activist_13d",
                "unit": "category",
                "confidence": 0.9,
                "evidence_text": "13G",
            }
        ]
    )
    gold = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "fact_name": "activist_13d_event_type",
                "expected_value": "passive_13g_control",
                "unit": "category",
                "gold_category": "13g_passive_hard_negative",
                "gold_review_status": "reviewed",
            }
        ]
    )
    errors, report = validate_activist_13d_parser(facts, gold)
    assert errors.loc[0, "status"] == "wrong_value"
    assert report["gates"]["no_passive_or_13g_false_activist"] is False
    assert report["parser_audit_pass"] is False


def test_timestamp_duplicate_audit_marks_duplicate_and_unclear_session():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "beneficial_owner_name": "Fund",
                "filing_type": "SC 13D",
                "source_url": "https://sec.test/a",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "after_close",
            },
            {
                "event_id": "E2",
                "ticker": "XYZ",
                "beneficial_owner_name": "Fund",
                "filing_type": "SC 13D",
                "source_url": "https://sec.test/a",
                "event_time": "2024-01-02T16:05:00",
                "release_session": "unknown",
            },
        ]
    )
    audited, summary = audit_activist_13d_timestamps_and_duplicates(events)
    assert audited.loc[1, "duplicate_status"] == "duplicate"
    assert audited.loc[1, "timestamp_audit_status"] == "needs_timestamp_review"
    assert summary["audit_pass"] is False


def test_context_enrichment_adds_market_cap_and_runup(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "XYZ",
                "event_time": "2024-03-29T16:05:00",
                "release_session": "after_close",
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=70, freq="B")
    xyz = pd.DataFrame(
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
    spy = xyz.copy()
    spy["close"] = 10.0
    spy["adj_close"] = 10.0
    xyz.to_csv(prices_dir / "XYZ.csv", index=False)
    spy.to_csv(prices_dir / "SPY.csv", index=False)
    pd.DataFrame([{"ticker": "XYZ", "asof_date": "2024-03-01", "market_cap_before_event": 1_500_000_000}]).to_csv(tmp_path / "market_caps.csv", index=False)

    enriched = enrich_activist_13d_context(events_path, prices_dir, tmp_path / "enriched.csv", market_caps_path=tmp_path / "market_caps.csv")
    assert enriched.loc[0, "company_size_bucket"] == "small_cap"
    assert pd.notna(enriched.loc[0, "pre_event_market_adjusted_return_20d"])


def test_readiness_summary_can_be_model_ready_only_after_non_modeling_gates():
    rows = []
    active_types = ["initial_activist_13d", "control_intent_13d", "board_seat_campaign", "sale_pressure"]
    hard_types = ["passive_13g_control", "ownership_decrease_amendment", "exit_amendment", "passive_or_ambiguous_13d"]
    for i in range(100):
        rows.append(
            {
                "event_id": f"E{i}",
                "ticker": f"T{i % 10}",
                "review_status": "reviewed",
                "activist_13d_event_type": active_types[i % len(active_types)] if i < 60 else hard_types[i % len(hard_types)],
                "ownership_pct": 6.0,
                "market_cap_before_event": 1_000_000_000,
                "pre_event_market_adjusted_return_20d": 0.01,
                "release_session": "after_close",
                "timestamp_audit_status": "clear",
                "duplicate_status": "primary",
            }
        )
    parser_errors = pd.DataFrame({"status": ["ok"] * 80})
    source_docs = pd.DataFrame({"source_doc_id": [f"D{i}" for i in range(120)]})
    summary = activist_13d_readiness_summary(pd.DataFrame(rows), source_documents=source_docs, parser_errors=parser_errors)
    assert summary["decision"] == "model-ready"
    assert summary["gates"]["initial_active_or_control_events_50"] is True


def test_execution_survivability_explanation_only_requires_next_open():
    result = classify_execution_survivability("passive_13g_control", "after_close")
    assert result["execution_survivability_class"] == "explanation-only"
    assert result["first_realistic_entry"] == "next_open"
    assert result["next_open_required_flag"] is True
    assert result["close_to_close_explanatory_only_flag"] is True


def test_source_builder_skips_bad_ticker(monkeypatch, tmp_path):
    calls = []

    def fake_build_manifest(client, tickers, out_manifest, docs_dir, **kwargs):
        ticker = tickers[0]
        calls.append((ticker, tuple(kwargs["forms"])))
        if ticker == "BAD":
            raise ValueError("missing ticker")
        df = pd.DataFrame(
            [
                {
                    "source_doc_id": f"{ticker}_doc",
                    "ticker": ticker,
                    "event_id": f"{ticker}_event",
                    "event_time": "2024-01-01T16:05:00",
                    "event_type": "filing",
                    "event_subtype": "SC 13D",
                    "release_session": "after_close",
                    "source_type": "sec_primary_filing",
                    "source_url": "https://sec.test/doc.htm",
                    "title": "doc",
                    "path": "doc.txt",
                    "text": "",
                    "fiscal_period_end": "",
                    "sector_benchmark": "",
                    "notes": "",
                }
            ]
        )
        df.to_csv(out_manifest, index=False)
        from mre.ingestion import IngestionDiagnostics

        return df, IngestionDiagnostics(rows_total=1, rows_written=1)

    monkeypatch.setattr("mre.activist_13d.build_sec_source_document_manifest", fake_build_manifest)
    df, diag = build_activist_13d_sec_source_documents(
        client=object(),
        tickers=["GOOD", "BAD"],
        out_manifest=tmp_path / "sources.csv",
        docs_dir=tmp_path / "docs",
    )
    assert set(df["ticker"]) == {"GOOD"}
    assert diag.rows_written == 1
    assert diag.rows_skipped == 1
    assert calls[0] == ("GOOD", ("SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"))
