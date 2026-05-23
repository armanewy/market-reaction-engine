from __future__ import annotations

from pathlib import Path

from .sec_common import clean_text, first_present, read_csv_rows, write_csv_rows

REVIEW_COLUMNS = [
    "event_id",
    "ticker",
    "form",
    "item_numbers",
    "event_time",
    "source_url",
    "review_status",
    "label_quality",
    "evidence_status",
    "reviewed_by",
    "reviewed_at",
    "drop_reason",
    "review_notes",
    "model_eligible",
]


def create_review_template(input_path: str | Path, out_path: str | Path) -> list[dict[str, object]]:
    rows, _ = read_csv_rows(input_path)
    output: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        event_id = first_present(row, ["event_id", "source_doc_id"], f"review_event_{index:05d}")
        event_time = first_present(row, ["event_time", "filing_acceptance_time", "filing_date"])
        output.append(
            {
                "event_id": event_id,
                "ticker": clean_text(row.get("ticker")).upper(),
                "form": clean_text(row.get("form")),
                "item_numbers": clean_text(row.get("item_numbers")),
                "event_time": event_time,
                "source_url": first_present(row, ["source_url", "primary_doc_url"]),
                "review_status": "unreviewed",
                "label_quality": "unreviewed",
                "evidence_status": "needs_review",
                "reviewed_by": "",
                "reviewed_at": "",
                "drop_reason": "",
                "review_notes": "",
                "model_eligible": "false",
            }
        )
    write_csv_rows(out_path, output, REVIEW_COLUMNS)
    return output
