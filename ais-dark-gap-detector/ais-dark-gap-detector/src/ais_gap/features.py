"""Step 4: per-gap behavioural features."""
import numpy as np
import pandas as pd

from . import geo
from .config import Params, REF


def vessel_group(t):
    if pd.isna(t):
        return "unknown"
    t = int(t)
    if t == 30: return "fishing"
    if t in (31, 32, 52): return "tug_tow"
    if t in (36, 37): return "pleasure"
    if 60 <= t <= 69: return "passenger"
    if 70 <= t <= 79: return "cargo"
    if 80 <= t <= 89: return "tanker"
    return "other"


def add_features(gaps: pd.DataFrame, p: Params, coast_vertices=None) -> pd.DataFrame:
    g = gaps.copy()
    if g.empty:
        for column in ("dist_coast_km", "dist_port_km", "start_hour", "cog_change"):
            g[column] = pd.Series(dtype=float)
        for column in ("vessel_group", "h3_start"):
            g[column] = pd.Series(dtype=str)
        for column in ("near_edge", "in_port_powerdown", "position_jump"):
            g[column] = pd.Series(dtype=bool)
        return g
    if coast_vertices is None:
        coast_vertices = geo.load_coast_vertices(REF, p.bbox)

    g["dist_coast_km"] = geo.dist_to_coast_km(g.start_lat, g.start_lon, coast_vertices)
    g["dist_port_km"] = geo.dist_to_port_km(g.start_lat, g.start_lon)
    g["vessel_group"] = g.vessel_type.map(vessel_group)
    g["start_hour"] = pd.to_datetime(g.start_ts).dt.hour
    g["h3_start"] = geo.h3_cells(g.start_lat, g.start_lon, p.h3_res)

    # Cog change across the gap (smallest angle) - a turn while dark is a classic evasion pattern
    g["cog_change"] = ((g.cog_before - g.cog_after + 180) % 360 - 180).abs()

    # Benign-explanation flags
    edge_start = geo.dist_to_bbox_edge_km(g.start_lat, g.start_lon, p.bbox)
    edge_end = geo.dist_to_bbox_edge_km(g.end_lat, g.end_lon, p.bbox)
    g["near_edge"] = (np.minimum(edge_start, edge_end) < p.edge_margin_km)        # probably left/entered the AOI
    g["in_port_powerdown"] = (g.dist_port_km < p.port_radius_km) & (g.sog_before.fillna(0) < 1.0)  # moored, transponder off
    g["position_jump"] = g.implied_kn > p.spoof_max_knots                          # reappears impossibly far away
    return g
