import csv
from datetime import date, timedelta

import pytest

from aqi_lab.benchmark import benchmark, load_daily_csv


def make_records(days=120):
    records = []
    cities = ("Bhopal", "Indore", "Jabalpur")
    for city_index, city in enumerate(cities):
        for offset in range(days):
            day = date(2024, 1, 1) + timedelta(days=offset)
            records.append(
                {
                    "city": city,
                    "sensor_id": str(100 + city_index),
                    "date": day,
                    "value": 40 + city_index * 10 + (offset % 7) + offset * 0.02,
                    "_line": offset + 2,
                }
            )
    return records


def test_benchmark_reports_time_and_unseen_city_splits():
    result = benchmark(make_records(), "Jabalpur")
    assert result["target"].endswith("not AQI.")
    assert result["temporal_holdout"]["test_rows"] > 0
    assert result["temporal_holdout"]["baselines"]["previous_day"]["mae"] is not None
    assert result["temporal_holdout"]["random_forest"]["n"] > 0
    assert result["city_holdout"]["split"] == "unseen_city:jabalpur"
    assert result["city_holdout"]["city_count_train"] == 2


def test_load_daily_csv_rejects_missing_columns(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("station,value\nA,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_daily_csv(path)


def test_load_daily_csv_skips_invalid_measurements(tmp_path):
    path = tmp_path / "input.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["city", "sensor_id", "date", "value"])
        writer.writeheader()
        writer.writerow({"city": "Katni", "sensor_id": 1, "date": "2025-01-01", "value": 12})
        writer.writerow({"city": "Katni", "sensor_id": 1, "date": "bad-date", "value": 12})
        writer.writerow({"city": "Katni", "sensor_id": 1, "date": "2025-01-03", "value": "NaN"})
    assert len(load_daily_csv(path)) == 1
