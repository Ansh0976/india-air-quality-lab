"""Station selection and transparent daily-coverage calculations."""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

PM25 = "pm25"


def _location_text(location: dict[str, Any]) -> str:
    country = location.get("country") or {}
    return " ".join(
        str(value)
        for value in (location.get("name"), location.get("locality"), country.get("name"))
        if value
    )


def pm25_sensors(location: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only PM2.5 sensor metadata, preserving the source units."""
    return [
        sensor
        for sensor in location.get("sensors", [])
        if (sensor.get("parameter") or {}).get("name", "").lower() == PM25
    ]


def select_locations(
    locations: Iterable[dict[str, Any]], city: str | None = None
) -> list[dict[str, Any]]:
    """Keep stationary PM2.5 stations, optionally matching a city/name."""
    needle = city.casefold().strip() if city else None
    selected = []
    seen = set()
    for location in locations:
        location_id = location.get("id")
        sensors = pm25_sensors(location)
        if location_id is None or not sensors or location_id in seen:
            continue
        if location.get("isMobile", False):
            continue
        if needle and needle not in _location_text(location).casefold():
            continue
        seen.add(location_id)
        selected.append(location)
    return selected


def _day_from_row(row: dict[str, Any]) -> str | None:
    period = row.get("period") or {}
    for key in ("datetimeFrom", "datetimeTo", "datetime_from", "datetime_to"):
        value = period.get(key)
        if isinstance(value, dict):
            local = value.get("local") or value.get("utc")
            if local:
                return str(local)[:10]
    return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def flatten_daily_rows(
    location: dict[str, Any], sensor: dict[str, Any], rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize OpenAQ daily aggregates without hiding missing coverage."""
    parameter = sensor.get("parameter") or {}
    country = location.get("country") or {}
    output = []
    for row in rows:
        day = _day_from_row(row)
        if day is None:
            continue
        coverage = row.get("coverage") or {}
        output.append(
            {
                "location_id": location.get("id"),
                "station": location.get("name", ""),
                "city": location.get("locality", ""),
                "country": country.get("code", ""),
                "sensor_id": sensor.get("id"),
                "parameter": parameter.get("name", PM25),
                "units": parameter.get("units", ""),
                "date": day,
                "value": _number(row.get("value")),
                "observed_count": coverage.get("observedCount"),
                "expected_count": coverage.get("expectedCount"),
                "coverage_pct": _number(
                    coverage.get("percentCoverage", coverage.get("percentComplete"))
                ),
                "source": "OpenAQ API v3",
            }
        )
    return output


def summarize_rows(
    rows: Iterable[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Summarize observed records and missing calendar days by sensor."""
    groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row.get("location_id"), row.get("sensor_id"), row.get("city"))].append(row)

    sensors = []
    for (location_id, sensor_id, city), records in sorted(
        groups.items(), key=lambda item: (str(item[0][2]), str(item[0][1]))
    ):
        records.sort(key=lambda row: row["date"])
        dates = [date.fromisoformat(row["date"]) for row in records]
        unique_dates = set(dates)
        first, last = min(dates), max(dates)
        range_start = date.fromisoformat(date_from) if date_from else first
        range_end = date.fromisoformat(date_to) if date_to else last
        if range_end < range_start:
            raise ValueError("The audit end date must be on or after the start date.")
        expected_days = (range_end - range_start).days + 1
        value_dates = {
            date.fromisoformat(row["date"])
            for row in records
            if row.get("value") is not None
        }
        values = [row["value"] for row in records if row.get("value") is not None]
        coverage_values = [
            row["coverage_pct"]
            for row in records
            if row.get("coverage_pct") is not None
        ]
        duplicates = len(dates) - len(unique_dates)
        sensors.append(
            {
                "location_id": location_id,
                "sensor_id": sensor_id,
                "city": city,
                "first_day": first.isoformat(),
                "last_day": last.isoformat(),
                "observed_record_days": len(unique_dates),
                "days_with_values": len(value_dates),
                "requested_calendar_days": expected_days,
                "record_date_coverage_pct": round(
                    100 * len(unique_dates) / expected_days, 2
                ),
                "value_date_coverage_pct": round(
                    100 * len(value_dates) / expected_days, 2
                ),
                "missing_value_days": len(unique_dates - value_dates),
                "duplicate_days": duplicates,
                "mean_daily_coverage_pct": round(
                    sum(coverage_values) / len(coverage_values), 2
                )
                if coverage_values
                else None,
                "mean_pm25": round(sum(values) / len(values), 3) if values else None,
            }
        )

    return {
        "sensor_count": len(sensors),
        "station_count": len({sensor["location_id"] for sensor in sensors}),
        "city_count": len({sensor["city"] for sensor in sensors if sensor["city"]}),
        "daily_record_count": sum(sensor["observed_record_days"] for sensor in sensors),
        "calendar_gap_days": sum(
            sensor["requested_calendar_days"] - sensor["observed_record_days"]
            for sensor in sensors
        ),
        "sensors": sensors,
    }


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    columns = [
        "location_id",
        "station",
        "city",
        "country",
        "sensor_id",
        "parameter",
        "units",
        "date",
        "value",
        "observed_count",
        "expected_count",
        "coverage_pct",
        "source",
    ]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def valid_date(value: str) -> str:
    """Validate an ISO calendar date supplied to the CLI."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"Expected a calendar date in YYYY-MM-DD format, got {value!r}.") from None


def date_range_is_valid(start: str, end: str) -> bool:
    return datetime.fromisoformat(start) <= datetime.fromisoformat(end)
