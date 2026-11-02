# India Air Quality Lab

A reproducible study of **whether daily PM2.5 station data in India is complete enough to support useful next-day forecasts—and how well simple models generalize to future dates and unseen cities**.

This is deliberately not a generic AQI dashboard. The first work is to check station coverage, missing days, units, source metadata, and daily aggregate completeness. Forecasts are a separate experiment and are reported as **PM2.5 concentration**, not as India's National AQI.

## What it does

- Discovers stationary Indian OpenAQ locations that report PM2.5.
- Filters candidate stations by city/locality and retains provider, owner, units, and license metadata for review.
- Collects per-day aggregates for selected stations and calculates calendar gaps separately from the API's within-day coverage.
- Benchmarks persistence baselines against a Random Forest using lagged observations.
- Evaluates both future-date holdouts and a city withheld entirely from training.
- Keeps API keys out of code, URLs, logs, generated reports, and Git.

## Current status

The pipeline and tests are implemented. The OpenAQ feasibility check found **765 Indian locations with PM2.5 sensors in the returned response**; this is not yet a verified national total or evidence of complete time-series coverage. Real station-level results have not been generated or claimed in this repository. Run the audit first and let its findings determine which cities and modelling experiments are justified.

## Requirements

- Python 3.10 or later.
- An OpenAQ account and API key for live data collection.
- `pandas` and `scikit-learn` for model benchmarking; the API client and coverage audit use the Python standard library.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e ".[analysis,test]"
```

Set the key for the current PowerShell session. Type or paste it only at the secure prompt; the key will not be echoed:

```powershell
$secure = Read-Host "OpenAQ API key" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:OPENAQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    Remove-Variable secure, ptr
}
```

Do not put the key in `.env` if you are unsure how to protect it, a command-line argument, source code, a screenshot, or a public issue. `.env` is ignored by Git; the API client reads `OPENAQ_API_KEY` from the process environment.

## Workflow

### 1. Discover candidate stations

```powershell
aqi-lab discover --city Katni
aqi-lab discover --city Bhopal
```

This scans OpenAQ's India station pages and saves metadata to `data/metadata/station-candidates.json`. It does not collect pollutant readings. If Katni has no matching stations, the output reports no match; do not infer local air quality from a distant station.

### 2. Audit a small station sample

Choose a `location_id` from the candidate file. Start with one station and a short period:

```powershell
aqi-lab audit --location-id 12345 --start 2025-01-01 --end 2025-03-31
```

Or compare a small number of stations in one city:

```powershell
aqi-lab audit --city Bhopal --max-stations 3 --start 2025-01-01 --end 2025-03-31
```

The command saves normalized daily rows to `data/processed/daily-pm25.csv` and an audit summary to `data/processed/coverage-summary.json`. Generated data and reports are ignored by Git by default. Review station licenses and upstream providers before sharing any derived dataset.

### 3. Run a forecast benchmark

```powershell
aqi-lab benchmark --input data/processed/daily-pm25.csv --holdout-city Jabalpur
```

The benchmark compares previous-day and previous-week persistence with a fixed-seed Random Forest. It uses only information dated before each prediction day, requires contiguous calendar lag dates, and reports MAE, RMSE, and bias. The time split tests future dates; the city split excludes the chosen city from model training. Both splits are reported alongside their sample counts.

## Interpreting the results

- Record-date coverage uses the entire requested date range, including leading and trailing gaps. Value-date coverage excludes missing daily values. Neither is the same as the number of valid hourly observations within each daily average.
- OpenAQ daily records include source units and daily coverage metadata. Never compare concentrations across sensors until units, providers, and measurement methods have been reviewed.
- OpenAQ describes its daily aggregate as an average of hourly averages. It is not necessarily a simple arithmetic mean of raw hourly readings.
- A PM2.5 concentration forecast is not an AQI forecast. India's National AQI depends on pollutant-specific breakpoints, averaging periods, and rules for the pollutants available.
- Good performance on one city or date range does not establish generalization. Report weak and negative results too.
- Do not use a random row split: observations from the same time series would leak across train and test.

## Data source, attribution, and privacy

Measurements are retrieved from the [OpenAQ API v3](https://docs.openaq.org/). OpenAQ provides station, sensor, provider, owner, license, and coverage metadata. Data may be subject to upstream-provider terms; review those terms and retain attribution for any data you use. OpenAQ requires attribution and registration/API-key use for programmatic access. See its [Terms of Use](https://docs.openaq.org/about/terms), [locations](https://docs.openaq.org/resources/locations), [sensors](https://docs.openaq.org/resources/sensors), and [measurement aggregation documentation](https://docs.openaq.org/resources/measurements).

Do not commit API keys, raw downloads, personal information, or generated local reports. No personal location data is collected by this project.

## Tests

```powershell
py -m pytest
```

Tests use mocked API responses and generated time series. They do not contact OpenAQ and do not claim real-world model performance.

## Limitations and next research steps

- OpenAQ coverage is incomplete and is not a census of Indian monitors.
- A city's station names and locality metadata can be inconsistent; manual validation is part of the research.
- Daily aggregation can hide intraday peaks and gaps.
- Station sensors may differ by instrument, operating organization, units, and QA practices.
- The initial model has no weather, emissions, or calendar-holiday covariates and does not infer causation.
- No empirical findings should be reported until the pipeline has been run on real data and the data-selection decisions have been documented.

## License

MIT for the code in this repository. This code license does not change the terms or licenses of third-party air-quality data.
