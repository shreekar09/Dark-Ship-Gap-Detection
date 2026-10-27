"""Steps 2-3 + 6: build per-vessel trajectories and detect (a) gaps and (b) impossible position jumps.

Everything is done with DuckDB window functions so it scales to tens of millions of pings.
"""
import duckdb
import pandas as pd

from .config import Params
from .sql import literal

HAV = """2 * 6371.0088 * asin(sqrt(
    pow(sin(radians({lat2} - {lat1}) / 2), 2) +
    cos(radians({lat1})) * cos(radians({lat2})) * pow(sin(radians({lon2} - {lon1}) / 2), 2)))"""


def _hav(lat1, lon1, lat2, lon2):
    return HAV.format(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)


def _consecutive_pings_sql(parquet: str) -> str:
    """One row per ping with its predecessor attached (the 'trajectory' view)."""
    return f"""
    WITH t AS (
      SELECT mmsi, ts, lat, lon, sog, cog, vessel_type,
             lag(ts)   OVER w AS prev_ts,  lag(lat) OVER w AS prev_lat, lag(lon) OVER w AS prev_lon,
             lag(sog)  OVER w AS prev_sog, lag(cog) OVER w AS prev_cog
      FROM read_parquet({literal(parquet)})
      WINDOW w AS (PARTITION BY mmsi ORDER BY ts)
    ),
    d AS (
      SELECT *, epoch(ts) - epoch(prev_ts) AS dt_s,
             {_hav('prev_lat', 'prev_lon', 'lat', 'lon')} AS jump_km
      FROM t WHERE prev_ts IS NOT NULL
    )
    """


def detect_gaps(parquet: str, p: Params) -> pd.DataFrame:
    """One row per gap: where/when the vessel went silent and where it reappeared.

    Also attaches `avg_ping_s_before`: mean reporting interval over the 10 pings preceding the gap
    (a vessel that reported every few seconds then vanished is more interesting than one that
    reported hourly anyway).
    """
    thr = p.gap_hours * 3600
    sql = f"""
    WITH t AS (
      SELECT mmsi, ts, lat, lon, sog, cog, vessel_type,
             lag(ts) OVER w AS prev_ts, lag(lat) OVER w AS prev_lat, lag(lon) OVER w AS prev_lon,
             lag(sog) OVER w AS prev_sog, lag(cog) OVER w AS prev_cog
      FROM read_parquet({literal(parquet)}) WINDOW w AS (PARTITION BY mmsi ORDER BY ts)
    ),
    d AS (
      SELECT *, epoch(ts) - epoch(prev_ts) AS dt_s,
             {_hav('prev_lat', 'prev_lon', 'lat', 'lon')} AS jump_km
      FROM t WHERE prev_ts IS NOT NULL
    ),
    e AS (
      SELECT *, avg(dt_s) OVER (PARTITION BY mmsi ORDER BY ts ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING)
                AS avg_ping_s_before
      FROM d
    )
    SELECT row_number() OVER (ORDER BY mmsi, prev_ts) AS gap_id,
           mmsi, vessel_type,
           prev_ts AS start_ts, prev_lat AS start_lat, prev_lon AS start_lon,
           prev_sog AS sog_before, prev_cog AS cog_before,
           ts AS end_ts, lat AS end_lat, lon AS end_lon, sog AS sog_after, cog AS cog_after,
           dt_s / 3600.0 AS duration_h, jump_km,
           jump_km / (dt_s / 3600.0) / 1.852 AS implied_kn,
           avg_ping_s_before
    FROM e WHERE dt_s >= {thr}
    ORDER BY gap_id
    """
    return duckdb.sql(sql).df()


def detect_spoof_jumps(parquet: str, p: Params) -> pd.DataFrame:
    """Consecutive pings (within the gap threshold) that imply physically impossible speed.

    A vessel that alternates between two distant positions (two transmitters sharing an MMSI, or
    replayed/spoofed tracks) produces a burst of these.
    """
    sql = _consecutive_pings_sql(parquet) + f"""
    SELECT mmsi, prev_ts AS ts_from, ts AS ts_to, prev_lat AS lat_from, prev_lon AS lon_from,
           lat AS lat_to, lon AS lon_to, dt_s, jump_km,
           jump_km / (dt_s / 3600.0) / 1.852 AS implied_kn
    FROM d
    WHERE dt_s >= 1 AND dt_s < {p.gap_hours * 3600}
      AND jump_km >= {p.spoof_min_jump_km}
      AND jump_km / (dt_s / 3600.0) / 1.852 > {p.spoof_max_knots}
    ORDER BY mmsi, ts
    """
    return duckdb.sql(sql).df()


def spoof_candidates(jumps: pd.DataFrame, min_jumps: int = 3) -> pd.DataFrame:
    """Aggregate per MMSI: repeated impossible jumps = strong spoofing / duplicate-identity signal."""
    if jumps.empty:
        return pd.DataFrame(columns=["mmsi", "n_jumps", "max_implied_kn", "max_jump_km"])
    g = jumps.groupby("mmsi").agg(n_jumps=("implied_kn", "size"), max_implied_kn=("implied_kn", "max"),
                                  max_jump_km=("jump_km", "max")).reset_index()
    return g[g.n_jumps >= min_jumps].sort_values("n_jumps", ascending=False)
