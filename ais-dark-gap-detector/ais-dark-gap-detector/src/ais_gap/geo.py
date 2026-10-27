"""Geo helpers: haversine, coastline distance, port distance, H3."""
from pathlib import Path
import numpy as np

EARTH_KM = 6371.0088

# Approximate major US port coordinates (lat, lon). Swap for the World Port Index for real work.
PORTS = {
    "Houston": (29.73, -95.27), "Galveston": (29.31, -94.79), "Port Arthur": (29.87, -93.93),
    "Lake Charles": (30.19, -93.30), "New Orleans": (29.93, -90.06), "Baton Rouge": (30.44, -91.19),
    "Gulfport": (30.36, -89.09), "Mobile": (30.69, -88.04), "Pensacola": (30.40, -87.21),
    "Tampa": (27.93, -82.45), "Corpus Christi": (27.81, -97.40), "Brownsville": (25.95, -97.39),
    "Freeport TX": (28.94, -95.31), "Port Fourchon": (29.11, -90.20), "Miami": (25.78, -80.17),
    "Port Everglades": (26.09, -80.12), "Port Canaveral": (28.41, -80.62), "Jacksonville": (30.39, -81.55),
    "Savannah": (32.08, -81.09), "Charleston": (32.78, -79.93), "Norfolk": (36.95, -76.33),
    "Baltimore": (39.25, -76.57), "NY/NJ": (40.67, -74.04), "Boston": (42.35, -71.04),
    "Los Angeles": (33.73, -118.26), "Long Beach": (33.75, -118.21), "San Diego": (32.69, -117.15),
    "Oakland": (37.80, -122.32), "Tacoma": (47.27, -122.41), "Seattle": (47.60, -122.35),
}

COAST_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
             "geojson/ne_10m_coastline.geojson")


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def destination(lat, lon, bearing_deg, dist_km):
    """Great-circle destination point."""
    lat, lon, brg = np.radians(lat), np.radians(lon), np.radians(bearing_deg)
    d = dist_km / EARTH_KM
    lat2 = np.arcsin(np.sin(lat) * np.cos(d) + np.cos(lat) * np.sin(d) * np.cos(brg))
    lon2 = lon + np.arctan2(np.sin(brg) * np.sin(d) * np.cos(lat), np.cos(d) - np.sin(lat) * np.sin(lat2))
    return np.degrees(lat2), (np.degrees(lon2) + 540) % 360 - 180


def _nearest_km(points_latlon_deg, targets_latlon_deg):
    from sklearn.neighbors import BallTree
    tree = BallTree(np.radians(targets_latlon_deg), metric="haversine")
    dist, _ = tree.query(np.radians(points_latlon_deg), k=1)
    return dist[:, 0] * EARTH_KM


def load_coast_vertices(ref_dir: Path, bbox, pad_deg=6.0) -> np.ndarray:
    """Download (once) Natural Earth 10m coastline, return Nx2 (lat, lon) vertices near the bbox."""
    import geopandas as gpd
    path = Path(ref_dir) / "ne_10m_coastline.geojson"
    if not path.exists():
        import requests
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(COAST_URL, timeout=180)
        r.raise_for_status()
        path.write_bytes(r.content)
    lon0, lat0, lon1, lat1 = bbox
    gdf = gpd.read_file(path, bbox=(lon0 - pad_deg, lat0 - pad_deg, lon1 + pad_deg, lat1 + pad_deg))
    pts = []
    for geom in gdf.geometry:
        for g in getattr(geom, "geoms", [geom]):
            xy = np.asarray(g.coords)
            if len(xy):
                pts.append(xy[:, ::-1])  # (lat, lon)
    return np.vstack(pts)


def dist_to_coast_km(lat, lon, coast_vertices):
    return _nearest_km(np.c_[lat, lon], coast_vertices)


def dist_to_port_km(lat, lon):
    return _nearest_km(np.c_[lat, lon], np.array(list(PORTS.values())))


def h3_cells(lat, lon, res):
    import h3
    return [h3.latlng_to_cell(a, b, res) for a, b in zip(lat, lon)]


def dist_to_bbox_edge_km(lat, lon, bbox):
    lon0, lat0, lon1, lat1 = bbox
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    km_per_deg_lon = 111.32 * np.cos(np.radians(lat))
    return np.minimum.reduce([
        (lat - lat0) * 111.32, (lat1 - lat) * 111.32,
        (lon - lon0) * km_per_deg_lon, (lon1 - lon) * km_per_deg_lon,
    ])
