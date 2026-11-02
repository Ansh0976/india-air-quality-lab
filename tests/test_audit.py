from aqi_lab.audit import flatten_daily_rows, pm25_sensors, select_locations, summarize_rows


def location(location_id, name, city, sensors, mobile=False):
    return {
        "id": location_id,
        "name": name,
        "locality": city,
        "country": {"code": "IN", "name": "India"},
        "isMobile": mobile,
        "sensors": sensors,
    }


def sensor(sensor_id, parameter="pm25", units="µg/m³"):
    return {"id": sensor_id, "parameter": {"name": parameter, "units": units}}


def daily(date_text, value, coverage=100):
    return {
        "value": value,
        "period": {"datetimeFrom": {"local": f"{date_text}T00:00:00+05:30"}},
        "coverage": {
            "expectedCount": 24,
            "observedCount": 24,
            "percentCoverage": coverage,
        },
    }


def test_selects_stationary_pm25_and_filters_city():
    locations = [
        location(1, "Katni Civil Lines", "Katni", [sensor(11)]),
        location(2, "Delhi PM10", "Delhi", [sensor(22, "pm10")]),
        location(3, "Mobile Katni", "Katni", [sensor(33)], mobile=True),
    ]
    selected = select_locations(locations, "katni")
    assert [item["id"] for item in selected] == [1]
    assert [item["id"] for item in pm25_sensors(selected[0])] == [11]


def test_flatten_preserves_units_coverage_and_local_day():
    station = location(1, "Station", "Katni", [sensor(11)])
    rows = flatten_daily_rows(station, sensor(11), [daily("2025-01-01", 42.5, 75)])
    assert rows == [
        {
            "location_id": 1,
            "station": "Station",
            "city": "Katni",
            "country": "IN",
            "sensor_id": 11,
            "parameter": "pm25",
            "units": "µg/m³",
            "date": "2025-01-01",
            "value": 42.5,
            "observed_count": 24,
            "expected_count": 24,
            "coverage_pct": 75.0,
            "source": "OpenAQ API v3",
        }
    ]


def test_summary_distinguishes_calendar_gaps_and_missing_values():
    rows = [
        {
            "location_id": 1,
            "sensor_id": 11,
            "city": "Katni",
            "date": "2025-01-01",
            "value": 10.0,
            "coverage_pct": 100.0,
        },
        {
            "location_id": 1,
            "sensor_id": 11,
            "city": "Katni",
            "date": "2025-01-03",
            "value": None,
            "coverage_pct": 50.0,
        },
    ]
    summary = summarize_rows(rows, "2024-12-31", "2025-01-04")
    assert summary["station_count"] == 1
    assert summary["calendar_gap_days"] == 3
    assert summary["sensors"][0]["missing_value_days"] == 1
    assert summary["sensors"][0]["record_date_coverage_pct"] == 40.0
    assert summary["sensors"][0]["value_date_coverage_pct"] == 20.0
    assert summary["sensors"][0]["mean_daily_coverage_pct"] == 75.0
    assert summary["sensors"][0]["mean_pm25"] == 10.0
