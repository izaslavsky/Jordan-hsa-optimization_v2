# Climate-Health Modeling with Daily Data
## DLNM, Predictive Horizons, and HSA Boundary Sensitivity

**Webinar 3 of 3 — 90 minutes**

*Zaslavsky et al. — Daily Epidemiological Pipeline*

---

## Agenda

- The climate-diarrhea hypothesis in Jordan
- Daily data pipeline recap
- Distributed Lag Non-Linear Models: theory and implementation
- Track A results: explanatory associations
- Infrastructure as an effect modifier
- Track B results: predictive horizons
- Sensitivity to HSA boundary version (v6/v7/v8)
- What the synthetic data tells us and what it doesn't

---

## Why Daily Data?

Weekly aggregation smooths over within-week signals:

- A precipitation event on Thursday may affect diarrheal incidence on Friday–Sunday
- Weekly bins mix the exposure event with its lagged effect
- Friday attendance suppression (50% of normal) creates weekly artifacts

Daily resolution gives:

- Sharper lag-response curves (effects appear 2–7 days after exposure)
- Day-of-week controls (Friday dummy captures reporting suppression)
- Separation of acute exposure effects from chronic baseline

The cost: 14-day lag history is needed before any modeled day — losing the first 14 rows per HSA.

---

## Study Window and Data Structure

**Health data:** INF network, 2022-07-01 to 2024-01-31 (19 months)

**Why start July 2022?** ICD diagnostic codes were changed on 2022-07-01. Earlier records use a different coding scheme; mixing them inflates apparent diarrheal counts.

**Final modeling dataset:**

| Item | Value |
|------|-------|
| Rows | 10,716 |
| Columns | 178 |
| HSAs | 19 |
| Non-zero HSA-days | 8,224 (76.7%) |
| Zero-count HSA-days | 23.3% |

Three HSAs excluded from Track A (mean < 1 case/day): Mabroukeh, Aqaba, Princess Basma. Track A uses 9,024 rows from 16 HSAs.

---

## Climate Variables in the Dataset

**11 daily climate variables extracted from GEE (CHIRPS + ERA5-Land):**

| Variable | Source | Meaning |
|----------|--------|---------|
| `P_precip` | CHIRPS | Daily precipitation (mm) |
| `T_mean_C` | ERA5-Land | Daily mean 2 m temperature (°C) |
| `T_max_C` | ERA5-Land | Daily maximum temperature |
| `T_min_C` | ERA5-Land | Daily minimum temperature |
| `Td_C` | ERA5-Land | Dewpoint temperature |
| `DTR_C` | ERA5-Land | Diurnal temperature range |
| `wind_speed_ms` | ERA5-Land | 10 m wind speed (m/s) |
| `SM1`, `SM2` | ERA5-Land | Soil moisture layers 1 and 2 |
| `hours_above_30C` | ERA5-Land | Hours with T > 30°C |
| `heat_index_C` | ERA5-Land | T + 0.4 × (Td − T) |

Each variable is lagged from 1 to 14 days. Total lag columns: 154.

---

## What Is a Distributed Lag Non-Linear Model?

A DLNM extends a standard GLM to estimate effects that are:

1. **Non-linear** in the exposure dimension (the effect may not scale linearly with precipitation amount)
2. **Distributed** across lags (the effect of today's rain is spread over the coming 14 days)

**Cross-basis construction:**

```
cb(exposure, lag) = basis_exposure(exposure) ⊗ basis_lag(lag)
```

Both bases use natural cubic splines:
- Exposure basis: 5 degrees of freedom
- Lag basis: 3 degrees of freedom, max lag 14 days

This produces a 15-column design matrix per climate variable.

---

## DLNM Implementation in Python

The `dlnm/` package in this repository implements the full cross-basis pipeline:

```python
from dlnm.dlnm_crossbasis import ns_basis, build_crossbasis, cumulative_rr

# Build cross-basis for precipitation
precip_cb = build_crossbasis(
    x = df["P_precip"].values,
    lag_basis = ns_basis(np.arange(0, 15), df=3),
    exp_basis = ns_basis(precip_values, df=5)
)

# Fit quasi-Poisson GLM (statsmodels)
# [assemble design matrix with HSA FE, time spline, calendar controls]
model = sm.GLM(y, X, family=sm.families.Poisson())
result = model.fit(scale="X2")   # scale='X2' → quasi-Poisson dispersion

# Cumulative relative risk at reference exposure level
rr, ci_lo, ci_hi = cumulative_rr(result, precip_cb, ref_value=0.0)
```

The `scale="X2"` flag estimates the dispersion parameter φ from Pearson χ²/df, then rescales standard errors by √φ. This is the standard quasi-Poisson formulation.

---

## Quasi-Poisson vs Negative Binomial

Both handle overdispersion in count data. The choice matters for inference:

| Feature | Quasi-Poisson | Negative Binomial |
|---------|---------------|-------------------|
| Dispersion estimate | From Pearson χ²/df | Estimated as a free parameter |
| F-test for nested models | Yes (φ from fuller model) | No (likelihood ratio) |
| Appropriate when | φ varies across model | φ is fixed |
| Implementation | `scale='X2'` in statsmodels | `sm.NegativeBinomial` |
| Our choice | **Yes** | Alternative in sensitivity |

For daily diarrheal counts in Jordan (overdispersion φ ≈ 4–8), quasi-Poisson produces valid inference with correct standard error scaling.

---

## Base Model Structure: Track A

The full explanatory model for HSA *h* on day *t*:

```
log E[Y_{ht}] = α_h
               + f(day_of_study; df=7)         [seasonal spline]
               + Σ_k γ_k DOW_k                  [day-of-week dummies]
               + δ₁ Ramadan_t + δ₂ EidFitr_t + δ₃ EidAdha_t
               + CB_precip(P_{h,t-0:14})        [precipitation cross-basis]
               + CB_temp(T_{h,t-0:14})          [temperature cross-basis]
               + ε_{ht}
```

**α_h**: HSA fixed effects (16 dummies, one per HSA)

**Seasonal spline**: 7-knot natural spline of `day_of_study` — captures annual cycle and secular trend

**Calendar controls**: Day-of-week (6 dummies, Monday reference) + Ramadan + two Eid indicators

**Effect modifier**: `infra_quality` × cross-basis interaction for sanitation moderation analysis

---

## Track A: Expected Results

*These results are pipeline-validation placeholders. Interpret with caution when using SYNMOD data — associations with synthetic visits are not meaningful.*

With real data, expected patterns from similar LMIC settings:

- Precipitation lag: diarrheal incidence rises 3–7 days after rainfall events (fecal-oral route, water contamination pathway)
- Temperature: heat increases risk at short lags (1–3 days); the effect is non-linear (threshold around 30°C)
- DTR effect: large diurnal temperature range may reduce bacterial survival
- Sanitation interaction: precipitation–diarrhea association attenuated in HSAs with higher JMP improved sanitation coverage

The cumulative RR plot shows the integrated effect over all 14 lags at a reference precipitation value.

---

## Infrastructure as Effect Modifier

`infra_quality` is the JMP improved sanitation coverage score for each HSA (range: 0.61–0.82 in this dataset).

The interaction test fits:

```
log E[Y] = ... + CB_precip + infra_quality + CB_precip × infra_quality
```

and compares it to the model without the interaction via F-test.

**Interpretation:**

A significant negative interaction means that HSAs with better sanitation coverage show a smaller precipitation–diarrhea association — consistent with the pathway hypothesis that improved sanitation interrupts the water contamination route.

**Limitation:** Only 16 HSAs, so the interaction is estimated from cross-sectional variation in `infra_quality` — this is an ecological association, not individual-level mediation.

---

## Track B: Predictive Horizons

Track B asks a different question: can today's climate improve predictions of disease counts 1, 3, 5, 7, or 14 days ahead?

**Model at horizon h:**

```
Y_{t+h} = β₀ + β_season·f(t) + β_DOW·DOW + β_calendar·Cal
         + Σ_k β_k X_{t-k}   [climate lags 0..14]
         + β_AR Y_{t-1}       [one-day lag of outcome]
         + ε_{t+h}
```

Fit by OLS (log-transformed outcome) with HSA fixed effects.

**Evaluation:** Leave-one-year-out cross-validation (2022–2023 train → 2024 test; 2022–2024 train → extended evaluation).

**Metrics:** RMSE, MAE per horizon per HSA, and across all HSAs.

---

## Predictive Horizon Results (Expected Pattern)

With real data, typical findings in similar settings:

| Horizon | Relative RMSE vs seasonal baseline | Climate contribution |
|---------|-------------------------------------|---------------------|
| 1 day | Moderate improvement | Limited (lag too short) |
| 3 days | Best improvement | Precipitation lag 2–3 days |
| 5 days | Good improvement | Precipitation + temperature |
| 7 days | Marginal improvement | Signal degrades |
| 14 days | No improvement | Seasonal baseline dominates |

The 3–5 day horizon is the most actionable for public health early warning systems.

---

## Comparing Boundary Versions: v6 vs v7 vs v8

**Key question:** Do downstream epidemiological estimates change meaningfully across HSA delineation versions?

**What differs between versions:**

| Version | Anchors | Southern Jordan | Boundary shape |
|---------|---------|-----------------|----------------|
| v6 | 17 | Bsaira anchor; Maan/Q.Rania absorbed | Circular |
| v7 | 19 | Tafilah + Maan + Q.Rania as anchors | Circular |
| v8 | 19 | Same as v7 | Non-circular (union with satellites) |

**Expected effects on modeling:**

- v6 has fewer, larger southern HSAs — case counts per HSA differ
- v7 separates Maan and Aqaba into distinct units — smaller case counts but more precise geographic attribution
- v8 changes the population denominators (different spatial footprints)

---

## Boundary Sensitivity Analysis in `compare_delineations.ipynb`

The notebook runs side-by-side comparisons:

```python
# Load all three versions
v6 = gpd.read_file("out/INF_footprint_hsas_v6.geojson")
v7 = gpd.read_file("out/INF_footprint_hsas_v7.geojson")
v8 = gpd.read_file("out/INF_footprint_hsas_v8.geojson")

# Anchor set comparison
anchors_v6 = set(v6["anchor_name"])
anchors_v7 = set(v7["anchor_name"])
new_in_v7 = anchors_v7 - anchors_v6      # promoted/added anchors
```

**Geometric comparison:** Intersection area, Jaccard similarity per matched HSA pair.

**Allocation comparison:** For each version, how many facilities change their primary HSA assignment? How much population shifts?

**Model stability:** Are precipitation cumulative RR estimates consistent across v6, v7, v8?

---

## What the Synthetic Data Can and Cannot Tell You

**SYNMOD data preserves:**

- Temporal structure (seasonal patterns, weekly cycles, trend)
- Diagnosis category distributions (Diarrheal Diseases is present)
- Facility-level visit volume ratios
- Date range and data gaps (June 2022 gap is present)

**SYNMOD data does not preserve:**

- Spatial clustering of cases (synthetic patients are randomly assigned to facilities)
- True climate–disease associations (SYNMOD visits are uncorrelated with climate)
- Any individual patient characteristics

**Conclusion:** Run the full pipeline on SYNMOD to verify code correctness. Any statistical associations produced from SYNMOD data are artifacts of the random generation, not real climate–health signals.

All quantitative DLNM results in publications must use real patient data.

---

## Jordan Context: Why Diarrheal Diseases?

Diarrheal diseases are the primary outcome because:

1. **Known climate pathway**: waterborne and foodborne routes are directly modulated by precipitation and temperature
2. **Reportable**: consistently coded in Jordan's INF network since 2022
3. **High burden**: one of the top 5 diagnoses in Jordan's INF surveillance system
4. **Policy relevance**: Jordan faces water scarcity and infrastructure inequality — understanding climate–sanitation interactions informs WASH programming

NCD network data (chronic diseases) are used for HSA delineation validation but are not modeled in the daily climate-health pipeline.

---

## From Surveillance to Early Warning: Next Steps

The current pipeline produces retrospective associations. Converting to prospective early warning requires:

1. **Real-time GEE extraction**: automate daily climate updates instead of manual export
2. **Rolling refit**: re-estimate model monthly as new data arrives
3. **Forecast pipeline**: apply the 3–5 day prediction model to CHIRPS/ERA5 near-real-time products
4. **Alert thresholds**: define exceedance thresholds from historical distribution

This is the downstream application the daily pipeline was designed to enable.

---

## Open Methodological Questions

1. Should the DLNM be fitted separately per HSA, or as a pooled model with HSA random effects?
2. The 14-day maximum lag was chosen by default — is it appropriate for waterborne pathogens in Jordan's climate?
3. How should the gap in case counts during June 2022 affect the cross-basis estimation at the study start?
4. Track B uses OLS on log-transformed counts. Would a proper count model (NB) improve predictive accuracy at low-count HSAs?

---

## Summary

- Daily data reveals lag-specific climate–diarrhea associations that weekly aggregation obscures
- DLNM cross-basis in Python gives the same cumulative RR as R's dlnm package, with full audit trail
- Track A: explanatory quasi-Poisson model with infrastructure interaction
- Track B: five-horizon OLS prediction with climate lags
- Boundary sensitivity analysis shows which HSAs and estimates are robust across v6/v7/v8
- SYNMOD data is for pipeline validation only; real-data results are needed for inference

---

## Resources

**Repository:** `jordan-hsa-optimization_v2` (this repository)

**Key notebooks:**
- `run_climate_models_daily.ipynb` — Track A and Track B
- `compare_delineations.ipynb` — v6/v7/v8 comparison

**Key docs:**
- `DAILY_CLIMATE_HEALTH_EXPLANATION_PREDICTION.md`
- `HSA_V7_ALGORITHM_MODIFICATIONS_VS_MANUSCRIPT.md`
- `METHODOLOGY_probabilistic_allocation.md`

**External:**
- Gasparrini et al. (2010) — original DLNM paper
- Gasparrini (2011) — R dlnm package documentation
- Armstrong et al. (2019) — distributed lag models for climate-health
