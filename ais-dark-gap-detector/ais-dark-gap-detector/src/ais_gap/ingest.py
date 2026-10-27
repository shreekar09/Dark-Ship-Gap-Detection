"""Step 1: clean raw NOAA AIS CSVs with DuckDB SQL and write a compact Parquet file."""
import os
from pathlib import Path
import duckdb

from .config import Params
from .download import materialize_csv
from .sql import identifier, literal

# Normalised header (lower-case, no underscores/spaces) -> our canonical name.
# NOAA has used BaseDateTime/LAT/LON/SOG/COG...; this tolerates case/underscore variations.
ALIASES = {
    "mmsi": "mmsi", "basedatetime": "ts", "datetime": "ts", "timestamp": "ts",
    "lat": "lat", "latitude": "lat", "lon": "lon", "longitude": "lon",
    "sog": "sog", "cog": "cog", "vesseltype": "vessel_type", "transceiverclass": "tclass",
}
REQUIRED = {"mmsi", "ts", "lat", "lon", "sog", "cog"}


def _norm(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "")


def clean_to_parquet(inputs, out_parquet: Path, p: Params) -> dict:
    files = [materialize_csv(Path(f)) for f in inputs]
    file_list = "[" + ", ".join(literal(f) for f in files) + "]"
    lon0, lat0, lon1, lat1 = p.bbox
    con = duckdb.connect()
    # Containers often have tight RAM: let callers cap DuckDB and give it a spill directory.
    if os.environ.get("DUCKDB_MEMORY_LIMIT"):
        con.execute(f"SET memory_limit={literal(os.environ['DUCKDB_MEMORY_LIMIT'])}")
    con.execute(f"SET temp_directory={literal(os.environ.get('DUCKDB_TEMP_DIR', '/tmp/duckdb_tmp'))}")

    # Read everything as text and cast ourselves: robust to odd rows and schema drift between years.
    read = f"read_csv({file_list}, header=true, all_varchar=true, union_by_name=true, ignore_errors=true)"
    header = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {read}").fetchall()]
    colmap = {}
    for h in header:
        canon = ALIASES.get(_norm(h))
        if canon and canon not in colmap:
            colmap[canon] = h
    missing = REQUIRED - set(colmap)
    if missing:
        raise SystemExit(f"Input is missing required columns {sorted(missing)}. Found: {header}")

    q = lambda c: identifier(colmap[c])
    vtype = f"TRY_CAST({q('vessel_type')} AS INTEGER)" if "vessel_type" in colmap else "NULL::INTEGER"
    tclass = q("tclass") if "tclass" in colmap else "NULL::VARCHAR"

    con.execute(f"""
        CREATE VIEW raw AS
        SELECT TRY_CAST({q('mmsi')} AS BIGINT) AS mmsi, TRY_CAST({q('ts')} AS TIMESTAMP) AS ts,
               TRY_CAST({q('lat')} AS DOUBLE) AS lat, TRY_CAST({q('lon')} AS DOUBLE) AS lon,
               TRY_CAST({q('sog')} AS DOUBLE) AS sog, TRY_CAST({q('cog')} AS DOUBLE) AS cog,
               {vtype} AS vessel_type, {tclass} AS tclass
        FROM {read}
    """)
    n_raw = con.execute("SELECT count(*) FROM raw").fetchone()[0]

    # Cleaning rules (each maps to a real AIS data-quality issue):
    #  - unparseable timestamp/number -> dropped (TRY_CAST gave NULL)
    #  - MMSI: 9 digits with a valid maritime identification digit (2xx-7xx) -> drops test/SAR/aid-to-nav MMSIs
    #  - lat/lon in range (91 / 181 mean "not available") and inside the area of interest
    #  - SOG 0-102.2 kn (102.3 = not available); COG >= 360 = not available -> NULL
    #  - Class A only (optional): Class B small craft report sparsely, so gaps are mostly noise
    #  - one row per (mmsi, ts): overlapping receivers produce duplicates
    class_clause = "AND (tclass = 'A' OR tclass IS NULL)" if p.class_a_only else ""
    con.execute(f"""
        COPY (
          SELECT mmsi, ts, lat, lon, sog, CASE WHEN cog >= 360 THEN NULL ELSE cog END AS cog, vessel_type
          FROM raw
          WHERE ts IS NOT NULL
            AND mmsi BETWEEN 200000000 AND 799999999
            AND lat BETWEEN {lat0} AND {lat1} AND lon BETWEEN {lon0} AND {lon1}
            AND sog BETWEEN 0 AND 102.2
            {class_clause}
          QUALIFY row_number() OVER (PARTITION BY mmsi, ts ORDER BY ts) = 1
          ORDER BY mmsi, ts
        ) TO {literal(out_parquet)} (FORMAT PARQUET)
    """)
    n_clean, n_vessels = con.execute(
        f"SELECT count(*), count(DISTINCT mmsi) FROM read_parquet({literal(out_parquet)})").fetchone()
    return {"raw_rows": n_raw, "clean_rows": n_clean, "vessels": n_vessels}
