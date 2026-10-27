"""Central configuration. Edit here or override via CLI flags in run_pipeline.py."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REF = DATA / "ref"
OUT = ROOT / "outputs"

# Gulf of Mexico: dense traffic, good terrestrial AIS coverage near the coast.
# (lon_min, lat_min, lon_max, lat_max)
DEFAULT_BBOX = (-98.0, 24.0, -80.0, 31.0)

NM_PER_KM = 1 / 1.852


@dataclass
class Params:
    bbox: tuple = DEFAULT_BBOX
    class_a_only: bool = True          # Class B (small craft) reports sparsely -> noisy gaps
    gap_hours: float = 2.0             # silence longer than this = a "gap"
    spoof_max_knots: float = 50.0      # implied speed above this = impossible jump
    spoof_min_jump_km: float = 1.0     # ignore GPS jitter at tiny dt
    edge_margin_km: float = 25.0       # gaps starting/ending near bbox edge = left the AOI
    port_radius_km: float = 5.0        # "in port" radius
    h3_res: int = 5
    recon_max_hours: float = 6.0       # only reconstruct gaps up to this long
    kalman_lookback_min: int = 30
    top_n_map: int = 200
