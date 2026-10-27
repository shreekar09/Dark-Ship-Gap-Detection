"""Step 8: maps. Interactive folium HTML + a static PNG for the README."""
from pathlib import Path
import numpy as np
import pandas as pd

from . import geo


def _color(score):
    # green -> red
    r = int(255 * min(max(score, 0), 1)); g = int(200 * (1 - min(max(score, 0), 1)))
    return f"#{r:02x}{g:02x}40"


def interactive_map(gaps: pd.DataFrame, jumps: pd.DataFrame, p, out_html: Path):
    import folium
    import h3
    lon0, lat0, lon1, lat1 = p.bbox
    m = folium.Map(location=[(lat0 + lat1) / 2, (lon0 + lon1) / 2], zoom_start=6, tiles="OpenStreetMap")

    # H3 density of gap start points
    dens = gaps.groupby("h3_start").size().rename("n").reset_index()
    layer = folium.FeatureGroup(name="Gap density (H3)", show=True)
    mx = dens.n.max() if len(dens) else 1
    for r in dens.itertuples():
        boundary = [(a, b) for a, b in h3.cell_to_boundary(r.h3_start)]
        folium.Polygon(boundary, weight=0.5, color="#444", fill=True, fill_opacity=0.15 + 0.5 * r.n / mx,
                       fill_color="#d6301d", tooltip=f"{r.n} gaps").add_to(layer)
    layer.add_to(m)

    # Top-ranked gaps: line from last-seen to reappearance
    top = gaps[~(gaps.near_edge | gaps.in_port_powerdown)].head(p.top_n_map)
    lg = folium.FeatureGroup(name=f"Top {len(top)} ranked gaps", show=True)
    for r in top.itertuples():
        tip = (f"MMSI {r.mmsi} | {r.vessel_group} | {r.duration_h:.1f} h dark | SOG before {r.sog_before:.1f} kn<br>"
               f"coast {r.dist_coast_km:.0f} km, port {r.dist_port_km:.0f} km | rule {r.rule_score:.2f}, IF {r.iforest_score:.2f}")
        col = _color(r.rule_score)
        folium.PolyLine([(r.start_lat, r.start_lon), (r.end_lat, r.end_lon)], color=col, weight=3,
                        dash_array="6", tooltip=tip).add_to(lg)
        folium.CircleMarker((r.start_lat, r.start_lon), radius=4, color=col, fill=True, tooltip=tip).add_to(lg)
    lg.add_to(m)

    # Spoof jumps
    if len(jumps):
        ls = folium.FeatureGroup(name="Impossible-speed jumps (spoofing?)", show=False)
        for r in jumps.head(500).itertuples():
            folium.PolyLine([(r.lat_from, r.lon_from), (r.lat_to, r.lon_to)], color="#7b2cbf", weight=2,
                            tooltip=f"MMSI {r.mmsi}: {r.jump_km:.0f} km in {r.dt_s:.0f}s = {r.implied_kn:.0f} kn").add_to(ls)
        ls.add_to(m)
    folium.LayerControl().add_to(m)
    m.save(str(out_html))


def static_map(gaps: pd.DataFrame, coast_vertices, p, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lon0, lat0, lon1, lat1 = p.bbox
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(coast_vertices[:, 1], coast_vertices[:, 0], ",", color="#888")
    ok = gaps[~(gaps.near_edge | gaps.in_port_powerdown)]
    if not ok.empty:
        sc = ax.scatter(ok.start_lon, ok.start_lat, c=ok.rule_score,
                        s=8 + 80 * ok.duration_h / ok.duration_h.max(),
                        cmap="YlOrRd", alpha=0.8, edgecolor="k", linewidth=0.2, vmin=0, vmax=1)
        fig.colorbar(sc, ax=ax, shrink=0.7, label="rule score")
    top = ok.head(15)
    for r in top.itertuples():
        ax.plot([r.start_lon, r.end_lon], [r.start_lat, r.end_lat], "--", color="crimson", lw=0.8)
    ax.set_xlim(lon0, lon1); ax.set_ylim(lat0, lat1); ax.set_aspect(1 / np.cos(np.radians((lat0 + lat1) / 2)))
    ax.set_title("AIS gaps (start of silence); colour = rule score, size = duration; dashed = top-15 reappearance")
    fig.tight_layout(); fig.savefig(out_png, dpi=150); plt.close(fig)


def error_plot(summary: pd.DataFrame, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if summary.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(0.5, 0.5, "No reconstructable gaps", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
    else:
        ax = summary.drop(columns="n").plot(kind="bar", figsize=(7, 4))
        fig = ax.figure
        ax.set_ylabel("median position error (nm)"); ax.set_xlabel("gap duration")
        ax.set_title("Where does the vessel reappear? Prediction error vs gap length")
        plt.xticks(rotation=0)
    fig.tight_layout(); fig.savefig(out_png, dpi=150); plt.close(fig)
