#!/usr/bin/env python3
"""
DLNM with daily precipitation lags (1, 2, 3, 5, 7, 10, 14 days before week start).

The weekly cross-basis uses weekly-mean precipitation at lags 0-3 weeks.
This script instead uses the actual daily precipitation measurements at
specific lag days to capture acute event effects masked by weekly averaging.

Each row of the exposure matrix Q_daily[obs, k] is the precipitation on the
day that was lag_days[k] days before the week start. The lag basis spans
1-14 days; natural splines handle the uneven spacing (1,2,3,5,7,10,14).
"""

from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reuse cross-basis helpers from the weekly script
import sys
sys.path.insert(0, str(Path(__file__).parent))
from dlnm_crossbasis import (
    _ns_basis_from_knots, ns_basis, build_crossbasis,
    predict_rr, cumulative_rr,
)

BASE_DIR   = Path(__file__).resolve().parent.parent
DSET_CSV   = BASE_DIR / "out/dlnm/dlnm_dataset.csv"
RAW_CSV    = (BASE_DIR.parent / "jordan-hsa-optimization_INF_FOOTPRINT"
              / "out/modeling/INF_footprint_modeling_dataset.csv")
OUTPUT_DIR = BASE_DIR / "out/dlnm/daily"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("DLNM — DAILY LAG ANALYSIS")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("\n[1/8] Loading data...")

dlnm = pd.read_csv(DSET_CSV)
raw  = pd.read_csv(RAW_CSV)

# Daily precip columns — each is precipitation on a specific day before week start
daily_lag_days = [1, 2, 3, 5, 7, 10, 14]
daily_cols     = [f"P_d-{d}" for d in daily_lag_days]
missing = [c for c in daily_cols if c not in raw.columns]
if missing:
    raise ValueError(f"Columns not found in raw dataset: {missing}")

# Merge daily precip into the DLNM panel dataset
merge_cols = ["hsa_id", "week_start"] + daily_cols
raw_sub = raw[merge_cols].copy()
df = dlnm.merge(raw_sub, on=["hsa_id", "week_start"], how="left")

# Apply same low-count exclusion as weekly script
meta_csv = BASE_DIR / "out/dlnm/hsa_metadata.csv"
meta = pd.read_csv(meta_csv)
low_count_hsas = meta.loc[meta["low_count_flag"] == True, "hsa_id"].tolist()
hsa_keep = [h for h in df["hsa_id"].unique() if h not in low_count_hsas]
df_full = df[df["hsa_id"].isin(hsa_keep)].copy().reset_index(drop=True)

print(f"  {len(df)} total obs; {len(df_full)} obs after removing "
      f"{len(low_count_hsas)} low-count HSAs")
print(f"  Daily lag columns: {daily_cols}")

# Check zero-fraction per lag day
for col, d in zip(daily_cols, daily_lag_days):
    z = (df_full[col] == 0).mean()
    print(f"    P_d-{d:>2d}: zero fraction = {z*100:.1f}%  "
          f"max = {df_full[col].max():.3f} mm")

# ---------------------------------------------------------------------------
# 2. Build daily cross-basis
# ---------------------------------------------------------------------------
print("\n[2/8] Building daily precipitation cross-basis...")

Q_daily = df_full[daily_cols].values  # (n_obs, 7)

# Exposure knots: same strategy as weekly — 80th pct of non-zero values
nonzero_daily = Q_daily[Q_daily > 0].flatten()
exp_int_knot = np.percentile(nonzero_daily, 80)
exp_all_knots = np.array([0.0, exp_int_knot, Q_daily.max()])
print(f"  Exposure interior knot: {exp_int_knot:.4f} mm "
      f"(80th pct of non-zero days)")

# Lag knots: span [1, 14] days with 2 interior knots at days 3 and 7
lag_vals = np.array(daily_lag_days, dtype=float)
lag_int_knots = np.array([3.0, 7.0])
lag_all_knots = np.array([lag_vals[0], *lag_int_knots, lag_vals[-1]])

CB_daily, cb_col_names, cb_meta_daily = build_crossbasis(
    Q_daily,
    exp_n_int=1,  lag_n_int=2,
    exp_all_knots=exp_all_knots,
    lag_all_knots=lag_all_knots,
    lag_values=lag_vals,         # actual lag values in days
)
print(f"  Cross-basis shape: {CB_daily.shape}  ({len(cb_col_names)} columns)")
print(f"  Exposure knots: {exp_all_knots.round(4)}")
print(f"  Lag knots     : {lag_all_knots}")

# ---------------------------------------------------------------------------
# 3. Fit quasi-Poisson models
# ---------------------------------------------------------------------------
print("\n[3/8] Fitting quasi-Poisson models...")

outcome = df_full["diarrheal_count_adjusted"].values.astype(float)
ns_cols  = [c for c in df_full.columns if c.startswith("ns_time_")]
hsa_dummies = pd.get_dummies(df_full["hsa_id"], drop_first=True, dtype=float)
base_X = pd.concat([hsa_dummies, df_full[ns_cols]], axis=1).reset_index(drop=True)

def fit_qp(X, y, label):
    model = sm.GLM(y, sm.add_constant(X.astype(float), has_constant="add"),
                   family=sm.families.Poisson())
    res = model.fit(scale="X2")
    print(f"  {label}: deviance={res.deviance:.1f}  df={res.df_resid}  φ={res.scale:.2f}")
    return res

def ftest(res_r, res_f, label):
    dD  = res_r.deviance - res_f.deviance
    ddf = res_r.df_resid  - res_f.df_resid
    F   = (dD / ddf) / res_f.scale
    p   = 1 - stats.f.cdf(F, ddf, res_f.df_resid)
    sig = "**" if p < 0.05 else "  "
    print(f"  {sig} {label:<50s}  F({ddf:.0f},{res_f.df_resid:.0f})={F:.3f}  p={p:.4f}")
    return {"comparison": label, "F": F, "p_value": p, "phi": res_f.scale}

X_base = base_X.values
X_cb_d = np.c_[base_X.values, CB_daily]

res_base  = fit_qp(pd.DataFrame(X_base),  outcome, "M_base  (HSA + time spline)")
res_daily = fit_qp(pd.DataFrame(X_cb_d),  outcome, "M_daily (+ daily precip cross-basis)")

comp_rows = [ftest(res_base, res_daily, "daily precip cross-basis vs base")]

# ---------------------------------------------------------------------------
# 4. Extract response
# ---------------------------------------------------------------------------
print("\n[4/8] Extracting precipitation cross-basis response...")

params   = res_daily.params
vcov_all = np.asarray(res_daily.cov_params())

n_base = X_base.shape[1] + 1
cb_idx = slice(n_base, n_base + CB_daily.shape[1])
coef_cb = np.asarray(params)[cb_idx]
vcov_cb = vcov_all[cb_idx, :][:, cb_idx]

# Use 95th pct of non-zero values so the exposure grid has meaningful range
exp_grid = np.linspace(0, np.percentile(nonzero_daily, 95), 50)
lag_grid = lag_vals          # actual day values: 1, 2, 3, 5, 7, 10, 14
reference_exp = 0.0

cum_logRR, cum_se = cumulative_rr(coef_cb, vcov_cb, cb_meta_daily,
                                   exp_grid, reference_exp)
logRR_surface, seRR_surface = predict_rr(coef_cb, vcov_cb, cb_meta_daily,
                                          exp_grid, lag_grid, reference_exp)

# ---------------------------------------------------------------------------
# 5. Interaction with infrastructure quality
# ---------------------------------------------------------------------------
print("\n[5/8] Testing infrastructure quality × daily precip interaction...")

infra   = df_full["infra_quality"].values
infra_c = infra - infra.mean()
CB_daily_x_infra = CB_daily * infra_c[:, None]

X_interact = np.c_[base_X.values, CB_daily, CB_daily_x_infra]
res_interact = fit_qp(pd.DataFrame(X_interact), outcome,
                      "M_interact (+cb×infra_quality)")

ftest_int = ftest(res_daily, res_interact,
                  "interaction (cb×infra_quality) vs daily precip")
comp_rows.append(ftest_int)
pd.DataFrame(comp_rows).to_csv(OUTPUT_DIR / "model_comparison_daily.csv", index=False)

# Extract interaction coefs
n_main  = X_base.shape[1] + 1 + CB_daily.shape[1]
int_idx = slice(n_main, n_main + CB_daily.shape[1])
coef_int = np.asarray(res_interact.params)[int_idx]

# ---------------------------------------------------------------------------
# 6. Per-HSA cumulative RR
# ---------------------------------------------------------------------------
print("\n[6/8] Per-HSA cumulative RR at 75th pct daily precipitation...")

# Daily precipitation is ~85% zero; the 75th pct of all values is 0.
# Use the 75th pct of non-zero values as the meaningful reference point.
nonzero_daily = Q_daily[Q_daily > 0].flatten()
exp_ref75 = np.percentile(nonzero_daily, 75)
print(f"  75th pct of non-zero daily precip: {exp_ref75:.4f} mm")

hsa_rr_rows = []
for hsa in hsa_keep:
    sub = df_full[df_full["hsa_id"] == hsa].copy()
    if len(sub) < 20:
        continue
    Q_h = sub[daily_cols].values
    ns_h = sub[ns_cols].astype(float)
    y_h  = sub["diarrheal_count_adjusted"].values.astype(float)

    CB_h, _, meta_h = build_crossbasis(
        Q_h, exp_n_int=1, lag_n_int=2,
        exp_all_knots=exp_all_knots,
        lag_all_knots=lag_all_knots,
        lag_values=lag_vals,
    )
    X_h = np.c_[np.ones(len(sub)), ns_h.values, CB_h]
    try:
        model_h = sm.GLM(y_h, X_h, family=sm.families.Poisson())
        res_h   = model_h.fit(scale="X2")
    except Exception as e:
        print(f"  {hsa}: fit failed ({e})")
        continue

    n_base_h = 1 + ns_h.shape[1]
    cb_idx_h = slice(n_base_h, n_base_h + CB_h.shape[1])
    coef_h   = np.asarray(res_h.params)[cb_idx_h]
    vcov_h   = np.asarray(res_h.cov_params())[cb_idx_h, :][:, cb_idx_h]

    logRR_h, se_h = cumulative_rr(coef_h, vcov_h, meta_h,
                                   np.array([exp_ref75]), reference_exp)
    logRR_val = float(logRR_h[0])
    se_val    = float(se_h[0])

    san_pct = float(sub["jmp_san_pct"].iloc[0])
    print(f"  {hsa:<50s}  cumRR={np.exp(logRR_val):.3f} "
          f"[{np.exp(logRR_val - 1.96*se_val):.3f},"
          f"{np.exp(logRR_val + 1.96*se_val):.3f}]  san={san_pct:.1f}%")

    hsa_rr_rows.append({
        "hsa_id":         hsa,
        "cum_logRR_75pct": logRR_val,
        "cum_se_75pct":    se_val,
        "cum_RR_75pct":    np.exp(logRR_val),
        "jmp_san_pct":     san_pct,
        "n_obs":           len(sub),
    })

hsa_rr_df = pd.DataFrame(hsa_rr_rows)
hsa_rr_df.to_csv(OUTPUT_DIR / "hsa_cumRR_daily.csv", index=False)

# Meta-regression — drop any HSAs where SE=0 (degenerate fit)
if len(hsa_rr_df) >= 5:
    hsa_rr_df = hsa_rr_df[hsa_rr_df["cum_se_75pct"] > 0].copy()
    weights = 1.0 / (hsa_rr_df["cum_se_75pct"] ** 2)
    meta_model = sm.WLS(
        hsa_rr_df["cum_logRR_75pct"],
        sm.add_constant(hsa_rr_df["jmp_san_pct"]),
        weights=weights,
    )
    meta_res = meta_model.fit()
    slope, slope_se, slope_p = meta_res.params[1], meta_res.bse[1], meta_res.pvalues[1]
    print(f"\n  Meta-regression (logRR ~ sanitation %): "
          f"β={slope:.4f} ± {slope_se:.4f}  p={slope_p:.4f}")
    meta_out = pd.DataFrame({
        "term": ["intercept", "jmp_san_pct"],
        "coef": meta_res.params, "se": meta_res.bse, "p_value": meta_res.pvalues,
    })
    meta_out.to_csv(OUTPUT_DIR / "meta_regression_daily.csv", index=False)
else:
    slope = slope_se = slope_p = None

# ---------------------------------------------------------------------------
# 7. Attributable fractions
# ---------------------------------------------------------------------------
print("\n[7/8] Computing attributable fractions...")

fitted_obs = res_interact.fittedvalues
Q_counterfactual = np.zeros_like(Q_daily)
CB_counter, _, _ = build_crossbasis(
    Q_counterfactual, exp_n_int=1, lag_n_int=2,
    exp_all_knots=exp_all_knots,
    lag_all_knots=lag_all_knots,
    lag_values=lag_vals,
)
CB_counter_x_infra = CB_counter * infra_c[:, None]

n_cb_start_int = base_X.shape[1] + 1
cb_idx_int = slice(n_cb_start_int, n_cb_start_int + CB_daily.shape[1])
coef_cb_int = np.asarray(res_interact.params)[cb_idx_int]

delta_lp = (
    (CB_counter @ coef_cb_int + CB_counter_x_infra @ coef_int) -
    (CB_daily   @ coef_cb_int + CB_daily_x_infra   @ coef_int)
)
mu_counter = np.exp(np.log(fitted_obs) + delta_lp)

df_full_copy = df_full.copy().reset_index(drop=True)
df_full_copy["af"] = ((fitted_obs - mu_counter) / fitted_obs).values

af_by_hsa = df_full_copy.groupby("hsa_id").agg(
    total_fitted=("diarrheal_count_adjusted", "sum"),
    total_counterfactual=("af", lambda x: (fitted_obs[x.index] - mu_counter[x.index]).sum()),
    jmp_san_pct=("jmp_san_pct", "first"),
).reset_index()
# simpler: use pre-computed delta
af_obs = ((fitted_obs - mu_counter) / fitted_obs).values
df_full_copy["af"]            = af_obs
df_full_copy["fitted_val"]    = fitted_obs.values
df_full_copy["counterfactual"] = mu_counter

af_by_hsa = df_full_copy.groupby("hsa_id").agg(
    total_fitted=("fitted_val", "sum"),
    total_counterfactual=("counterfactual", "sum"),
    jmp_san_pct=("jmp_san_pct", "first"),
).reset_index()
af_by_hsa["AF_pct"] = (
    (af_by_hsa["total_fitted"] - af_by_hsa["total_counterfactual"])
    / af_by_hsa["total_fitted"] * 100
)
af_by_hsa = af_by_hsa.sort_values("jmp_san_pct")
af_by_hsa.to_csv(OUTPUT_DIR / "attributable_fraction_daily.csv", index=False)

af_by_hsa["infra_tertile"] = pd.qcut(
    af_by_hsa["jmp_san_pct"], q=3, labels=["Low", "Medium", "High"]
)
print("  Mean AF by sanitation tertile:")
for t, v in af_by_hsa.groupby("infra_tertile", observed=True)["AF_pct"].mean().items():
    print(f"    {t}: {v:.2f}%")

# ---------------------------------------------------------------------------
# 8. Plots
# ---------------------------------------------------------------------------
print("\n[8/8] Creating plots...")

RR_cum = np.exp(cum_logRR)
RR_lo  = np.exp(cum_logRR - 1.96 * cum_se)
RR_hi  = np.exp(cum_logRR + 1.96 * cum_se)

infra_tertile_vals = {
    "Low sanitation":    np.percentile(infra_c, 17),
    "Medium sanitation": np.percentile(infra_c, 50),
    "High sanitation":   np.percentile(infra_c, 83),
}
tertile_colors = {
    "Low sanitation": "#d62728",
    "Medium sanitation": "#ff7f0e",
    "High sanitation": "#2ca02c",
}

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Plot A: cumulative RR stratified by infra quality
ax = axes[0]
ax.plot(exp_grid, RR_cum, "k-", linewidth=2, alpha=0.4, label="Pooled average")
ax.fill_between(exp_grid, RR_lo, RR_hi, alpha=0.08, color="black")

for label, q_c_val in infra_tertile_vals.items():
    eff_coef = coef_cb + coef_int * q_c_val
    lr, se_ = cumulative_rr(eff_coef, vcov_cb, cb_meta_daily, exp_grid)
    san_pct = (q_c_val + infra.mean()) * 100
    ax.plot(exp_grid, np.exp(lr), linewidth=2, color=tertile_colors[label],
            label=f"{label} ({san_pct:.0f}%)")
    ax.fill_between(exp_grid, np.exp(lr - 1.96 * se_), np.exp(lr + 1.96 * se_),
                    alpha=0.12, color=tertile_colors[label])

ax.axhline(1.0, color="black", linewidth=0.7, linestyle=":")
ax.axvline(exp_ref75, color="gray", linewidth=0.7, linestyle="--",
           label=f"75th pct ({exp_ref75:.3f} mm)")
ax.set_xlabel("Daily precipitation (mm)")
ax.set_ylabel("Cumulative RR (all lag days)")
ax.set_title("Daily Precip–Diarrhea: Cumulative Lag-Response\nby Sanitation Quality")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Plot B: RR surface over lag days × exposure
ax2 = axes[1]
RR_surface = np.exp(logRR_surface)
vmin = max(RR_surface.min(), 0.7)
vmax = min(RR_surface.max(), 1.4)
im = ax2.contourf(lag_grid, exp_grid, RR_surface, levels=20,
                   cmap="RdBu_r", vmin=vmin, vmax=vmax)
plt.colorbar(im, ax=ax2, label="RR")
ax2.set_xlabel("Lag (days before week start)")
ax2.set_ylabel("Daily precipitation (mm)")
ax2.set_title("RR Surface: Daily Precipitation × Lag (Pooled)")
ax2.set_xticks(lag_grid)
ax2.set_xticklabels([f"d-{int(d)}" for d in lag_grid])
ax2.grid(True, alpha=0.2)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "cumulative_rr_daily.png", dpi=150, bbox_inches="tight")
plt.close()
print("  Saved: cumulative_rr_daily.png")

# Plot C: meta-regression scatter
if slope is not None and len(hsa_rr_df) >= 5:
    fig, ax = plt.subplots(figsize=(9, 6))
    rr_vals    = hsa_rr_df["cum_RR_75pct"].values
    logRR_vals = hsa_rr_df["cum_logRR_75pct"].values
    se_vals    = hsa_rr_df["cum_se_75pct"].values
    err_lo = rr_vals - np.exp(logRR_vals - 1.96 * se_vals)
    err_hi = np.exp(logRR_vals + 1.96 * se_vals) - rr_vals

    sc = ax.scatter(hsa_rr_df["jmp_san_pct"], rr_vals,
                    s=hsa_rr_df["n_obs"] / 3,
                    c=hsa_rr_df["jmp_san_pct"], cmap="RdYlGn",
                    vmin=60, vmax=85, alpha=0.85, zorder=3)
    ax.errorbar(hsa_rr_df["jmp_san_pct"], rr_vals,
                yerr=[err_lo, err_hi],
                fmt="none", color="gray", alpha=0.4, linewidth=0.8)

    x_line = np.linspace(hsa_rr_df["jmp_san_pct"].min() - 1,
                          hsa_rr_df["jmp_san_pct"].max() + 1, 100)
    y_line = np.exp(meta_res.params[0] + meta_res.params[1] * x_line)
    ax.plot(x_line, y_line, "k-", linewidth=2,
            label=f"WLS: β={slope:.4f}/ppt  p={slope_p:.3f}")

    for _, row in hsa_rr_df.iterrows():
        short = (row["hsa_id"].replace("_Hospital", "")
                 .replace("_Comprehensive_Center", " CC")
                 .replace("_Primary_Center", " PC").replace("_", " "))
        ax.annotate(short, (row["jmp_san_pct"], row["cum_RR_75pct"]),
                    textcoords="offset points", xytext=(4, 3), fontsize=7)

    ax.axhline(1.0, color="black", linewidth=0.8, linestyle=":")
    ax.set_xlabel("Safely managed sanitation (%, JMP × census weights)")
    ax.set_ylabel(f"Cumulative RR at 75th pct daily precip ({exp_ref75:.3f} mm)")
    ax.set_title("Per-HSA Cumulative RR vs Sanitation (Daily Lag Model)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.colorbar(sc, ax=ax, label="Sanitation %")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "meta_regression_daily.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: meta_regression_daily.png")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("DAILY LAG DLNM — RESULTS SUMMARY")
print("=" * 70)

for r in comp_rows:
    sig = "SIGNIFICANT" if r["p_value"] < 0.05 else "not significant"
    print(f"  {r['comparison']:<55s}  F={r['F']:.3f}  p={r['p_value']:.4f}  [{sig}]")

print(f"\nCumulative RR (daily precip, all lags combined):")
for pct in [50, 75, 90, 95]:
    exp_val = np.percentile(Q_daily, pct)
    idx = np.argmin(np.abs(exp_grid - exp_val))
    rr = float(RR_cum[idx])
    lo = float(RR_lo[idx])
    hi = float(RR_hi[idx])
    print(f"  {pct}th pct ({exp_val:.3f} mm): RR={rr:.3f}  95%CI [{lo:.3f}, {hi:.3f}]")

if slope is not None:
    print(f"\nMeta-regression: β={slope:.5f}/ppt sanitation  p={slope_p:.4f}")

print(f"\nOutputs: {OUTPUT_DIR}")
