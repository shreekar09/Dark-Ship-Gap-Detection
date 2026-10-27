import sys
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ais_gap import features, geo, reconstruct, scoring
from ais_gap.config import Params
from ais_gap.download import materialize_csv
from ais_gap.sql import identifier, literal


def test_haversine_known_distance():
    # 1 degree of latitude ~ 111.19 km
    assert abs(geo.haversine_km(0, 0, 1, 0) - 111.19) < 0.2


def test_destination_roundtrip():
    lat, lon = geo.destination(29.0, -90.0, 90.0, 100.0)
    assert abs(geo.haversine_km(29.0, -90.0, lat, lon) - 100.0) < 0.01


def test_kalman_recovers_constant_velocity():
    t = np.arange(0, 1800, 60.0)
    lat = 28.0 + t * 0.0 / 111000
    lon = -90.0 + (6.0 * t) / (111320 * np.cos(np.radians(28.0)))  # 6 m/s due east
    plat, plon = reconstruct.kalman_predict(t, lat, lon, 3600)
    expected_lon = lon[-1] + (6.0 * 3600) / (111320 * np.cos(np.radians(28.0)))
    assert geo.haversine_km(plat, plon, 28.0, expected_lon) < 0.5


def test_rule_score_zero_for_benign():
    g = pd.DataFrame({"duration_h": [10, 10], "sog_before": [12, 12], "dist_port_km": [100, 100],
                      "avg_ping_s_before": [60, 60], "jump_km": [50, 50],
                      "near_edge": [False, True], "in_port_powerdown": [False, False]})
    s = scoring.rule_score(g)
    assert s.iloc[0] > 0.9 and s.iloc[1] == 0.0


def test_no_gaps_produces_empty_scored_table():
    gaps = pd.DataFrame(columns=["gap_id", "start_lat", "start_lon"])
    enriched = features.add_features(gaps, Params())
    scored = scoring.score_gaps(enriched)
    assert scored.empty
    assert {"near_edge", "rule_score", "iforest_score", "ensemble_rank_score"} <= set(scored)
    assert scoring.compare_methods(scored) == {
        "k": 0, "top_k_overlap": None, "jaccard": 0.0, "spearman": None
    }
    assert reconstruct.summarize_errors(pd.DataFrame()).empty


def test_sql_quoting_handles_paths_and_headers():
    assert literal("C:/AIS/O'Brien.csv") == "'C:/AIS/O''Brien.csv'"
    assert identifier('Vessel "name"') == '"Vessel ""name"""'


def test_zip_csv_is_extracted_beside_archive(tmp_path):
    archive = tmp_path / "ais.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../unexpected/pings.csv", "MMSI,LAT\n123,28\n")
    extracted = Path(materialize_csv(archive))
    assert extracted == tmp_path / "ais.csv"
    assert extracted.read_text() == "MMSI,LAT\n123,28\n"
    assert not (tmp_path.parent / "unexpected").exists()
