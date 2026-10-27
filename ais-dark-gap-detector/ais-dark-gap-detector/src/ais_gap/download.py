"""Download NOAA MarineCadastre AIS daily files.

NOAA hosts one file per day. Naming/format has changed over the years:
  2015-2024: AIS_YYYY_MM_DD.zip      (contains one CSV)
  2025+    : AIS_YYYY_MM_DD.csv.zst  (zstd-compressed CSV; DuckDB reads it directly)
Browse https://hub.marinecadastre.gov/pages/vesseltraffic if a URL here 404s, and just drop the
downloaded file into data/raw/ - the pipeline accepts .csv, .zip and .csv.zst.
"""
import sys
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"


def candidate_urls(d: date):
    stem = f"AIS_{d:%Y_%m_%d}"
    return [f"{BASE}/{d.year}/{stem}.zip", f"{BASE}/{d.year}/{stem}.csv.zst"]


def fetch_day(d: date, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for url in candidate_urls(d):
        target = dest / url.rsplit("/", 1)[1]
        if target.exists():
            return target
        print(f"trying {url}")
        with requests.get(url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                continue
            temporary = target.with_name(target.name + ".tmp")
            try:
                with temporary.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target
    raise FileNotFoundError(f"No NOAA file found for {d}. Download manually into {dest}.")


def materialize_csv(path: Path) -> str:
    """Return something DuckDB can read_csv: extracts .zip, passes .csv/.csv.zst through."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            csv_files = [n for n in z.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]
            if len(csv_files) != 1:
                raise ValueError(f"Expected one CSV in {path}, found {len(csv_files)}")
            out = path.with_suffix(".csv")
            if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
                temporary = out.with_suffix(".csv.tmp")
                try:
                    with z.open(csv_files[0]) as source, temporary.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    temporary.replace(out)
                finally:
                    temporary.unlink(missing_ok=True)
            return str(out)
    if not (path.name.lower().endswith(".csv") or path.name.lower().endswith(".csv.zst")):
        raise ValueError(f"Unsupported AIS input format: {path}")
    return str(path)


if __name__ == "__main__":
    # python -m ais_gap.download 2023-01-15 2   (or: docker compose run --rm download 2023-01-15 2)
    if len(sys.argv) < 2:
        sys.exit('usage: python -m ais_gap.download YYYY-MM-DD [num_days]')
    start = date.fromisoformat(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    for i in range(n):
        print(fetch_day(start + timedelta(days=i), Path(__file__).resolve().parents[2] / "data" / "raw"))
