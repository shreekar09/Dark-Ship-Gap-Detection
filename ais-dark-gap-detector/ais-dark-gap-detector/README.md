# AIS Dark Gap Detector

An analyst triage pipeline for AIS reporting gaps in NOAA MarineCadastre vessel positions. It cleans raw AIS files, finds periods of radio silence and impossible-speed jumps, ranks gaps, and compares simple reappearance predictions.

**A gap is not evidence of wrongdoing.** Receiver coverage, port stays, equipment faults, and travel outside the selected area can all explain missing reports. Scores are for investigation, not attribution.

![Gap map from a NOAA data run](outputs/gap_map.png)

## Requirements

- Docker with Compose, or Python 3.12 with the packages in requirements.txt
- NOAA daily AIS files in data/raw/ (.csv, .zip containing one CSV, or .csv.zst)

A full day of NOAA data may need several GB of memory and several minutes to process. The first run may download a Natural Earth coastline GeoJSON into data/ref/.

## Quick start

From the directory containing this README, place a NOAA AIS file in data/raw/ and run:

~~~sh
docker compose build
docker compose run --rm pipeline --input "data/raw/*.csv.zst" --out outputs
docker compose run --rm test
~~~

Quote globs so they expand inside the container. You can also download one or more historical daily files with:

~~~sh
docker compose run --rm download 2023-01-15 2
docker compose run --rm pipeline --input "data/raw/*.zip" --out outputs
~~~

If the downloader's URL pattern no longer works, get files from the [NOAA MarineCadastre vessel traffic portal](https://hub.marinecadastre.gov/pages/vesseltraffic) and place them in data/raw/.

For local Python:

~~~sh
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python run_pipeline.py --input data/raw/AIS_2023_01_15.zip --out outputs
python -m pytest -q tests
~~~

Use Python 3.12 for the local setup. Run python run_pipeline.py --help for all CLI options.

## Inputs and options

Each CSV needs MMSI, BaseDateTime, LAT, LON, SOG, and COG. VesselType and TransceiverClass are optional. Column names are matched without regard to case, spaces, or underscores. The pipeline filters invalid coordinates, speed sentinels, invalid MMSIs, duplicate timestamps, and positions outside the selected area.

The default area is the Gulf of Mexico (-98 24 -80 31, in lon_min lat_min lon_max lat_max order). The minimum gap is two hours; Class B messages are excluded unless --include-class-b is set.

~~~sh
# Example: Southern California with a three-hour minimum gap
docker compose run --rm pipeline --input "data/raw/*.csv.zst" --bbox -122 32 -117 35 --gap-hours 3 --out outputs
~~~

Set DUCKDB_MEMORY_LIMIT if DuckDB needs a lower memory cap. The Compose default is 6GB.

## Outputs

Each run writes into the directory given by --out:

| File | Contents |
| --- | --- |
| clean_pings.parquet | Filtered, deduplicated AIS positions |
| gaps_scored.csv | Gaps, features, context flags, scores, and ranks |
| spoof_jumps.csv | Consecutive positions whose implied speed exceeds the threshold |
| spoof_candidates.csv | MMSIs with at least three impossible-speed jumps |
| reconstruction_errors.csv | Per-gap prediction errors in nautical miles |
| reconstruction_summary.csv | Median error by duration for underway vessels |
| summary.json | Row counts and agreement between scoring methods |
| gap_map.html, gap_map.png | Interactive and static gap maps |
| reconstruction_error.png | Prediction error chart |

Open outputs/gap_map.html for the interactive map. The rank is a relative ordering, not a calibrated probability. near_edge and in_port_powerdown mark plausible benign explanations and lower those gaps in the ranking. A position_jump indicates implausible displacement; it does not by itself prove spoofing.

Explore the results with the DuckDB CLI:

~~~sh
docker compose run --rm duckdb -init sql/explore.sql
~~~

## Pipeline

1. ingest.py reads source files with DuckDB, casts fields, filters bad values and the selected area, and keeps one ping per MMSI and timestamp.
2. gaps.py uses window functions to find silence periods and impossible-speed jumps between consecutive pings.
3. features.py adds duration, speed, coast and port proximity, prior reporting interval, H3 cell, and context flags.
4. scoring.py combines a hand-weighted rule score with an Isolation Forest anomaly score.
5. reconstruct.py predicts reappearance using a stationary baseline, dead reckoning, and a constant-velocity Kalman filter.
6. viz.py writes maps and an error chart.

## Limits and data handling

- NOAA's terrestrial AIS receiver coverage is uneven offshore. Many apparent gaps may be coverage artifacts.
- The major-port coordinates and nearest Natural Earth coastline **vertices** are approximate and should not be used for navigation or legal boundaries.
- Rule weights, the 50-knot jump threshold, and Kalman noise settings are heuristics. Validate them on representative, labeled data before operational use.
- Output contains MMSIs and vessel locations. Handle real data according to your data policy.

## Project layout

~~~text
run_pipeline.py         CLI and pipeline orchestration
src/ais_gap/            Ingest, detection, features, scoring, reconstruction, maps
tests/                 Focused unit tests
sql/explore.sql         Example DuckDB queries
data/raw/               Input AIS files (ignored by Git)
data/ref/               Cached coastline data (ignored by Git)
outputs/                Results (ignored by Git)
~~~
