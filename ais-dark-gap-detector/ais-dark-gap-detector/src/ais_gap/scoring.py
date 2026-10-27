"""Step 5: score gaps two ways and compare them.

1. Rule-based baseline: transparent, hand-weighted domain heuristics.
2. Isolation Forest: unsupervised, finds gaps that are statistically unusual in feature space.

There is no ground truth in real AIS data: a gap can be benign (coverage hole, receiver outage,
vessel left the area). So the output is a *ranking for analyst triage*, not a verdict.
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

IF_FEATURES = ["log_duration_h", "sog_before", "dist_coast_km", "dist_port_km",
               "log_jump_km", "log_avg_ping_s"]


def rule_score(g: pd.DataFrame) -> pd.Series:
    """0..1. Long + underway + away from port + previously chatty + moved while dark = suspicious.
    Zeroed for gaps with a benign explanation (left the AOI, moored in port)."""
    s = (0.30 * np.clip(g.duration_h / 12.0, 0, 1)
         + 0.25 * (g.sog_before.fillna(0) >= 3).astype(float)
         + 0.20 * np.clip(g.dist_port_km / 50.0, 0, 1)
         + 0.10 * (g.avg_ping_s_before.fillna(1e9) <= 300).astype(float)
         + 0.15 * np.clip(g.jump_km / 20.0, 0, 1))
    benign = g.near_edge | g.in_port_powerdown
    return s.where(~benign, 0.0)


def isolation_forest_score(g: pd.DataFrame, seed: int = 42) -> pd.Series:
    X = pd.DataFrame({
        "log_duration_h": np.log1p(g.duration_h),
        "sog_before": g.sog_before.fillna(0),
        "dist_coast_km": g.dist_coast_km,
        "dist_port_km": g.dist_port_km,
        "log_jump_km": np.log1p(g.jump_km),
        "log_avg_ping_s": np.log1p(g.avg_ping_s_before.fillna(g.avg_ping_s_before.median())),
    })[IF_FEATURES]
    Xs = StandardScaler().fit_transform(X)
    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=seed).fit(Xs)
    raw = -iso.score_samples(Xs)                       # higher = more anomalous
    return pd.Series(raw, index=g.index)


def score_gaps(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    if g.empty:
        for column in ("rule_score", "iforest_score", "rule_rank", "iforest_rank", "ensemble_rank_score"):
            g[column] = pd.Series(dtype=float)
        return g
    g["rule_score"] = rule_score(g)
    g["iforest_score"] = isolation_forest_score(g)
    g["rule_rank"] = g.rule_score.rank(ascending=False, method="first")
    g["iforest_rank"] = g.iforest_score.rank(ascending=False, method="first")
    # Ensemble: average rank; benign-explained gaps pushed to the bottom
    g["ensemble_rank_score"] = (g.rule_rank + g.iforest_rank) / 2
    g.loc[g.near_edge | g.in_port_powerdown, "ensemble_rank_score"] += len(g)
    g = g.sort_values("ensemble_rank_score").reset_index(drop=True)
    return g


def compare_methods(g: pd.DataFrame, k: int = 25) -> dict:
    """Agreement between rule-based and Isolation Forest rankings."""
    k = min(k, len(g))
    top_r = set(g.nsmallest(k, "rule_rank").gap_id)
    top_i = set(g.nsmallest(k, "iforest_rank").gap_id)
    rho = spearmanr(g.rule_score, g.iforest_score).statistic if len(g) > 2 else np.nan
    return {"k": k, "top_k_overlap": len(top_r & top_i) / k if k else None,
            "jaccard": len(top_r & top_i) / max(len(top_r | top_i), 1),
            "spearman": float(rho) if np.isfinite(rho) else None}
