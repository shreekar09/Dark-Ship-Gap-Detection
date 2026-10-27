"""Step 7: mini trajectory reconstruction.

For each gap we "forget" where the vessel reappeared and predict it from what we knew at the
moment it went silent, then measure the error. Three predictors, simplest to smartest:

  stationary   : vessel stays where it was last seen (naive baseline)
  dead_reckon  : continue at last SOG/COG for the whole gap (great circle)
  kalman       : constant-velocity Kalman filter over the last N minutes of pings, then predict
                 forward (smooths noisy SOG/COG and position jitter)

Expect error to grow with gap length: ships manoeuvre, so a 6 h extrapolation is a weak guess.
That curve is itself a finding.
"""
import duckdb
import numpy as np
import pandas as pd

from . import geo
from .config import Params
from .sql import literal

R = 6371008.8  # m
ERROR_COLUMNS = ["gap_id", "duration_h", "sog_before", "err_stationary_nm",
                 "err_dead_reckon_nm", "err_kalman_nm", "duration_bucket"]


def _to_xy(lat, lon, lat0, lon0):
    x = np.radians(np.asarray(lon) - lon0) * R * np.cos(np.radians(lat0))
    y = np.radians(np.asarray(lat) - lat0) * R
    return x, y


def _to_latlon(x, y, lat0, lon0):
    return lat0 + np.degrees(y / R), lon0 + np.degrees(x / (R * np.cos(np.radians(lat0))))


def kalman_predict(ts_s, lat, lon, horizon_s, meas_sigma_m=25.0, accel_sigma=0.001):
    """Constant-velocity Kalman filter over irregularly spaced pings; returns predicted (lat, lon)
    `horizon_s` after the last ping. State = [x, y, vx, vy] in a local metric frame."""
    lat0, lon0 = lat[-1], lon[-1]
    x, y = _to_xy(lat, lon, lat0, lon0)
    t = np.asarray(ts_s, float) - ts_s[0]
    if len(t) < 2 or t[-1] - t[0] <= 0:
        return lat0, lon0
    v0 = ((x[1] - x[0]) / max(t[1] - t[0], 1e-6), (y[1] - y[0]) / max(t[1] - t[0], 1e-6))
    s = np.array([x[0], y[0], v0[0], v0[1]])
    P = np.diag([meas_sigma_m**2, meas_sigma_m**2, 5.0**2, 5.0**2])
    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
    Rm = np.eye(2) * meas_sigma_m**2

    def F(dt):
        m = np.eye(4); m[0, 2] = m[1, 3] = dt
        return m

    def Q(dt):  # white-noise acceleration model
        q = accel_sigma**2
        a, b, c = dt**4 / 4, dt**3 / 2, dt**2
        return q * np.array([[a, 0, b, 0], [0, a, 0, b], [b, 0, c, 0], [0, b, 0, c]])

    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        s, P = F(dt) @ s, F(dt) @ P @ F(dt).T + Q(dt)
        z = np.array([x[i], y[i]])
        S = H @ P @ H.T + Rm
        K = P @ H.T @ np.linalg.inv(S)
        s = s + K @ (z - H @ s)
        P = (np.eye(4) - K @ H) @ P
    s = F(horizon_s) @ s
    return _to_latlon(s[0], s[1], lat0, lon0)


def reconstruct(parquet: str, gaps: pd.DataFrame, p: Params) -> pd.DataFrame:
    g = gaps[(gaps.duration_h <= p.recon_max_hours) & ~gaps.near_edge & ~gaps.position_jump].copy()
    if g.empty:
        return pd.DataFrame(columns=ERROR_COLUMNS)
    con = duckdb.connect()
    con.register("gaps_tbl", g[["gap_id", "mmsi", "start_ts"]])
    pings = con.sql(f"""
        SELECT gt.gap_id, epoch(p.ts) AS t, p.lat, p.lon
        FROM gaps_tbl gt JOIN read_parquet({literal(parquet)}) p
          ON p.mmsi = gt.mmsi AND p.ts <= gt.start_ts
         AND p.ts >= gt.start_ts - INTERVAL {p.kalman_lookback_min} MINUTE
        ORDER BY gt.gap_id, p.ts
    """).df()
    con.close()
    by_gap = {k: v for k, v in pings.groupby("gap_id")}

    rows = []
    for r in g.itertuples():
        hrs = r.duration_h
        # stationary
        stat_err = geo.haversine_km(r.start_lat, r.start_lon, r.end_lat, r.end_lon)
        # dead reckoning
        if pd.notna(r.cog_before) and pd.notna(r.sog_before):
            dlat, dlon = geo.destination(r.start_lat, r.start_lon, r.cog_before, r.sog_before * 1.852 * hrs)
            dr_err = geo.haversine_km(dlat, dlon, r.end_lat, r.end_lon)
        else:
            dr_err = np.nan
        # kalman
        kal_err = np.nan
        pg = by_gap.get(r.gap_id)
        if pg is not None and len(pg) >= 3:
            klat, klon = kalman_predict(pg.t.values, pg.lat.values, pg.lon.values, hrs * 3600)
            kal_err = geo.haversine_km(klat, klon, r.end_lat, r.end_lon)
        rows.append((r.gap_id, hrs, r.sog_before, stat_err / 1.852, dr_err / 1.852, kal_err / 1.852))
    out = pd.DataFrame(rows, columns=["gap_id", "duration_h", "sog_before",
                                      "err_stationary_nm", "err_dead_reckon_nm", "err_kalman_nm"])
    out["duration_bucket"] = pd.cut(out.duration_h, [0, 3, 4, 5, 6.01], labels=["<3h", "3-4h", "4-5h", "5-6h"])
    return out


def summarize_errors(rec: pd.DataFrame) -> pd.DataFrame:
    if rec.empty:
        return pd.DataFrame(columns=["err_stationary_nm", "err_dead_reckon_nm", "err_kalman_nm", "n"])
    cols = ["err_stationary_nm", "err_dead_reckon_nm", "err_kalman_nm"]
    # only vessels that were underway - predicting a moored ship is trivial
    moving = rec[rec.sog_before >= 3]
    return moving.groupby("duration_bucket", observed=True)[cols].median().round(2).assign(
        n=moving.groupby("duration_bucket", observed=True).size())
