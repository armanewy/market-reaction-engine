from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .paths import ensure_parent

class _FallbackEastern(tzinfo):
    """US Eastern timezone fallback for environments without tzdata."""

    @staticmethod
    def _dst_start(year: int) -> datetime:
        day = nth_weekday(year, 3, 6, 2)
        return datetime.combine(day, time(2, 0))

    @staticmethod
    def _dst_end(year: int) -> datetime:
        day = nth_weekday(year, 11, 6, 1)
        return datetime.combine(day, time(2, 0))

    def _is_dst_local(self, dt: datetime | None) -> bool:
        if dt is None:
            return False
        naive = dt.replace(tzinfo=None)
        return self._dst_start(naive.year) <= naive < self._dst_end(naive.year)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-4 if self._is_dst_local(dt) else -5)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1 if self._is_dst_local(dt) else 0)

    def tzname(self, dt: datetime | None) -> str:
        return "EDT" if self._is_dst_local(dt) else "EST"

    def fromutc(self, dt: datetime) -> datetime:
        utc_naive = dt.replace(tzinfo=None)
        dst_candidate = (utc_naive + timedelta(hours=-4)).replace(tzinfo=self)
        if self._is_dst_local(dst_candidate):
            return dst_candidate
        return (utc_naive + timedelta(hours=-5)).replace(tzinfo=self)


try:
    EASTERN = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    EASTERN = _FallbackEastern()


def read_csv_rows(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def write_csv_rows(path: str | Path, rows: Iterable[Mapping[str, object]], columns: list[str]) -> Path:
    out = ensure_parent(path)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: csv_value(row.get(col, "")) for col in columns})
    return out


def csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def first_present(row: Mapping[str, object], names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = row.get(name)
        text = clean_text(value)
        if text:
            return text
    return default


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def truthy(value: object) -> bool:
    return clean_text(value).lower() in {"1", "true", "t", "yes", "y"}


def falsy(value: object) -> bool:
    return clean_text(value).lower() in {"0", "false", "f", "no", "n"}


def to_float(value: object) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def parse_date(value: object) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime_et(value: object) -> tuple[datetime | None, bool]:
    text = clean_text(value)
    if not text:
        return None, False
    date_only = bool(_DATE_ONLY_RE.match(text))
    normalized = text.replace("Z", "+00:00")
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
        date_only = True
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d"):
            try:
                dt = datetime.strptime(text, fmt)
                date_only = fmt == "%Y%m%d"
                break
            except ValueError:
                continue
        else:
            return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    else:
        dt = dt.astimezone(EASTERN)
    return dt, date_only


def iso_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def iso_datetime(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def observed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        day = date(year, month + 1, 1) - timedelta(days=1)
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year: int) -> set[date]:
    holidays = {
        observed_holiday(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_holiday(date(year, 6, 19)),
        observed_holiday(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_holiday(date(year, 12, 25)),
    }
    return holidays


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in market_holidays(day.year)


def next_trading_day(day: date, *, include_same_day: bool = True) -> date:
    current = day if include_same_day else day + timedelta(days=1)
    while not is_trading_day(current):
        current += timedelta(days=1)
    return current


def previous_trading_day(day: date, *, include_same_day: bool = True) -> date | None:
    current = day if include_same_day else day - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(current):
            return current
        current -= timedelta(days=1)
    return None


def market_open(day: date) -> datetime:
    return datetime.combine(day, time(9, 30), tzinfo=EASTERN)


def market_close(day: date) -> datetime:
    return datetime.combine(day, time(16, 0), tzinfo=EASTERN)
