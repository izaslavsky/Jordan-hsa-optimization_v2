#!/usr/bin/env python3
"""
Systematic DLNM screening of environmental exposures beyond precipitation.

For each candidate variable, fits:
  M_base     : HSA fixed effects + seasonal spline
  M_exposure : M_base + cross-basis (daily lags d-1, d-2, d-3, d-5, d-7, d-10, d-14)
  M_interact : M_exposure + cross-basis × sanitation quality (centred)

Reports F-tests (exposure vs base, interaction vs exposure) for every variable,
then ranks by interaction p-value.

Excluded:
  - Evaporation (E_d-*): values labelled mm/day but appear to be in different units
  - SM3, SM4: deep soil layers not relevant to surface contamination pathways
  - T_min: highly correlated with T_mean and Td
  - hours_above_35C: correlated with hours_above_30C; less discriminating in Jordan

Epidemiological rationale for each included variable:
  T_mean      — bacterial growth rate doubles every 5°C above ~10°C
  T_max       — peak heat stress; proxy for afternoon food-safety conditions
  DTR         — diurnal temperature range; low DTR → overcast/humid → fly activity
  Td          — dewpoint (absolute humidity); fly vector activity, pathogen survival
  heat_index  — combined temperature + humidity thermal stress
  hrs_above_30C — hours above 30°C per day; 52.9% zero weeks, needs non-zero knot
  SM1         — surface soil moisture (0-7 cm); saturation → surface runoff → fecal contamination
  SM2         — shallow subsurface (7-28 cm); slower contamination signal
  wind_speed  — pathogen aerosol dispersal; fly dispersal range
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from dlnm_crossbasis import (
    ns_basis, build_crossbasis, cumulative_rr,
)

BASE_DIR   = Path(__file__).resolve().parent.parent
DSET_CSV   = BASE_DIR / "out/dlnm/dlnm_dataset.csv"
RAW_CSV    = (BASE_DIR.parent / "jordan-hsa-optimization_INF_FOOTPRINT"
              / "out/modeling/INF_footprint_modeling_dataset.csv")
META_CSV   = BASE_DIR / "out/dlnm/hsa_metadata.csv"
OUTPUT_DIR = BASE_DIR / "out/dlnm/env_screening"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("DLNM ENVIRONMENTAL EXPOSURE SCREENING")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("\n[1/4] Loading data...")
dlnm = pd.read_csv(DSET_CSV)
raw  = pd.read_csv(RAW_CSV)

meta = pd.read_csv(META_CSV)
low_count_hsas = meta.loc[meta["low_count_flag"] == True, "hsa_id"].tolist()

lag_days = [1, 2, 3, 5, 7, 10, 14]
lag_vals = np.array(lag_days, dtype=float)

# Candidate exposures: (name, column_prefix_or_list, description)
EXPOSURES = [
    ("T_mean",      [f"T_mean_d-{d}_C"          for d in lag_days], "Daily mean temperature (°C)"),
    ("T_max",       [f"T_max_d-{d}_C"            for d in lag_days], "Daily max temperature (°C)"),
    ("DTR",         [f"DTR_d-{d}_C"              for d in lag_days], "Diurnal temperature range (°C)"),
    ("dewpoint",    [f"Td_d-{d}_C"               for d in lag_days], "Dewpoint temperature (°C)"),
    ("heat_index",  [f"heat_index_d-{d}_C"       for d in lag_days], "Heat index (°C)"),
    ("hrs_above_30",[f"hours_above_30C_d-{d}"    for d in lag_days], "Hours above 30°C per day"),
    ("SM1",         [f"SM1_d-{d}"                for d in lag_days], "Surface soil moisture 0-7 cm (m³/m³)"),
    ("SM2",         [f"SM2_d-{d}"                for d in lag_days], "Shallow soil moisture 7-28 cm (m³/m³)"),
    ("wind_speed",  [f"wind_speed_d-{d}_ms"      for d in lag_days], "Wind speed (m/s)"),
]

# Merge all needed columns into one dataframe
all_env_cols = [c for _, cols, _ in EXPOSURES for c in cols]
available = [c for c in all_env_cols if c in raw.columns]
missing   = [c for c in all_env_cols if c not in raw.columns]
if missing:
    print(f"  WARNING: missing columns: {missing}")

merge_cols = ["hsa_id", "week_start"] + available
df = dlnm.merge(raw[merge_cols], on=["hsa_id", "week_start"], how="left")
df_full = df[~df["hsa_id"].isin(low_count_hsas)].copy().reset_index(drop=True)

print(f"  {len(df_full)} obs ({len(df_full['hsa_id'].unique())} HSAs) after exclusions")

# Base model components (shared across all exposures)
outcome     = df_full["diarrheal_count_adjusted"].values.astype(float)
ns_cols     = [c for c in df_full.columns if c.startswith("ns_time_")]
hsa_dummies = pd.get_dummies(df_full["hsa_id"], drop_first=True, dtype=float)
base_X_df   = pd.concat([hsa_dummies, df_full[ns_cols]], axis=1).reset_index(drop=True)
base_X      = base_X_df.values

infra   = df_full["infra_quality"].values
infra_c = infra - infra.mean()

lag_int_knots = np.array([3.0, 7.0])
lag_all_knots = np.array([lag_vals[0], *lag_int_knots, lag_vals[-1]])

def fit_qp(X, y):
    model = sm.GLM(y, sm.add_constant(X.astype(float), has_constant="add"),
                   family=sm.families.Poisson())
    return model.fit(scale="X2")

def ftest(res_r, res_f):
    dD  = res_r.deviance - res_f.deviance
    ddf = int(round(res_r.df_resid - res_f.df_resid))
    if ddf <= 0:
        return np.nan, np.nan, res_f.scale
    F = (dD / ddf) / res_f.scale
    p = 1 - stats.f.cdf(F, ddf, res_f.df_resid)
    return float(F), float(p), float(res_f.scale)

# Fit baseline once
print("\n[2/4] Fitting baseline model...")
res_base = fit_qp(pd.DataFrame(base_X), outcome)
print(f"  M_base: deviance={res_base.deviance:.1f}  df={res_base.df_resid}  φ={res_base.scale:.2f}")

# ---------------------------------------------------------------------------
# 2. Screen each exposure
# ---------------------------------------------------------------------------
print("\n[3/4] Screening exposures...")
print(f"  {'Variable':<14s}  {'F_main':>7s}  {'p_main':>7s}  {'F_int':>7s}  {'p_int':>7s}  {'φ_int':>5s}  Sig")
print("  " + "-" * 65)

results = []

for name, cols, description in EXPOSURES:
    missing_exp = [c for c in cols if c not in df_full.columns]
    if missing_exp:
        print(f"  {name:<14s}  SKIP (missing: {missing_exp[0]})")
        continue

    Q = df_full[cols].values  # (n_obs, 7)

    # Knot strategy: if >30% zeros, use 80th pct of non-zero; else use 50th pct
    all_vals  = Q.flatten()
    zero_frac = (all_vals == 0).mean()
    nonzero   = all_vals[all_vals > 0]
    if zero_frac > 0.30 and len(nonzero) > 0:
        int_knot = np.percentile(nonzero, 80)
    else:
        int_knot = np.percentile(all_vals, 50)

    # For temperature-like variables that can be negative (Td, DTR), shift boundary
    exp_min = all_vals.min()
    exp_max = all_vals.max()
    # Ensure interior knot is strictly interior
    int_knot = np.clip(int_knot, exp_min + 1e-6, exp_max - 1e-6)
    exp_all_knots = np.array([exp_min, int_knot, exp_max])

    try:
        CB, _, cb_meta = build_crossbasis(
            Q, exp_n_int=1, lag_n_int=2,
            exp_all_knots=exp_all_knots,
            lag_all_knots=lag_all_knots,
            lag_values=lag_vals,
        )
    except Exception as e:
        print(f"  {name:<14s}  ERROR building crossbasis: {e}")
        continue

    CB_x_infra = CB * infra_c[:, None]

    X_exp      = np.c_[base_X, CB]
    X_interact = np.c_[base_X, CB, CB_x_infra]

    try:
        res_exp      = fit_qp(pd.DataFrame(X_exp),      outcome)
        res_interact = fit_qp(pd.DataFrame(X_interact), outcome)
    except Exception as e:
        print(f"  {name:<14s}  ERROR fitting model: {e}")
        continue

    F_main, p_main, _   = ftest(res_base,   res_exp)
    F_int,  p_int,  phi = ftest(res_exp,     res_interact)

    sig = ""
    if not np.isnan(p_int):
        if p_int < 0.001:
            sig = "***"
        elif p_int < 0.01:
            sig = "**"
        elif p_int < 0.05:
            sig = "*"

    print(f"  {name:<14s}  {F_main:>7.3f}  {p_main:>7.4f}  {F_int:>7.3f}  {p_int:>7.4f}  {phi:>5.2f}  {sig}")

    results.append({
        "variable":    name,
        "description": description,
        "n_cb_cols":   CB.shape[1],
        "exp_int_knot": int_knot,
        "zero_frac":   zero_frac,
        "F_main":      F_main,
        "p_main":      p_main,
        "F_interact":  F_int,
        "p_interact":  p_int,
        "phi_interact": phi,
    })

# ---------------------------------------------------------------------------
# 3. Summary and plots
# ---------------------------------------------------------------------------
print("\n[4/4] Ranking and saving results...")

res_df = pd.DataFrame(results).sort_values("p_interact")
res_df.to_csv(OUTPUT_DIR / "screening_results.csv", index=False)

print("\n  Ranked by interaction p-value:")
print(f"  {'Rank':<5s} {'Variable':<14s} {'p_main':>7s} {'p_interact':>10s} {'sig':>4s}  Description")
for rank, (_, row) in enumerate(res_df.iterrows(), 1):
    p_int = row["p_interact"]
    sig = "***" if p_int < 0.001 else ("**" if p_int < 0.01 else ("*" if p_int < 0.05 else ""))
    print(f"  {rank:<5d} {row['variable']:<14s} {row['p_main']:>7.4f} {p_int:>10.4f} {sig:>4s}  {row['description']}")

# Plot: tornado chart of -log10(p) for main effect and interaction
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

vars_sorted = res_df["variable"].tolist()
y_pos = np.arange(len(vars_sorted))

for ax, col, title in [
    (axes[0], "p_main",     "Main effect: F-test (exposure cross-basis vs seasonal baseline)"),
    (axes[1], "p_interact", "Sanitation interaction: F-test (CB×infra vs main)"),
]:
    pvals = res_df[col].values
    log_p = -np.log10(np.clip(pvals, 1e-10, 1.0))
    colors = ["#d62728" if p < 0.05 else "#aec7e8" for p in pvals]
    ax.barh(y_pos, log_p, color=colors, alpha=0.85)
    ax.axvline(-np.log10(0.05), color="black", linewidth=1, linestyle="--",
               label="p=0.05")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(vars_sorted, fontsize=10)
    ax.set_xlabel("-log₁₀(p-value)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="x")

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "screening_tornado.png", dpi=150, bbox_inches="tight")
plt.close()
print(f"\n  Saved: screening_tornado.png")
print(f"  Saved: screening_results.csv")
print(f"  Output directory: {OUTPUT_DIR}")

# Highlight any significant interactions
sig_vars = res_df[res_df["p_interact"] < 0.05]
if len(sig_vars):
    print(f"\n  Variables with significant sanitation interaction (p<0.05):")
    for _, row in sig_vars.iterrows():
        print(f"    {row['variable']:<14s}  p_interact={row['p_interact']:.4f}")
else:
    print("\n  No variables with significant sanitation interaction at p<0.05.")
