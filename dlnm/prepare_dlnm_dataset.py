#!/usr/bin/env python3
"""
Prepare DLNM-ready dataset for Gasparrini-style epidemiological modeling.

Reads the existing INF_footprint_modeling_dataset.csv (ML pipeline output) and produces
outputs optimized for quasi-Poisson GLM and distributed lag non-linear models:

  out/dlnm/dlnm_dataset.csv       — full panel with all new features
  out/dlnm/Q_precip.csv           — precipitation exposure matrix [obs × 4 lags]
  out/dlnm/Q_temp.csv             — temperature exposure matrix [obs × 3 lags]
  out/dlnm/hsa_metadata.csv       — HSA-level infrastructure quality + covariates

Key differences from the ML pipeline:
  - No AR outcome lags (these absorb climate signal in regression)
  - Precipitation entered as exposure matrix for DLNM cross-basis
  - Extreme-event exposures (P_max_day_week, P95_week) as primary rainfall features
  - Natural cubic spline basis for time trend (7 df) for proper confounding control
  - Infrastructure quality proxy per HSA
"""

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "out/modeling/INF_footprint_modeling_dataset.csv"
_real_fac = BASE_DIR / "data/INF_facility_coordinates.csv"
DEFAULT_FACILITIES = _real_fac if _real_fac.exists() else BASE_DIR / "data/SYNMODINF_facility_coordinates.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "out/dlnm"

parser = argparse.ArgumentParser(description="Prepare DLNM dataset")
parser.add_argument("--input-csv", default=str(DEFAULT_INPUT))
parser.add_argument("--facilities-csv", default=str(DEFAULT_FACILITIES))
parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
parser.add_argument("--min-mean-cases", type=float, default=0.0,
                    help="Flag HSAs with mean weekly cases below this threshold")
args = parser.parse_args()

INPUT_CSV = Path(args.input_csv)
FACILITIES_CSV = Path(args.facilities_csv)
OUTPUT_DIR = Path(args.output_dir)
MIN_MEAN_CASES = args.min_mean_cases
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("DLNM DATA PREPARATION")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load base dataset
# ---------------------------------------------------------------------------
print("\n[1/6] Loading base modeling dataset...")
df = pd.read_csv(INPUT_CSV)
df["week_start"] = pd.to_datetime(df["week_start"])
df = df.sort_values(["hsa_id", "week_start"]).reset_index(drop=True)

print(f"  Rows: {len(df):,}  |  HSAs: {df['hsa_id'].nunique()}  |  "
      f"Weeks: {df['week_number'].nunique()}")
print(f"  Period: {df['week_start'].min().date()} to {df['week_start'].max().date()}")
print(f"  Total diarrheal cases: {df['diarrheal_count_adjusted'].sum():,.0f}")

# ---------------------------------------------------------------------------
# 2. Precipitation exposure matrix (lags 0-3 weeks)
# ---------------------------------------------------------------------------
print("\n[2/6] Building precipitation exposure matrix...")

# Lag 0: mean precipitation in current week (mm/day)
# Lag 1-3: mean precipitation in preceding weeks
precip_lag_cols = {
    "Q_precip_w0": "P_mean_week",
    "Q_precip_w1": "P_mean_lag_w-1",
    "Q_precip_w2": "P_mean_lag_w-2",
    "Q_precip_w3": "P_mean_lag_w-3",
}

missing = [v for v in precip_lag_cols.values() if v not in df.columns]
if missing:
    raise ValueError(f"Missing required precipitation columns: {missing}")

for new_col, src_col in precip_lag_cols.items():
    df[new_col] = df[src_col]

# Extreme event precipitation (separate exposure for sensitivity analysis)
extreme_precip_cols = {
    "Q_precip_max_w0": "P_max_day_week",  # max daily rainfall in current week
    "Q_precip_heavy_w0": "heavy_days_week",  # heavy rain days in current week
    "Q_precip_p95_w0": "P95_week",  # 95th pct threshold exceeded
}
for new_col, src_col in extreme_precip_cols.items():
    if src_col in df.columns:
        df[new_col] = df[src_col]
    else:
        print(f"  WARNING: {src_col} not found, skipping {new_col}")

Q_precip_cols = ["Q_precip_w0", "Q_precip_w1", "Q_precip_w2", "Q_precip_w3"]
Q_precip = df[["hsa_id", "week_start"] + Q_precip_cols].copy()
print(f"  Precipitation matrix: {len(Q_precip)} obs × 4 lag weeks")
print(f"  Mean exposure by lag:")
for col in Q_precip_cols:
    print(f"    {col}: {df[col].mean():.4f} mm/day")

# ---------------------------------------------------------------------------
# 3. Temperature exposure matrix (lags 0-2 weeks)
# ---------------------------------------------------------------------------
# Lag 0: mean temp in current week
# Lag 1: T_mean at d-7 (temperature 7 days before week start ≈ 1-week lag)
# Lag 2: T_mean at d-14 (≈ 2-week lag)
# Note: exact weekly lags not available for temperature; d-7 and d-14 are proxies
print("\n[3/6] Building temperature exposure matrix...")

temp_lag_map = {
    "Q_temp_w0": "T_mean_week_C",
    "Q_temp_w1": "T_mean_d-7_C",
    "Q_temp_w2": "T_mean_d-14_C",
}

missing_temp = [v for v in temp_lag_map.values() if v not in df.columns]
if missing_temp:
    raise ValueError(f"Missing required temperature columns: {missing_temp}")

for new_col, src_col in temp_lag_map.items():
    df[new_col] = df[src_col]

Q_temp_cols = ["Q_temp_w0", "Q_temp_w1", "Q_temp_w2"]
Q_temp = df[["hsa_id", "week_start"] + Q_temp_cols].copy()
print(f"  Temperature matrix: {len(Q_temp)} obs × 3 lag weeks")
print(f"  Mean exposure by lag:")
for col in Q_temp_cols:
    print(f"    {col}: {df[col].mean():.2f} °C")

# ---------------------------------------------------------------------------
# 4. Natural cubic spline basis for time trend
# ---------------------------------------------------------------------------
# Gasparrini uses ns(time, df=7/year) to control long-term trend and seasonality.
# Over 84 weeks (~1.62 years): 7 × 1.62 ≈ 11 df, but with only 84 observations
# per HSA, 7 df is more parsimonious.
print("\n[4/6] Computing natural cubic spline basis for time...")

N_DF = 7  # degrees of freedom total over 84 weeks (~4.3 df/year)

# Compute on the full sorted time_index (same time points for all HSAs)
unique_weeks = df.drop_duplicates("week_start").sort_values("week_start")
t = unique_weeks["week_start"].dt.dayofyear.values  # or use days_since_start
t_days = (unique_weeks["week_start"] - unique_weeks["week_start"].min()).dt.days.values

# Place knots at equally-spaced quantiles of time (interior knots only)
n_interior_knots = N_DF - 1  # natural spline: n_interior_knots + 1 = df for non-intercept
knot_positions = np.quantile(t_days, np.linspace(0, 1, n_interior_knots + 2)[1:-1])

# Build natural cubic spline design matrix using scipy
# Natural spline = cubic spline with zero second derivative at boundary knots
all_knots = np.concatenate([[t_days.min()], knot_positions, [t_days.max()]])


def natural_cubic_spline_basis(t_vals, knots):
    """
    Construct a natural cubic spline basis matrix.
    Returns array of shape (len(t_vals), len(knots) - 2) — one column per interior df.
    Uses the truncated power basis representation with natural boundary constraints.
    """
    n = len(t_vals)
    K = len(knots)  # includes two boundary knots
    interior = knots[1:-1]  # K-2 interior knots
    dk = knots[-1] - knots[-2]

    # Basis columns: each column h_k(t) for interior knot k
    def h(t, xi, xK_1, xK):
        d_k = ((np.maximum(t - xi, 0)) ** 3 - (np.maximum(t - xK_1, 0)) ** 3) / (xK - xK_1)
        d_last = ((np.maximum(t - xK_1, 0)) ** 3) / (xK - xK_1)
        return d_k - d_last

    n_interior = len(interior)
    xK_1 = knots[-2]
    xK = knots[-1]

    B = np.zeros((n, n_interior))
    for j, xi in enumerate(interior):
        B[:, j] = h(t_vals, xi, xK_1, xK)

    return B


# Map each row in df to its time value
df["days_since_start"] = (
    df["week_start"] - df["week_start"].min()
).dt.days

# Compute spline basis at each unique time point, then broadcast to all HSAs
B_unique = natural_cubic_spline_basis(t_days, all_knots)
# B_unique shape: (84 weeks, N_DF - 1 interior df)

# Build mapping from days_since_start to basis rows
day_to_idx = {d: i for i, d in enumerate(t_days)}
basis_cols = [f"ns_time_{k+1}" for k in range(B_unique.shape[1])]

for k, col in enumerate(basis_cols):
    df[col] = df["days_since_start"].map(
        {d: B_unique[i, k] for i, d in enumerate(t_days)}
    )

print(f"  Natural spline basis: {len(basis_cols)} columns (df={N_DF-1} interior knots)")
print(f"  Knot positions (days since start): {knot_positions.astype(int).tolist()}")

# ---------------------------------------------------------------------------
# 5. Infrastructure quality proxy per HSA
# ---------------------------------------------------------------------------
# Placeholder: maps facility type + governorate to an ordinal score 1-4.
# SHOULD BE REPLACED with JMP water/sanitation access data by governorate.
# Source: https://washdata.org/data/household#!/
print("\n[5/6] Assigning infrastructure quality scores...")

fac_df = pd.read_csv(FACILITIES_CSV)
fac_df.columns = fac_df.columns.str.strip().str.lstrip("﻿")

# Map facility name → type and governorate
# HSA IDs use underscores (e.g., 'Al-Basheer_Hospital'); facility CSV uses spaces
fac_lookup = {}
for _, row in fac_df.iterrows():
    key = row["healthfacility"].replace(" ", "_").replace("-", "-")
    fac_lookup[key] = {
        "fac_type": row["healthfacilitytype"],
        "governorate": row["governorate"],
    }

# Facility type tier: primary=1, CC=2, hospital=3, specialized/educational=4
fac_type_score = {
    "Primary Center": 1,
    "Comprehensive Center": 2,
    "Hospital": 3,
    "Educational Hospital": 3,
    "Specialized Medical Center": 4,
}

# Urban/well-serviced governorates (higher JMP access scores historically)
urban_govs = {"Amman", "Zarqa", "Aqaba"}
semi_urban_govs = {"Irbid", "Balqa", "Mafraq"}

hsa_meta_rows = []
for hsa_id in df["hsa_id"].unique():
    # Try direct match, then strip trailing part
    match = fac_lookup.get(hsa_id)
    if match is None:
        # Try case-insensitive partial match
        for k, v in fac_lookup.items():
            if k.lower() == hsa_id.lower():
                match = v
                break
    if match is None:
        # Fuzzy: longest common substring match
        best_score, best_match = 0, None
        for k, v in fac_lookup.items():
            common = sum(a == b for a, b in zip(k, hsa_id))
            if common > best_score:
                best_score, best_match = common, v
        match = best_match or {"fac_type": "Unknown", "governorate": "Unknown"}

    fac_type = match["fac_type"]
    gov = match["governorate"]
    type_score = fac_type_score.get(fac_type, 2)

    # Urban bonus: better water infrastructure coverage
    urban_bonus = 1 if gov in urban_govs else (0.5 if gov in semi_urban_govs else 0)
    infra_quality = type_score + urban_bonus

    # Mean weekly cases (for flagging low-count HSAs)
    mean_cases = df[df["hsa_id"] == hsa_id]["diarrheal_count_adjusted"].mean()

    hsa_meta_rows.append({
        "hsa_id": hsa_id,
        "fac_type": fac_type,
        "governorate": gov,
        "fac_type_score": type_score,
        "urban_bonus": urban_bonus,
        "infra_quality": infra_quality,
        "mean_weekly_cases": round(mean_cases, 2),
        "low_count_flag": mean_cases < 2.0,
        "note_infra": "PLACEHOLDER: replace with JMP water/sanitation access data",
    })

hsa_meta = pd.DataFrame(hsa_meta_rows).sort_values("infra_quality")
print(f"  Infrastructure quality scores:")
for _, row in hsa_meta.iterrows():
    flag = " [LOW COUNT]" if row["low_count_flag"] else ""
    print(f"    {row['hsa_id']:<50s} score={row['infra_quality']:.1f}  "
          f"gov={row['governorate']}{flag}")

# Merge infrastructure quality back into main df
df = df.merge(
    hsa_meta[["hsa_id", "fac_type", "governorate", "infra_quality",
              "fac_type_score", "urban_bonus", "low_count_flag"]],
    on="hsa_id",
    how="left",
)

# ---------------------------------------------------------------------------
# 6. Select and save outputs
# ---------------------------------------------------------------------------
print("\n[6/6] Saving outputs...")

# Core columns for DLNM analysis
id_cols = ["hsa_id", "week_start", "week_number", "week_of_year", "days_since_start"]
outcome_col = ["diarrheal_count_adjusted"]
exposure_cols = Q_precip_cols + Q_temp_cols
extreme_cols = [c for c in ["Q_precip_max_w0", "Q_precip_heavy_w0", "Q_precip_p95_w0"]
                if c in df.columns]
spline_cols = basis_cols
infra_cols = ["fac_type", "governorate", "infra_quality", "fac_type_score",
              "low_count_flag"]

# Additional climate covariates to keep for sensitivity analyses
extra_climate = [
    "T_max_week_C", "T_min_week_C", "DTR_week_C",
    "hours_above_30C_week", "heat_index_week_C",
    "SM1_week", "SM2_week",
    "water_deficit_mm_week", "elevation_m",
    "P_total_week", "P_sum_lag_w-1", "P_sum_lag_w-2", "P_sum_lag_w-3",
    "P_heavy_days_lag_w-1", "P_heavy_days_lag_w-2", "P_heavy_days_lag_w-3",
]
extra_climate = [c for c in extra_climate if c in df.columns]

all_cols = id_cols + outcome_col + exposure_cols + extreme_cols + spline_cols + infra_cols + extra_climate
dlnm_df = df[all_cols].copy()

# Save main dataset
out_main = OUTPUT_DIR / "dlnm_dataset.csv"
dlnm_df.to_csv(out_main, index=False)
print(f"  Saved: {out_main}  ({len(dlnm_df):,} rows × {len(dlnm_df.columns)} cols)")

# Save precipitation exposure matrix
out_q_precip = OUTPUT_DIR / "Q_precip.csv"
Q_precip.to_csv(out_q_precip, index=False)
print(f"  Saved: {out_q_precip}  ({len(Q_precip):,} rows × {len(Q_precip_cols)+2} cols)")

# Save temperature exposure matrix
out_q_temp = OUTPUT_DIR / "Q_temp.csv"
Q_temp.to_csv(out_q_temp, index=False)
print(f"  Saved: {out_q_temp}  ({len(Q_temp):,} rows × {len(Q_temp_cols)+2} cols)")

# Save HSA metadata
out_meta = OUTPUT_DIR / "hsa_metadata.csv"
hsa_meta.to_csv(out_meta, index=False)
print(f"  Saved: {out_meta}  ({len(hsa_meta)} HSAs)")

# ---------------------------------------------------------------------------
# 7. Summary statistics for verification
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("SUMMARY VERIFICATION")
print("=" * 70)

print(f"\nOutcome (diarrheal_count_adjusted):")
print(f"  Total cases: {dlnm_df['diarrheal_count_adjusted'].sum():,.0f}")
print(f"  Mean/week/HSA: {dlnm_df['diarrheal_count_adjusted'].mean():.2f}")
print(f"  Median/week/HSA: {dlnm_df['diarrheal_count_adjusted'].median():.1f}")
print(f"  Max/week/HSA: {dlnm_df['diarrheal_count_adjusted'].max():.0f}")
print(f"  Zero-count weeks: {(dlnm_df['diarrheal_count_adjusted'] == 0).sum()}")

print(f"\nPrecipitation exposure (Q_precip_w0, mm/day):")
p = dlnm_df["Q_precip_w0"]
print(f"  Range: {p.min():.3f} – {p.max():.3f}  |  Mean: {p.mean():.3f}  |  "
      f"Pct>0: {(p > 0).mean()*100:.1f}%")

print(f"\nTemperature exposure (Q_temp_w0, °C):")
t = dlnm_df["Q_temp_w0"]
print(f"  Range: {t.min():.1f} – {t.max():.1f}  |  Mean: {t.mean():.1f}")

print(f"\nInfrastructure quality distribution:")
print(f"  {hsa_meta['infra_quality'].value_counts().sort_index().to_dict()}")

print(f"\nLow-count HSAs (mean < 2 cases/week) — flagged but not excluded:")
low = hsa_meta[hsa_meta["low_count_flag"]]
for _, r in low.iterrows():
    print(f"  {r['hsa_id']}: {r['mean_weekly_cases']:.2f}/week")

print(f"\nOutputs written to: {OUTPUT_DIR}")
print("\nNext step: dlnm/dlnm_quasipoisson.py (quasi-Poisson GLM baseline)")
