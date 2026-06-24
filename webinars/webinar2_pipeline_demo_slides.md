# Running the HSA Pipeline End to End
## From Raw Data to Modeled Disease Rates

**Webinar 2 of 3 — 90 minutes**

*Live demonstration with Jordan synthetic data (SYNMOD)*

---

## Agenda

- Repository structure and prerequisites
- Step 1: Climate features by facility (Google Earth Engine)
- Step 2: HSA delineation — all three boundary variants
- Step 3: Population allocation with gravity model
- Step 4a/4b: Weekly and daily climate aggregation
- Steps 5–7: Disease counts, modeling datasets, and models
- Comparing delineation outcomes across v6/v7/v8

---

## What You Will Need

**Software:**

```
Python 3.8+
pip install -r requirements.txt
earthengine authenticate   # one-time, requires Google account
```

**Data (included in repo):**

- `data/SYNMODINF_patient_visits.csv` — 66,876 synthetic INF visits
- `data/SYNMODINF_facility_coordinates.csv` — 188 INF facility locations
- `data/adm_boundaries/` — Jordan administrative boundaries (GPKG)
- `data/hsa_metadata.csv` — JMP sanitation quality per HSA

**Data (download separately — too large for git):**

- `data/jor_ppp_2020_UNadj.tif` — WorldPop Jordan 2020 (WorldPop.org)
- `data/jor_ppp_2020_constrained.tif` — WorldPop Jordan 2020 constrained

---

## Repository Layout

```
jordan-hsa-optimization_v2/
├── data/                    ← Input data (SYNMOD + boundaries)
├── out/                     ← Runtime outputs (gitignored)
│   ├── *.geojson            ← HSA boundary bundles
│   ├── *.csv                ← Allocation tables
│   ├── DRIVE_CLIMATE_*/     ← GEE climate exports
│   └── modeling/            ← Final modeling datasets
├── dlnm/                    ← DLNM cross-basis Python package
├── HSA_FINAL.ipynb          ← Step 2: HSA delineation
├── Population_Allocation_Probabilistic_v2.ipynb   ← Step 3
├── GEE_local_*.ipynb        ← Steps 1, 4a, 4b (GEE extraction)
├── Generate_*Dataset.ipynb  ← Steps 5–6
└── run_climate_models*.ipynb ← Step 7
```

---

## Step 1 — Climate Features by Facility

**Notebook:** `GEE_local_Climate_Features_by_Facilities.ipynb`

**Purpose:** Extract climate cluster assignments for each facility — used by the HSA optimizer to measure climate diversity.

**What it does:**

1. Loads facility coordinates into GEE as a feature collection
2. Samples ERA5-Land temperature, CHIRPS precipitation, and TerraClimate at each facility
3. Clusters facilities into 5 climate zones using k-means
4. Exports `{NETWORK}_Facilities_Climate_Features_with_clusters.csv`

**Output location:** Copy to `out/`

**Runtime:** ~5 minutes for 188 facilities

*Demo: run the notebook, inspect the cluster assignments*

---

## What Climate Clusters Look Like

The five climate clusters in Jordan capture:

| Cluster | Character | Governorates |
|---------|-----------|--------------|
| 1 | Hot, arid (desert) | Ma'an, Aqaba |
| 2 | Hot semi-arid | Zarqa, Balqa periphery |
| 3 | Mediterranean highland | Amman, Madaba |
| 4 | Northern semiarid | Irbid, Ajloun, Jarash |
| 5 | Steppe/badia | Mafraq, eastern desert |

The optimizer's climate diversity score rewards selecting anchors from different clusters — preventing all anchors from clustering in the Amman metropolitan area.

---

## Step 2 — HSA Delineation

**Notebook:** `HSA_FINAL.ipynb`

**Set at the top:**

```python
NETWORK = "INF"   # or "NCD"
```

The notebook then loops over all three algorithm variants and five optimization modes.

**What it produces (15 files):**

```
out/INF_fewest_hsas_v6.geojson
out/INF_fewest_hsas_v7.geojson
out/INF_fewest_hsas_v8.geojson
out/INF_footprint_hsas_v6.geojson
...  (5 modes × 3 variants = 15 files)
```

**Runtime:** ~8–12 minutes total (5 modes × 3 variants × ~17–21 anchor selections)

---

## Inside the Optimizer: Live Trace

```
Mode: footprint  |  Variant: v7
Coverage target: 90%

Iteration  1: Al-Basheer Hospital          score=0.847  coverage=31.2%
Iteration  2: AL-Zarqa Hospital            score=0.731  coverage=42.1%
Iteration  3: AL-Ramtha Hospital           score=0.612  coverage=49.8%
...
Iteration 15: Aqaba Comprehensive Center   score=0.201  coverage=87.3%
Iteration 16: AL-Shuneh Hospital           score=0.178  coverage=89.1%
Iteration 17: Princess Raya Hospital       score=0.094  coverage=90.6%

─── Anchor upgrade step ───
  Bsaira Comp. Center  →  Tafilah Governmental Hospital  (ratio 4.09×)
  North Madaba Comp.   →  AL-Nadeem Hospital              (ratio 4.85×)
  [3 more upgrades]

─── Major-orphan promotion ───
  Maan Hospital promoted    (72.6 km from Tafilah, cross-governorate)
  Queen Rania promoted      (64.6 km from Tafilah, cross-governorate)

Final anchors: 19
```

---

## Inspecting the GeoJSON Output

```python
import geopandas as gpd
import matplotlib.pyplot as plt

v6 = gpd.read_file("out/INF_footprint_hsas_v6.geojson")
v7 = gpd.read_file("out/INF_footprint_hsas_v7.geojson")

print(v6[["anchor_name", "mode", "population_coverage"]].head())

fig, axes = plt.subplots(1, 2, figsize=(14, 7))
v6.plot(ax=axes[0], column="anchor_name", legend=False)
v7.plot(ax=axes[1], column="anchor_name", legend=False)
axes[0].set_title("v6: 17 anchors")
axes[1].set_title("v7: 19 anchors")
```

*Demo: show the visual difference in southern Jordan between v6 and v7*

---

## Step 3 — Patient Allocation

**Notebook:** `Population_Allocation_Probabilistic_v2.ipynb`

**Set at the top:**

```python
NETWORK = "INF"
HSA_MODE = "footprint"
BOUNDARY_VERSION = "v7"   # v6, v7, or v8
```

**Two-step process:**

1. Gravity model pixel allocation: each WorldPop 100m cell split across all reachable facilities (α=0.75, β=1.5)
2. Facility → HSA aggregation by spatial containment case (inside 1 / outside all / overlapping)

**Output:**

```
out/INF_footprint_facility_hsa_assignments_v7.csv
```

**Runtime:** ~5–15 minutes (rasterio required for WorldPop)

---

## Why WorldPop Instead of Census?

**Census grids** in Jordan are administrative unit–based: population is uniform within each census unit. They miss the within-unit variation between dense cities and empty desert.

**WorldPop 100m rasters** estimate population at every 100m cell using dasymetric disaggregation from census totals + land-use and settlement layers. Two products:

- `jor_ppp_2020_UNadj.tif` — unconstrained (all land)
- `jor_ppp_2020_constrained.tif` — constrained to settled areas only

The constrained product is used for HSA footprint delineation (no population assigned to desert). The unconstrained product is kept as a cross-check.

*Demo: plot the WorldPop raster alongside the HSA boundaries*

---

## Reading the Allocation Table

```python
import pandas as pd

alloc = pd.read_csv("out/INF_footprint_facility_hsa_assignments_v7.csv")

# Case distribution
print(alloc["assignment_case"].value_counts())

# Facilities with gravity split across HSAs
split = alloc[alloc["num_containing_hsas"] > 1]
print(split[["facility_id", "all_containing_hsas", "excluded"]].head())
```

Expected output:

```
Case 1: Inside 1 HSA           145
Case 2: Outside (admissible)    41
Case 3: Overlapping (gravity)    5
EXCLUDED: no admissible fallback 1    ← Swaqa Correctional Primary
```

*Demo: trace one facility from Case 2 assignment through to HSA population total*

---

## Step 4a — Weekly Climate Aggregation

**Notebook:** `GEE_local_HSA_Weekly_Climate_Lagged.ipynb`

**Sources:** CHIRPS daily + ERA5-Land + TerraClimate

**Output:** One CSV per HSA per variable, weekly averages with lags 0–8 weeks.

**For v6 boundaries:** Pre-computed CSVs are included in `v2_real` under:

```
out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD/FINAL_HSA_CLIMATE/
```

102 files: 17 HSAs × 6 climate variables.

**For v7 or v8:** Re-run the notebook with the new boundary GeoJSON. Export to Google Drive, then copy to `out/`.

**Note:** GEE exports may take 15–60 minutes for 17+ polygons × 2+ years of daily data.

---

## Step 4b — Daily Climate Aggregation

**Notebook:** `GEE_local_HSA_Daily_Climate.ipynb`

**Sources:** CHIRPS daily + ERA5-Land hourly (aggregated to daily)

**Export period:** 2022-06-01 to 2024-01-31 (includes 14-day lag buffer before study start)

**Output:** One CSV per HSA with 11 daily climate variables:

```
P_precip, T_mean_C, T_max_C, T_min_C,
Td_C, DTR_C, wind_speed_ms, SM1, SM2,
hours_above_30C, heat_index_C
```

**For v7 boundaries:** Pre-computed CSVs are included in `v2_real`:

```
out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/
```

23 files (19 active HSAs + older exports).

---

## Step 5 — Daily Disease Counts

**Script:** `generate_daily_disease_counts.py`

```bash
# Real patient data (v2_real only):
python3 generate_daily_disease_counts.py --boundary-version v7

# Synthetic data (v2):
python3 generate_daily_disease_counts.py \
  --boundary-version v7 \
  --patient-file data/SYNMODINF_patient_visits.csv
```

**What it does:**

1. Loads `out/INF_footprint_facility_hsa_assignments_v7.csv`
2. Filters patient visits to Diarrheal Diseases, 2022-07-01 to 2024-01-31
3. Expands each visit to gravity-weighted HSA-day records
4. Aggregates to daily HSA panel, fills zero days
5. Flags 38 known system reporting gaps as NaN

**Output:** `out/INF_footprint_daily_diarrheal.csv` — 11,020 rows

---

## Reporting Gaps: Why They Matter

The INF system has known data gaps that look like zero-case days but are actually missing data:

- June 2–30, 2022: system migration gap at start of data collection
- May 30–31, 2023: two-day reporting outage

If these are treated as real zeros, the DLNM will estimate a negative climate effect around late May/early June every year — a false signal driven by data absence, not disease dynamics.

The script flags these rows with `is_reporting_gap = 1` and sets `diarrheal_count = NaN`. The modeling dataset preparation step then removes them.

---

## Step 6 — Assemble Daily Modeling Dataset

**Script:** `prepare_daily_modeling_dataset.py`

```bash
python3 prepare_daily_modeling_dataset.py
```

**What it builds:**

1. Merges daily health + daily climate on `hsa_id, date`
2. Builds within-HSA climate lag matrix: lags 1–14 days
3. Drops first 14 rows per HSA (insufficient lag history)
4. Removes reporting gaps and NaN outcomes
5. Adds calendar features: `day_of_study`, `day_of_week`, `month`, Ramadan/Eid indicators
6. Merges `infra_quality` from `data/hsa_metadata.csv`

**Output:** `out/modeling/INF_footprint_daily_modeling_dataset.csv`

- 10,716 rows, 178 columns, 19 HSAs
- 11 climate vars × 14 lags = 154 lag columns

---

## Calendar Feature Logic

Jordan's healthcare attendance has strong day-of-week and religious calendar patterns:

| Pattern | Mean cases vs baseline | Mechanism |
|---------|------------------------|-----------|
| Friday | 49.7% | Jumu'ah prayer day; most clinics closed |
| Ramadan | 68.0% | Reduced health-seeking during fasting |
| Eid al-Fitr | 53.4% | Multi-day holiday |
| Eid al-Adha | 60.6% | Multi-day holiday |
| Saturday | 92.8% | Normal service day in Jordan |

These are modeled as indicator variables. Without them, climate coefficients would absorb religious calendar signals — producing spurious associations between climate and diarrheal cases during Ramadan months (which often fall in spring/summer).

---

## Step 7 — Run Daily Climate-Health Models

**Notebook:** `run_climate_models_daily.ipynb`

**Two modeling tracks:**

**Track A — Explanatory DLNM (quasi-Poisson):**

- Does precipitation exposure over the past 14 days associate with diarrheal incidence?
- Is the association modified by sanitation infrastructure quality?
- Uses natural spline cross-basis; cumulative relative risk with 95% CI

**Track B — Predictive OLS:**

- Can daily climate improve 1-, 3-, 5-, 7-, 14-day ahead predictions?
- Five forecast horizons with RMSE and MAE evaluation

*Demo: run the first 4 cells; display the cumulative RR plot from Track A*

---

## What a DLNM Cross-Basis Looks Like

```python
from dlnm.dlnm_crossbasis import ns_basis, build_crossbasis

# Natural spline basis for precipitation exposure (5 df)
df_exp = ns_basis(precip_values, df=5)

# Natural spline basis for lag dimension (3 df, max lag = 14)
df_lag = ns_basis(np.arange(0, 15), df=3)

# Cross-basis: outer product of exposure and lag bases
cb = build_crossbasis(precip_values, lag_basis=df_lag, exp_basis=df_exp)
# Shape: (n_obs, 5 × 3) = (n_obs, 15)
```

The cross-basis captures both the exposure–response curve (how the effect varies with precipitation amount) and the lag–response curve (how the effect distributes over the 14-day window).

Fitting uses quasi-Poisson GLM via statsmodels with Pearson chi² dispersion scaling.

---

## Comparing v6, v7, v8 Delineations

**Notebook:** `compare_delineations.ipynb`

Run for each boundary version:

```python
BOUNDARY_VERSION = "v7"   # change to v6 or v8
```

**Comparison dimensions:**

| Dimension | What to check |
|-----------|--------------|
| Anchor count | v6: 17, v7: 19, v8: 19 |
| Anchor identity | Which anchors changed? |
| HSA geometry | Area, compactness, overlap |
| Population allocation | How many facilities reassigned? |
| Disease rate maps | Do case rates differ across versions? |
| Model coefficients | Are climate estimates stable? |

*See `SPATIAL_METHODS_COMPARISON.md` for full metric table.*

---

## Practical Notes for Running the Pipeline

**GEE authentication:**

```bash
earthengine authenticate   # opens browser, one-time per machine
```

**Output directory:**

All notebooks default to `out/`. Override with:

```bash
HSA_OUT_DIR=/path/to/output jupyter notebook HSA_FINAL.ipynb
```

**WorldPop download:**

```
https://www.worldpop.org → Jordan → Population → 2020 → Unconstrained
```

Place as `data/jor_ppp_2020_UNadj.tif`.

**Python environment:**

```bash
conda create -n hsa python=3.10
conda activate hsa
pip install -r requirements.txt
```

---

## Full Run Time Estimates

| Step | Notebook/Script | Typical Time |
|------|----------------|--------------|
| Step 1: Facility climate | GEE_local_Climate_Features | 5 min |
| Step 2: HSA delineation | HSA_FINAL.ipynb | 8–12 min |
| Step 3: Population allocation | Population_Allocation_Probabilistic_v2 | 5–15 min |
| Step 4a: Weekly climate | GEE_local_HSA_Weekly_Climate_Lagged | 30–60 min |
| Step 4b: Daily climate | GEE_local_HSA_Daily_Climate | 60–120 min |
| Step 5: Daily counts | generate_daily_disease_counts.py | <1 min |
| Step 6: Modeling dataset | prepare_daily_modeling_dataset.py | <1 min |
| Step 7a: Weekly models | run_climate_health_modeling | 5–10 min |
| Step 7b: Daily DLNM | run_climate_models_daily | 10–20 min |

Steps 4a and 4b depend on GEE queue; actual export may be longer during peak hours.

---

## Key Outputs for Publication

| Output | File | Used in |
|--------|------|---------|
| HSA boundary maps | `out/*_hsas_v7.geojson` | Figure 2 |
| Allocation table | `out/*_facility_hsa_assignments_v7.csv` | Table S-X |
| HSA populations | `out/*_hsa_populations_probabilistic.csv` | Table 3 |
| Daily modeling dataset | `out/modeling/*_daily_modeling_dataset.csv` | Analysis |
| DLNM cumulative RR | (notebook output) | Figure 4 |
| Predictive RMSE table | (notebook output) | Table 5 |

---

## Q&A and Live Demonstration

*This slide is a placeholder for the live demo portion of the webinar.*

*Suggested demonstration sequence:*

1. Open `HSA_FINAL.ipynb` — run Cell 1 (params) and Cell 5 (optimizer loop) for INF-footprint v7
2. Display the GeoJSON anchor list and the southern Jordan upgrade/promotion log
3. Open `generate_daily_disease_counts.py` — run with SYNMOD flag
4. Display `out/INF_footprint_daily_diarrheal.csv` statistics
5. Open `run_climate_models_daily.ipynb` — run through Track A DLNM cells
6. Display cumulative relative risk plot for precipitation

*Estimated: 40 minutes for live demo, 10 minutes Q&A*
