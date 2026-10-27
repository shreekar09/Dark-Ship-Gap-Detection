#!/usr/bin/env python
"""End-to-end: raw NOAA AIS -> clean parquet -> gaps -> features -> scores -> reconstruction -> maps.

  python run_pipeline.py --input data/raw/AIS_2023_01_15.zip data/raw/AIS_2023_01_16.zip
"""
import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from ais_gap import features, geo, gaps as G, ingest, reconstruct, scoring, viz
from ais_gap.config import DEFAULT_BBOX, OUT, REF, Params


def main():
    ap = argparse.ArgumentParser(description="Detect and rank AIS reporting gaps")
    ap.add_argument("--input", nargs="+", required=True,
                    help="NOAA AIS files (.csv / .zip / .csv.zst); globs ok")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("LON0", "LAT0", "LON1", "LAT1"), default=DEFAULT_BBOX)
    ap.add_argument("--gap-hours", type=float, default=2.0)
    ap.add_argument("--include-class-b", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()

    lon0, lat0, lon1, lat1 = a.bbox
    if not (-180 <= lon0 < lon1 <= 180 and -90 <= lat0 < lat1 <= 90):
        ap.error("--bbox must be ordered as LON_MIN LAT_MIN LON_MAX LAT_MAX within valid coordinates")
    if a.gap_hours <= 0:
        ap.error("--gap-hours must be positive")

    p = Params(bbox=tuple(a.bbox), gap_hours=a.gap_hours, class_a_only=not a.include_class_b)
    a.out.mkdir(parents=True, exist_ok=True)

    inputs = sorted({f for pat in a.input for f in glob.glob(pat)})
    if not inputs:
        ap.error("No input files matched. Check --input paths.")

    clean = a.out / "clean_pings.parquet"
    print("[1/7] cleaning with DuckDB ...")
    stats = ingest.clean_to_parquet(inputs, clean, p)
    print("     ", stats)

    print("[2/7] detecting gaps + impossible jumps ...")
    gaps = G.detect_gaps(str(clean), p)
    jumps = G.detect_spoof_jumps(str(clean), p)
    cands = G.spoof_candidates(jumps)
    print(f"      {len(gaps)} gaps, {len(jumps)} impossible jumps, {len(cands)} spoof-candidate MMSIs")

    print("[3/7] engineering features ...")
    coast = geo.load_coast_vertices(REF, p.bbox)
    gaps = features.add_features(gaps, p, coast)

    print("[4/7] scoring (rules + Isolation Forest) ...")
    gaps = scoring.score_gaps(gaps)
    cmp = scoring.compare_methods(gaps)
    print("     ", {k: round(v, 3) if v is not None else None for k, v in cmp.items()})

    print("[5/7] reconstructing trajectories across gaps ...")
    rec = reconstruct.reconstruct(str(clean), gaps, p)
    summ = reconstruct.summarize_errors(rec)
    print(summ.to_string() if len(summ) else "      (no reconstructable gaps)")

    print("[6/7] writing tables ...")
    gaps.to_csv(a.out / "gaps_scored.csv", index=False)
    jumps.to_csv(a.out / "spoof_jumps.csv", index=False)
    cands.to_csv(a.out / "spoof_candidates.csv", index=False)
    rec.to_csv(a.out / "reconstruction_errors.csv", index=False)
    summ.to_csv(a.out / "reconstruction_summary.csv")
    summary = {**stats, "gaps": len(gaps), "gaps_after_benign_filter": int((~(gaps.near_edge | gaps.in_port_powerdown)).sum()),
               "spoof_jump_rows": len(jumps), "spoof_candidate_mmsis": len(cands), "method_agreement": cmp}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2, default=float, allow_nan=False))

    print("[7/7] drawing maps ...")
    viz.interactive_map(gaps, jumps, p, a.out / "gap_map.html")
    viz.static_map(gaps, coast, p, a.out / "gap_map.png")
    viz.error_plot(summ, a.out / "reconstruction_error.png")

    print("done ->", a.out)


if __name__ == "__main__":
    main()
