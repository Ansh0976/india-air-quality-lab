"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .audit import (
    date_range_is_valid,
    flatten_daily_rows,
    pm25_sensors,
    select_locations,
    summarize_rows,
    valid_date,
    write_csv,
)
from .benchmark import benchmark, load_daily_csv
from .openaq import OpenAQClient, OpenAQError


def _write_json(data: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _discover(args: argparse.Namespace) -> int:
    client = OpenAQClient()
    matches = select_locations(client.iter_locations(), args.city)
    if not matches:
        print(f"No stationary PM2.5 stations matched {args.city!r}.")
        return 0

    payload = []
    for location in matches:
        country = location.get("country") or {}
        for sensor in pm25_sensors(location):
            parameter = sensor.get("parameter") or {}
            payload.append(
                {
                    "location_id": location.get("id"),
                    "station": location.get("name"),
                    "city": location.get("locality", ""),
                    "country": country.get("name"),
                    "sensor_id": sensor.get("id"),
                    "units": parameter.get("units"),
                    "provider": (location.get("provider") or {}).get("name"),
                    "owner": (location.get("owner") or {}).get("name"),
                    "licenses": location.get("licenses", []),
                    "first_reading": location.get("datetimeFirst"),
                    "last_reading": location.get("datetimeLast"),
                }
            )

    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(payload, output / "station-candidates.json")
    print(f"Matched {len(matches)} stationary locations and {len(payload)} PM2.5 sensors.")
    print(f"Candidate metadata saved to {output / 'station-candidates.json'}")
    print("Review station names, units, providers, and licenses before collecting readings.")
    return 0


def _audit(args: argparse.Namespace) -> int:
    start = valid_date(args.start)
    end = valid_date(args.end)
    if not date_range_is_valid(start, end):
        raise ValueError("--start must be on or before --end.")

    client = OpenAQClient()
    selected = select_locations(client.iter_locations(), args.city)
    if args.location_id is not None:
        selected = [location for location in selected if location.get("id") == args.location_id]
        if not selected:
            results = client.get(f"locations/{args.location_id}").get("results", [])
            if not results:
                raise ValueError(f"OpenAQ location {args.location_id} was not found.")
            selected = results
    if args.max_stations:
        selected = selected[: args.max_stations]
    if not selected:
        raise ValueError("No matching PM2.5 stations were found.")

    rows = []
    for index, location in enumerate(selected, start=1):
        sensors = pm25_sensors(location)
        if args.sensor_id is not None:
            sensors = [sensor for sensor in sensors if sensor.get("id") == args.sensor_id]
        if not sensors:
            continue
        print(f"[{index}/{len(selected)}] {location.get('name')} ({location.get('id')})")
        for sensor in sensors:
            daily = client.sensor_daily(sensor["id"], start, end)
            rows.extend(flatten_daily_rows(location, sensor, daily))

    if not rows:
        raise ValueError("No daily PM2.5 records were returned for this selection and date range.")

    output = Path(args.out)
    csv_path = output / "daily-pm25.csv"
    json_path = output / "coverage-summary.json"
    write_csv(rows, csv_path)
    summary = summarize_rows(rows, start, end)
    summary.update(
        {
            "source": "OpenAQ API v3",
            "target": "Daily PM2.5 sensor aggregates; not an AQI calculation.",
            "date_from": start,
            "date_to": end,
            "daily_csv": str(csv_path),
            "coverage_definition": (
                "Record-date coverage uses distinct dates with a daily aggregate divided by "
                "the full requested calendar window, including leading and trailing gaps. "
                "Value-date coverage excludes records with missing values. Both are separate "
                "from OpenAQ's within-day aggregate coverage."
            ),
        }
    )
    _write_json(summary, json_path)
    print(
        f"Saved {summary['daily_record_count']} sensor-days across "
        f"{summary['station_count']} stations and {summary['city_count']} cities."
    )
    print(f"Daily observations: {csv_path}")
    print(f"Coverage summary:   {json_path}")
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    records = load_daily_csv(args.input)
    result = benchmark(records, args.holdout_city)
    _write_json(result, args.out)
    print(json.dumps(result, indent=2))
    print(f"Saved results to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aqi-lab",
        description="Audit Indian PM2.5 station coverage and benchmark daily forecasts.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", help="find Indian stationary PM2.5 sensors")
    discover.add_argument("--city", help="case-insensitive substring in station or locality")
    discover.add_argument("--out", default="data/metadata")
    discover.set_defaults(handler=_discover)

    audit = commands.add_parser("audit", help="collect daily PM2.5 data and coverage")
    audit.add_argument("--city", help="filter stations by locality/name")
    audit.add_argument("--location-id", type=int, help="audit one OpenAQ location")
    audit.add_argument("--sensor-id", type=int, help="audit one PM2.5 sensor")
    audit.add_argument("--max-stations", type=int, default=10)
    audit.add_argument("--start", default=(date.today() - timedelta(days=365)).isoformat())
    audit.add_argument("--end", default=date.today().isoformat())
    audit.add_argument("--out", default="data/processed")
    audit.set_defaults(handler=_audit)

    model = commands.add_parser("benchmark", help="compare baselines and a random forest")
    model.add_argument("--input", default="data/processed/daily-pm25.csv")
    model.add_argument("--out", default="reports/benchmark.json")
    model.add_argument("--holdout-city", help="city withheld entirely from model training")
    model.set_defaults(handler=_benchmark)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OpenAQError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
