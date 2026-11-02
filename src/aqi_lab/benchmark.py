"""Leakage-aware daily PM2.5 benchmark helpers."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

REQUIRED_COLUMNS = {"city", "sensor_id", "date", "value"}


def load_daily_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read normalized daily observations and reject invalid rows."""
    records = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            try:
                value = float(row["value"])
                day = date.fromisoformat(row["date"])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or value < 0 or not row["city"].strip():
                continue
            records.append(
                {
                    **row,
                    "city": row["city"].strip(),
                    "sensor_id": row["sensor_id"].strip(),
                    "date": day,
                    "value": value,
                    "_line": line_number,
                }
            )
    return records


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float | int | None]:
    if not actual:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    errors = [prediction - observed for observed, prediction in zip(actual, predicted)]
    return {
        "n": len(errors),
        "mae": round(sum(abs(error) for error in errors) / len(errors), 4),
        "rmse": round(math.sqrt(sum(error * error for error in errors) / len(errors)), 4),
        "bias": round(sum(errors) / len(errors), 4),
    }


def _series(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[date, float]]:
    grouped: dict[tuple[str, str], dict[date, float]] = defaultdict(dict)
    for record in records:
        key = (record["city"].casefold(), record["sensor_id"])
        day = record["date"]
        if day not in grouped[key]:
            grouped[key][day] = record["value"]
    return grouped


def _features(history: dict[date, float], target_day: date) -> list[float] | None:
    offsets = (1, 2, 3, 7, 14)
    lag_values = [history.get(target_day - timedelta(days=offset)) for offset in offsets]
    if any(value is None for value in lag_values[:2]):
        return None
    recent = [
        history[target_day - timedelta(days=offset)]
        for offset in range(1, 8)
        if target_day - timedelta(days=offset) in history
    ]
    angle = 2 * math.pi * target_day.timetuple().tm_yday / 365.25
    return [
        *[float(value) if value is not None else -1.0 for value in lag_values],
        sum(recent) / len(recent) if recent else -1.0,
        math.sin(angle),
        math.cos(angle),
    ]


def _make_examples(
    series: dict[tuple[str, str], dict[date, float]],
) -> list[dict[str, Any]]:
    examples = []
    for (city_key, sensor_id), values in series.items():
        for target_day in sorted(values):
            features = _features(values, target_day)
            if features is None:
                continue
            examples.append(
                {
                    "city_key": city_key,
                    "sensor_id": sensor_id,
                    "date": target_day,
                    "actual": values[target_day],
                    "features": features,
                    "lag1": features[0],
                    "lag7": features[3] if features[3] >= 0 else None,
                }
            )
    return examples


def _best_city_holdout(examples: list[dict[str, Any]]) -> str | None:
    city_counts: dict[str, int] = defaultdict(int)
    for example in examples:
        city_counts[example["city_key"]] += 1
    eligible = {city: count for city, count in city_counts.items() if count >= 30}
    if len(eligible) < 2:
        return None
    return min(eligible, key=lambda city: (eligible[city], city))


def _score_split(
    train: list[dict[str, Any]], test: list[dict[str, Any]], label: str
) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor

    actual = [example["actual"] for example in test]
    results: dict[str, Any] = {
        "split": label,
        "train_rows": len(train),
        "test_rows": len(test),
        "city_count_train": len({e["city_key"] for e in train}),
        "city_count_test": len({e["city_key"] for e in test}),
        "baselines": {
            "previous_day": _metrics(
                [e["actual"] for e in test if e["lag1"] is not None],
                [e["lag1"] for e in test if e["lag1"] is not None],
            ),
            "previous_week": _metrics(
                [e["actual"] for e in test if e["lag7"] is not None],
                [e["lag7"] for e in test if e["lag7"] is not None],
            ),
        },
    }
    if len(train) >= 20 and test:
        model = RandomForestRegressor(
            n_estimators=300,
            min_samples_leaf=3,
            max_features=0.8,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(
            [example["features"] for example in train],
            [example["actual"] for example in train],
        )
        predictions = model.predict([example["features"] for example in test])
        results["random_forest"] = _metrics(actual, list(predictions))
        results["model_features"] = [
            "lag_1_day",
            "lag_2_days",
            "lag_3_days",
            "lag_7_days",
            "lag_14_days",
            "available_7_day_mean",
            "day_of_year_sin",
            "day_of_year_cos",
        ]
    else:
        results["random_forest"] = None
        results["model_note"] = "At least 20 training rows are required."
    return results


def benchmark(records: list[dict[str, Any]], holdout_city: str | None = None) -> dict[str, Any]:
    """Compare persistence baselines with RF on time and city holdouts."""
    examples = _make_examples(_series(records))
    if not examples:
        raise ValueError("Not enough contiguous daily data to construct lag features.")

    cutoff = sorted(example["date"] for example in examples)[int(0.8 * (len(examples) - 1))]
    temporal_train = [example for example in examples if example["date"] < cutoff]
    temporal_test = [example for example in examples if example["date"] >= cutoff]

    requested_city = holdout_city.casefold().strip() if holdout_city else _best_city_holdout(examples)
    if holdout_city and requested_city not in {example["city_key"] for example in examples}:
        raise ValueError(f"No usable lagged observations found for holdout city {holdout_city!r}.")
    city_train = [example for example in examples if example["city_key"] != requested_city]
    city_test = [example for example in examples if example["city_key"] == requested_city]
    city_split = (
        _score_split(city_train, city_test, f"unseen_city:{requested_city}")
        if requested_city and city_test
        else None
    )

    return {
        "target": "Daily station-level PM2.5 concentration; this is not AQI.",
        "unit": "source units (normally µg/m³); inspect source metadata before comparing sensors",
        "method": "Next-calendar-day prediction using only prior observations and day-of-year.",
        "rows_with_lag_features": len(examples),
        "time_cutoff": cutoff.isoformat(),
        "temporal_holdout": _score_split(temporal_train, temporal_test, "future_dates"),
        "city_holdout": city_split,
        "limitations": [
            "Daily values are OpenAQ daily aggregates, not raw measurements.",
            "Sensors may have different instruments, units, and upstream providers.",
            "Lag-based forecasts cannot predict abrupt events or explain causality.",
            "The city holdout is interpretable only when its city label is reliable.",
            "Results do not represent CPCB National AQI.",
        ],
    }
