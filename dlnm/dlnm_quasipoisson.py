#!/usr/bin/env python3
"""
Step 2: Quasi-Poisson GLM baseline for climate-diarrhea analysis.

Tests whether precipitation lags improve fit over a seasonal-only model,
using the correct distributional family for count data.

Fits five nested models and compares them:
  M0: intercept + HSA fixed effects
  M1: M0 + natural spline of time (7 df) — seasonal/trend baseline
  M2: M1 + precipitation lags w0-w3 — weekly mean precip
  M3: M1 + extreme precipitation (max daily + heavy rain days)
  M4: M2 + temperature lags w0-w2 — full climate model

Outputs in out/dlnm/quasipoisson/:
  model_comparison.csv       — deviance, df, F-statistic, p-value per model pair
  coefficients_M2.csv        — IRR table for precipitation lag model
  coefficients_M4.csv        — IRR table for full climate model
  lag_response_precip.png    — cumulative lag-response plot for precipitation
  predicted_vs_observed.png  — observed vs. fitted per HSA
  dispersion_check.png       — residual diagnostics
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "out/dlnm/dlnm_dataset.csv"
DEFAULT_OUTPUT = BASE_DIR / "out/dlnm/quasipoisson"

parser = argparse.ArgumentParser(description="Quasi-Poisson GLM for climate-diarrhea")
parser.add_argument("--input-csv", default=str(DEFAULT_INPUT))
parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
parser.add_argument("--exclude-low-count", action="store_true",
                    help="Exclude HSAs with mean weekly cases < 2")
args = parser.parse_args()

INPUT_CSV = Path(args.input_csv)
OUTPUT_DIR = Path(args.output_dir)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("QUASI-POISSON GLM: CLIMATE-DIARRHEA BASELINE")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("\n[1/6] Loading DLNM dataset...")
df = pd.read_csv(INPUT_CSV)
df["week_start"] = pd.to_datetime(df["week_start"])

if args.exclude_low_count:
    n_before = len(df)
    df = df[~df["low_count_flag"]].copy()
    print(f"  Excluded low-count HSAs: {n_before} → {len(df)} rows")

df = df.sort_values(["hsa_id", "week_start"]).reset_index(drop=True)
print(f"  Rows: {len(df):,}  |  HSAs: {df['hsa_id'].nunique()}  |  "
      f"Weeks: {df['week_number'].nunique()}")

# ---------------------------------------------------------------------------
# 2. Build design matrices
# ---------------------------------------------------------------------------
print("\n[2/6] Building design matrices...")

outcome = df["diarrheal_count_adjusted"].values.astype(float)

# HSA fixed effects (one-hot, drop first for identifiability)
hsa_dummies = pd.get_dummies(df["hsa_id"], drop_first=True, dtype=float)
hsa_cols = list(hsa_dummies.columns)

# Natural spline columns (time trend + seasonality)
ns_cols = [c for c in df.columns if c.startswith("ns_time_")]
ns_df = df[ns_cols].astype(float)

# Precipitation lag columns
precip_lag_cols = ["Q_precip_w0", "Q_precip_w1", "Q_precip_w2", "Q_precip_w3"]
precip_extreme_cols = [c for c in ["Q_precip_max_w0", "Q_precip_heavy_w0"]
                       if c in df.columns]

# Temperature lag columns
temp_lag_cols = ["Q_temp_w0", "Q_temp_w1", "Q_temp_w2"]

def build_X(*parts, add_const=True):
    frames = [p.reset_index(drop=True) if isinstance(p, pd.DataFrame)
              else pd.DataFrame(p) for p in parts]
    X = pd.concat(frames, axis=1)
    if add_const:
        X = sm.add_constant(X, has_constant="add")
    return X.astype(float)

# M0: intercept + HSA FE
X0 = build_X(hsa_dummies)

# M1: M0 + time spline (seasonal baseline)
X1 = build_X(hsa_dummies, ns_df)

# M2: M1 + precipitation lags (weekly mean)
X2 = build_X(hsa_dummies, ns_df, df[precip_lag_cols])

# M3: M1 + extreme precipitation only
X3 = build_X(hsa_dummies, ns_df, df[precip_extreme_cols]) if precip_extreme_cols else None

# M4: M2 + temperature lags (full climate model)
X4 = build_X(hsa_dummies, ns_df, df[precip_lag_cols], df[temp_lag_cols])

print(f"  M0 (HSA FE only):       {X0.shape[1]} predictors")
print(f"  M1 (+time spline):       {X1.shape[1]} predictors")
print(f"  M2 (+precip lags):       {X2.shape[1]} predictors")
if X3 is not None:
    print(f"  M3 (+extreme precip):    {X3.shape[1]} predictors")
print(f"  M4 (+temp lags):         {X4.shape[1]} predictors")

# ---------------------------------------------------------------------------
# 3. Fit quasi-Poisson models
# ---------------------------------------------------------------------------
# statsmodels implements quasi-Poisson via scale='X2': fits Poisson then
# estimates dispersion φ from Pearson χ²/df and rescales SEs by √φ.
# Inference uses t-distribution, not z, because φ is estimated.
print("\n[3/6] Fitting quasi-Poisson models...")

def fit_qp(X, y, label):
    """Fit quasi-Poisson GLM and return result with dispersion."""
    model = sm.GLM(y, X, family=sm.families.Poisson())
    res = model.fit(scale="X2", disp=1)  # scale='X2' → quasi-Poisson
    phi = res.scale  # estimated dispersion φ
    print(f"  {label}: deviance={res.deviance:.1f}  df={res.df_resid}  "
          f"φ={phi:.3f}  AIC≈{res.aic:.1f}")
    return res

res0 = fit_qp(X0, outcome, "M0 (baseline)")
res1 = fit_qp(X1, outcome, "M1 (seasonal)")
res2 = fit_qp(X2, outcome, "M2 (precip lags)")
res3 = fit_qp(X3, outcome, "M3 (extreme precip)") if X3 is not None else None
res4 = fit_qp(X4, outcome, "M4 (full climate)")

# ---------------------------------------------------------------------------
# 4. Model comparison via F-tests
# ---------------------------------------------------------------------------
# For quasi-Poisson, compare nested models with F-statistic:
#   F = (D_reduced - D_full) / (df_reduced - df_full) / φ_full
# where D = deviance, φ_full = dispersion from the fuller model.
print("\n[4/6] Model comparison (F-tests)...")

def ftest_nested(res_reduced, res_full, label_reduced, label_full):
    delta_dev = res_reduced.deviance - res_full.deviance
    delta_df = res_reduced.df_resid - res_full.df_resid
    phi = res_full.scale
    F = (delta_dev / delta_df) / phi
    p = 1 - stats.f.cdf(F, delta_df, res_full.df_resid)
    return {
        "comparison": f"{label_full} vs {label_reduced}",
        "delta_deviance": round(delta_dev, 2),
        "delta_df": int(delta_df),
        "F_statistic": round(F, 3),
        "p_value": p,
        "dispersion_full": round(phi, 3),
    }

comparisons = [
    ftest_nested(res0, res1, "M0", "M1(seasonal)"),
    ftest_nested(res1, res2, "M1", "M2(+precip_lags)"),
    ftest_nested(res1, res4, "M1", "M4(+all_climate)"),
    ftest_nested(res2, res4, "M2", "M4(+temp_lags)"),
]
if res3 is not None:
    comparisons.insert(2, ftest_nested(res1, res3, "M1", "M3(+extreme_precip)"))

comp_df = pd.DataFrame(comparisons)
comp_df["significant"] = comp_df["p_value"] < 0.05

print("\n  Model comparison results:")
for _, row in comp_df.iterrows():
    sig = "**" if row["significant"] else "  "
    print(f"  {sig} {row['comparison']:<35s}  "
          f"F({row['delta_df']},{res4.df_resid})={row['F_statistic']:.3f}  "
          f"p={row['p_value']:.4f}")

comp_df.to_csv(OUTPUT_DIR / "model_comparison.csv", index=False)

# ---------------------------------------------------------------------------
# 5. Coefficient tables with IRR and 95% CI
# ---------------------------------------------------------------------------
print("\n[5/6] Extracting coefficient tables...")

def irr_table(res, feature_cols, label):
    """Extract IRR (exp(β)) and 95% CI for named features."""
    rows = []
    phi = res.scale
    for col in feature_cols:
        if col not in res.params.index:
            continue
        b = res.params[col]
        se = res.bse[col]  # already accounts for quasi-Poisson dispersion
        irr = np.exp(b)
        ci_lo = np.exp(b - 1.96 * se)
        ci_hi = np.exp(b + 1.96 * se)
        p = res.pvalues[col]
        rows.append({
            "variable": col,
            "coef": round(b, 4),
            "IRR": round(irr, 4),
            "CI_lower_95": round(ci_lo, 4),
            "CI_upper_95": round(ci_hi, 4),
            "p_value": round(p, 4),
            "significant": p < 0.05,
        })
    tbl = pd.DataFrame(rows)
    path = OUTPUT_DIR / f"coefficients_{label}.csv"
    tbl.to_csv(path, index=False)
    print(f"\n  {label} — precipitation and climate coefficients:")
    print(tbl.to_string(index=False))
    return tbl

irr_m2 = irr_table(res2, precip_lag_cols, "M2_precip")
irr_m4 = irr_table(res4, precip_lag_cols + temp_lag_cols, "M4_full_climate")

# ---------------------------------------------------------------------------
# 6. Plots
# ---------------------------------------------------------------------------
print("\n[6/6] Creating diagnostic plots...")

# --- Plot A: Lag-response for precipitation (M2) ---
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

lags = [0, 1, 2, 3]
lag_labels = ["Week 0\n(current)", "Week -1", "Week -2", "Week -3"]

# M2 precipitation IRRs
m2_irr = []
m2_lo = []
m2_hi = []
for col in precip_lag_cols:
    if col in irr_m2["variable"].values:
        row = irr_m2[irr_m2["variable"] == col].iloc[0]
        m2_irr.append(row["IRR"])
        m2_lo.append(row["CI_lower_95"])
        m2_hi.append(row["CI_upper_95"])
    else:
        m2_irr.append(1.0)
        m2_lo.append(1.0)
        m2_hi.append(1.0)

# M4 precipitation IRRs
m4_irr = []
m4_lo = []
m4_hi = []
for col in precip_lag_cols:
    if col in irr_m4["variable"].values:
        row = irr_m4[irr_m4["variable"] == col].iloc[0]
        m4_irr.append(row["IRR"])
        m4_lo.append(row["CI_lower_95"])
        m4_hi.append(row["CI_upper_95"])
    else:
        m4_irr.append(1.0)
        m4_lo.append(1.0)
        m4_hi.append(1.0)

ax = axes[0]
ax.plot(lags, m2_irr, "o-", color="steelblue", label="M2 (precip only)", linewidth=2)
ax.fill_between(lags, m2_lo, m2_hi, alpha=0.2, color="steelblue")
ax.plot(lags, m4_irr, "s--", color="firebrick", label="M4 (+temperature)", linewidth=2)
ax.fill_between(lags, m4_lo, m4_hi, alpha=0.15, color="firebrick")
ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
ax.set_xticks(lags)
ax.set_xticklabels(lag_labels)
ax.set_xlabel("Lag")
ax.set_ylabel("IRR per 1 mm/day precipitation")
ax.set_title("Precipitation Lag-Response\n(IRR per 1 mm/day mean weekly precip)")
ax.legend()
ax.grid(True, alpha=0.3)

# --- Plot B: Observed vs. fitted (M2) ---
ax2 = axes[1]
fitted = res2.fittedvalues
observed = outcome

ax2.scatter(fitted, observed, alpha=0.3, s=15, color="steelblue")
max_val = max(fitted.max(), observed.max()) * 1.05
ax2.plot([0, max_val], [0, max_val], "k--", linewidth=1)
ax2.set_xlabel("Fitted (quasi-Poisson M2)")
ax2.set_ylabel("Observed cases/week")
ax2.set_title("Observed vs. Fitted\n(M2: seasonal + precip lags)")
ax2.grid(True, alpha=0.3)

# Pearson correlation
r = np.corrcoef(fitted, observed)[0, 1]
ax2.text(0.05, 0.92, f"r = {r:.3f}", transform=ax2.transAxes, fontsize=11)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "lag_response_precip.png", dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved: lag_response_precip.png")

# --- Plot C: Residual diagnostics ---
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

pearson_resid = res4.resid_pearson

ax = axes[0]
ax.scatter(res4.fittedvalues, pearson_resid, alpha=0.3, s=12)
ax.axhline(0, color="black", linewidth=0.8)
ax.axhline(2, color="red", linewidth=0.8, linestyle="--")
ax.axhline(-2, color="red", linewidth=0.8, linestyle="--")
ax.set_xlabel("Fitted values")
ax.set_ylabel("Pearson residuals")
ax.set_title(f"Residuals vs. Fitted (M4)\nDispersion φ = {res4.scale:.2f}")
ax.grid(True, alpha=0.3)

ax2 = axes[1]
by_hsa = df.copy()
by_hsa["fitted_m4"] = res4.fittedvalues
by_hsa["pearson_resid"] = pearson_resid
hsa_resid = by_hsa.groupby("hsa_id")["pearson_resid"].mean().sort_values()
hsa_resid.plot(kind="barh", ax=ax2, color="steelblue", alpha=0.7)
ax2.axvline(0, color="black", linewidth=0.8)
ax2.set_xlabel("Mean Pearson residual")
ax2.set_title("Mean Residual by HSA (M4)\n(systematic bias check)")
ax2.grid(True, alpha=0.3, axis="x")

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "dispersion_check.png", dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved: dispersion_check.png")

# --- Plot D: Per-HSA observed vs. fitted time series (M2) ---
hsa_list = sorted(df["hsa_id"].unique())
n_hsa = len(hsa_list)
ncols = 3
nrows = int(np.ceil(n_hsa / ncols))
fig, axes = plt.subplots(nrows, ncols, figsize=(16, nrows * 3.5), squeeze=False)

df_plot = df.copy()
df_plot["fitted_m2"] = res2.fittedvalues
df_plot["fitted_m4"] = res4.fittedvalues

for i, hsa in enumerate(hsa_list):
    ax = axes[i // ncols][i % ncols]
    sub = df_plot[df_plot["hsa_id"] == hsa].sort_values("week_start")
    ax.plot(sub["week_start"], sub["diarrheal_count_adjusted"],
            "k-", linewidth=1, alpha=0.8, label="Observed")
    ax.plot(sub["week_start"], sub["fitted_m2"],
            "b--", linewidth=1.5, alpha=0.7, label="M2 (precip)")
    ax.plot(sub["week_start"], sub["fitted_m4"],
            "r:", linewidth=1.5, alpha=0.7, label="M4 (full)")
    ax.set_title(hsa.replace("_", " "), fontsize=8)
    ax.tick_params(axis="both", labelsize=6)
    ax.grid(True, alpha=0.2)
    if i == 0:
        ax.legend(fontsize=6)

# Hide unused panels
for j in range(n_hsa, nrows * ncols):
    axes[j // ncols][j % ncols].set_visible(False)

plt.suptitle("Observed vs. Fitted Diarrheal Cases by HSA", y=1.01, fontsize=12)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "predicted_vs_observed.png", dpi=120, bbox_inches="tight")
plt.close()
print(f"  Saved: predicted_vs_observed.png")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)

phi_m4 = res4.scale
print(f"\nDispersion (M4): φ = {phi_m4:.2f}  "
      f"({'overdispersed' if phi_m4 > 1.5 else 'mild overdispersion' if phi_m4 > 1 else 'underdispersed'})")
print(f"  φ > 1 confirms counts are overdispersed; quasi-Poisson SEs are valid.")

print("\nModel comparison summary:")
for _, row in comp_df.iterrows():
    sig = "SIGNIFICANT" if row["significant"] else "not significant"
    print(f"  {row['comparison']:<40s}  F={row['F_statistic']:.3f}  "
          f"p={row['p_value']:.4f}  [{sig}]")

print(f"\nPrecipitation IRRs (M2 — per 1 mm/day increase in weekly mean precip):")
for col in precip_lag_cols:
    rows = irr_m2[irr_m2["variable"] == col]
    if not rows.empty:
        r = rows.iloc[0]
        lag = col.replace("Q_precip_", "")
        sig = "*" if r["significant"] else " "
        print(f"  {lag}: IRR={r['IRR']:.4f}  "
              f"95%CI [{r['CI_lower_95']:.4f}, {r['CI_upper_95']:.4f}]  "
              f"p={r['p_value']:.4f} {sig}")

print(f"\nNext step: dlnm/dlnm_gasparrini.R (proper DLNM cross-basis in R)")
print(f"Outputs in: {OUTPUT_DIR}")
