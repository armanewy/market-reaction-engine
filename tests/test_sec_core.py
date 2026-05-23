from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from mre.cli import main
from mre.sec_context import add_sec_context
from mre.sec_readiness import build_readiness
from mre.sec_timestamps import audit_timestamp_row
from mre.source_docs import SEC_SOURCE_DOC_COLUMNS, discover_sec_source_documents


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str] | None = None) -> Path:
    columns = columns or list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class FakeSecClient:
    def get_json(self, url: str):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "ABC", "cik_str": 123456}}
        return {
            "filings": {
                "recent": {
                    "form": ["8-K", "4"],
                    "filingDate": ["2024-01-03", "2024-01-05"],
                    "acceptanceDateTime": ["2024-01-03T13:00:00Z", "2024-01-05T21:10:00Z"],
                    "accessionNumber": ["0000123456-24-000001", "0000123456-24-000002"],
                    "primaryDocument": ["abc-8k.htm", "abc-4.xml"],
                    "items": ["", ""],
                },
                "files": [],
            }
        }

    def get_text(self, url: str) -> str:
        if url.endswith("abc-8k.htm"):
            return "<html><body>Item 1.05 Material Cybersecurity Incidents.</body></html>"
        return "<xml />"


def test_sec_source_docs_discovers_downloads_and_filters_items(tmp_path: Path):
    rows = discover_sec_source_documents(
        domain="cybersecurity_material_incidents_8k",
        tickers=["ABC"],
        forms=["8-K"],
        items=["1.05"],
        start="2024-01-01",
        end="2024-01-31",
        docs_dir=tmp_path / "docs",
        client=FakeSecClient(),  # type: ignore[arg-type]
    )

    assert len(rows) == 1
    assert list(rows[0].keys()) == SEC_SOURCE_DOC_COLUMNS
    assert rows[0]["form"] == "8-K"
    assert rows[0]["item_numbers"] == "1.05"
    assert Path(str(rows[0]["local_path"])).exists()


def test_review_template_command_from_source_docs(tmp_path: Path):
    source = write_csv(
        tmp_path / "sources.csv",
        [
            {
                "source_doc_id": "doc1",
                "ticker": "ABC",
                "form": "8-K",
                "item_numbers": "1.05",
                "filing_acceptance_time": "2024-01-03T13:00:00Z",
                "source_url": "https://sec.test/doc1",
            }
        ],
    )
    out = tmp_path / "review.csv"

    assert main(["sec-domain-review-template", "--input", str(source), "--out", str(out)]) == 0
    rows = read_csv(out)
    assert rows[0]["event_id"] == "doc1"
    assert rows[0]["event_time"] == "2024-01-03T13:00:00Z"
    assert rows[0]["review_status"] == "unreviewed"
    assert rows[0]["model_eligible"] == "false"


def make_price_rows(start: date, count: int, base: float) -> list[dict[str, object]]:
    rows = []
    day = start
    index = 0
    while len(rows) < count:
        if day.weekday() < 5:
            close = base + index
            rows.append({"date": day.isoformat(), "close": close, "volume": 1000 + index})
            index += 1
        day += timedelta(days=1)
    return rows


def test_context_command_adds_required_fields_and_pit_capitalization(tmp_path: Path):
    prices_dir = tmp_path / "prices"
    abc_prices = make_price_rows(date(2024, 1, 2), 75, 10.0)
    spy_prices = make_price_rows(date(2024, 1, 2), 75, 100.0)
    write_csv(prices_dir / "ABC.csv", abc_prices)
    write_csv(prices_dir / "SPY.csv", spy_prices)
    event_day = abc_prices[65]["date"]
    events = write_csv(
        tmp_path / "events.csv",
        [{"event_id": "e1", "ticker": "ABC", "event_time": f"{event_day}T08:00:00-05:00", "model_eligible": "true"}],
    )
    shares = write_csv(
        tmp_path / "shares.csv",
        [{"ticker": "ABC", "asof_date": "2023-12-31", "shares_outstanding": "10000000"}],
    )
    out = tmp_path / "context.csv"

    assert (
        main(
            [
                "sec-domain-context",
                "--input",
                str(events),
                "--prices-dir",
                str(prices_dir),
                "--shares-outstanding",
                str(shares),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    row = read_csv(out)[0]
    assert row["last_close_before_event"]
    assert row["market_cap_before_event"]
    assert row["shares_outstanding_before_event"] == "10000000.0"
    assert row["pre_event_market_adjusted_return_20d"]
    assert row["pre_event_market_adjusted_return_60d"]
    assert row["pre_event_volatility_20d"]
    assert row["dollar_volume_20d"]
    assert row["company_size_bucket"] in {"micro", "small", "mid", "large", "mega"}


def test_timestamp_audit_rules_before_after_and_intraday(tmp_path: Path):
    before = audit_timestamp_row({"event_id": "before", "filing_acceptance_time": "2024-01-03T13:00:00Z"})
    after = audit_timestamp_row({"event_id": "after", "filing_acceptance_time": "2024-01-03T22:00:00Z"})
    intraday = audit_timestamp_row({"event_id": "intraday", "filing_acceptance_time": "2024-01-03T17:00:00Z"})

    assert before["release_session"] == "before_open"
    assert "2024-01-03T09:30:00" in str(before["first_tradable_timestamp"])
    assert before["timestamp_status"] == "ok"
    assert after["release_session"] == "after_close"
    assert "2024-01-04T09:30:00" in str(after["first_tradable_timestamp"])
    assert intraday["release_session"] == "intraday"
    assert intraday["timestamp_status"] == "ambiguous"
    assert intraday["model_eligible"] == "false"


def test_timestamp_audit_command_marks_invalid_reaction_window(tmp_path: Path):
    source = write_csv(
        tmp_path / "events.csv",
        [
            {
                "event_id": "e1",
                "filing_acceptance_time": "2024-01-03T22:00:00Z",
                "reaction_window_start": "2024-01-03T09:30:00-05:00",
                "model_eligible": "true",
            }
        ],
    )
    out = tmp_path / "timestamps.csv"

    assert main(["sec-domain-timestamp-audit", "--input", str(source), "--out", str(out)]) == 0
    row = read_csv(out)[0]
    assert row["timestamp_status"] == "invalid_reaction_window"
    assert row["model_eligible"] == "false"


def test_readiness_report_command_and_helper_model_ready(tmp_path: Path):
    source_rows = [{"source_doc_id": f"s{i}", "ticker": "ABC"} for i in range(45)]
    parsed_rows = [{"event_id": f"e{i}", "ticker": "ABC", "model_eligible": "true"} for i in range(45)]
    review_rows = [
        {"event_id": f"e{i}", "ticker": "ABC", "review_status": "approved", "model_eligible": "true"}
        for i in range(45)
    ]
    parser_rows = [{"event_id": f"e{i}", "fact_name": "event_type", "status": "ok"} for i in range(60)]
    timestamp_rows = [{"event_id": f"e{i}", "timestamp_status": "ok", "model_eligible": "true"} for i in range(45)]
    context_rows = []
    for i in range(45):
        row = {"event_id": f"e{i}", "model_eligible": "true"}
        row.update(
            {
                "last_close_before_event": "10",
                "market_cap_before_event": "1000000000",
                "shares_outstanding_before_event": "100000000",
                "pre_event_market_adjusted_return_20d": "0.01",
                "pre_event_market_adjusted_return_60d": "0.02",
                "pre_event_volatility_20d": "0.03",
                "dollar_volume_20d": "1000000",
                "company_size_bucket": "small",
            }
        )
        context_rows.append(row)

    sources = write_csv(tmp_path / "sources.csv", source_rows)
    parsed = write_csv(tmp_path / "parsed.csv", parsed_rows)
    review = write_csv(tmp_path / "review.csv", review_rows)
    parser_audit = write_csv(tmp_path / "parser.csv", parser_rows)
    timestamps = write_csv(tmp_path / "timestamps.csv", timestamp_rows)
    context = write_csv(tmp_path / "context.csv", context_rows)

    readiness = build_readiness(
        domain="accounting_integrity_8k",
        sources_path=sources,
        parsed_path=parsed,
        review_path=review,
        parser_audit_path=parser_audit,
        timestamp_audit_path=timestamps,
        context_path=context,
        min_train=40,
    )
    assert readiness["decision"] == "model-ready"
    assert readiness["likely_oos_predictions"] == 5

    report = tmp_path / "readiness.md"
    assert (
        main(
            [
                "sec-domain-readiness-report",
                "--domain",
                "accounting_integrity_8k",
                "--sources",
                str(sources),
                "--parsed",
                str(parsed),
                "--review",
                str(review),
                "--parser-audit",
                str(parser_audit),
                "--timestamp-audit",
                str(timestamps),
                "--context",
                str(context),
                "--out",
                str(report),
            ]
        )
        == 0
    )
    assert "Decision: model-ready" in report.read_text(encoding="utf-8")
