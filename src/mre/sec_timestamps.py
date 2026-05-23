from __future__ import annotations

from pathlib import Path

from .sec_common import (
    clean_text,
    first_present,
    iso_datetime,
    market_close,
    market_open,
    next_trading_day,
    parse_datetime_et,
    read_csv_rows,
    truthy,
    write_csv_rows,
)

TIMESTAMP_FIELDS = [
    "event_time_original",
    "sec_acceptance_time",
    "selected_event_time",
    "selected_event_time_source",
    "release_session",
    "first_tradable_timestamp",
    "reaction_window_start",
    "timestamp_confidence",
    "timestamp_notes",
    "timestamp_status",
]


def classify_release_session(selected_event_time: object) -> tuple[str, bool]:
    dt, date_only = parse_datetime_et(selected_event_time)
    if dt is None:
        return "missing", False
    if date_only:
        return "ambiguous", True
    if dt < market_open(dt.date()):
        return "before_open", False
    if dt >= market_close(dt.date()):
        return "after_close", False
    return "intraday", False


def audit_timestamp_row(row: dict[str, str], *, has_intraday_prices: bool = False) -> dict[str, object]:
    out = dict(row)
    event_time_original = first_present(row, ["event_time_original", "event_time"])
    sec_acceptance_time = first_present(row, ["sec_acceptance_time", "filing_acceptance_time", "acceptanceDateTime"])
    selected = sec_acceptance_time or event_time_original
    selected_source = "sec_acceptance_time" if sec_acceptance_time else ("event_time" if event_time_original else "none")
    selected_dt, selected_date_only = parse_datetime_et(selected)
    notes: list[str] = []

    if selected_dt is None:
        release_session = "missing"
        first_tradable = None
        status = "missing_timestamp"
        confidence = 0.0
        notes.append("missing parseable SEC acceptance time and event_time")
    else:
        release_session, ambiguous = classify_release_session(selected)
        confidence = 0.95 if selected_source == "sec_acceptance_time" else 0.80
        status = "ok"
        if release_session == "before_open":
            tradable_day = next_trading_day(selected_dt.date(), include_same_day=True)
            first_tradable = market_open(tradable_day)
        elif release_session == "after_close":
            tradable_day = next_trading_day(selected_dt.date(), include_same_day=False)
            first_tradable = market_open(tradable_day)
        elif release_session == "intraday":
            if has_intraday_prices:
                first_tradable = selected_dt
                confidence = min(confidence, 0.75)
            else:
                tradable_day = next_trading_day(selected_dt.date(), include_same_day=False)
                first_tradable = market_open(tradable_day)
                status = "ambiguous"
                confidence = min(confidence, 0.40)
                notes.append("intraday release without intraday prices; next open is conservative but not model eligible")
        else:
            tradable_day = next_trading_day(selected_dt.date(), include_same_day=not selected_date_only)
            first_tradable = market_open(tradable_day)
            status = "ambiguous"
            confidence = min(confidence, 0.20)
            notes.append("date-only or ambiguous selected event time")
        if ambiguous:
            status = "ambiguous"
            confidence = min(confidence, 0.20)

    existing_reaction_start = clean_text(row.get("reaction_window_start"))
    reaction_start = existing_reaction_start or iso_datetime(first_tradable)
    reaction_start_dt, _ = parse_datetime_et(reaction_start)
    if first_tradable is not None and reaction_start_dt is not None and reaction_start_dt < first_tradable:
        status = "invalid_reaction_window"
        confidence = min(confidence, 0.10)
        notes.append("reaction window starts before first tradable timestamp")

    out["event_time_original"] = event_time_original
    out["sec_acceptance_time"] = sec_acceptance_time
    out["selected_event_time"] = iso_datetime(selected_dt)
    out["selected_event_time_source"] = selected_source
    out["release_session"] = release_session
    out["first_tradable_timestamp"] = iso_datetime(first_tradable)
    out["reaction_window_start"] = reaction_start
    out["timestamp_confidence"] = f"{confidence:.2f}"
    out["timestamp_notes"] = "; ".join(notes)
    out["timestamp_status"] = status

    existing_eligible = clean_text(row.get("model_eligible"))
    eligible = status == "ok" and (not existing_eligible or truthy(existing_eligible))
    out["model_eligible"] = "true" if eligible else "false"
    return out


def audit_timestamps(
    input_path: str | Path,
    out_path: str | Path,
    *,
    has_intraday_prices: bool = False,
) -> list[dict[str, object]]:
    rows, columns = read_csv_rows(input_path)
    output = [audit_timestamp_row(row, has_intraday_prices=has_intraday_prices) for row in rows]
    out_columns = list(columns)
    for col in TIMESTAMP_FIELDS + ["model_eligible"]:
        if col not in out_columns:
            out_columns.append(col)
    write_csv_rows(out_path, output, out_columns)
    return output
