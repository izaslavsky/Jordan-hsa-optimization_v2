# Hospital Service Area Optimization and Climate-Health Analysis — v2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Code and synthetic data accompanying the research paper on delineating Hospital Service Areas (HSAs) using patient trajectory data and analyzing climate-health relationships in Jordan. This is **v2** of the repository, which adds three algorithm variants for HSA boundary delineation, a daily climate-health epidemiological pipeline, and a DLNM cross-basis module. The original repository (`jordan-hsa-optimization`) retains the v6 baseline algorithm and weekly modeling pipeline.

---

## What is new in v2

### Three HSA algorithm variants

`HSA_FINAL.ipynb` runs all three variants in a single execution and writes versioned boundary bundles:

| Bundle | Algorithm | Key additions |
|--------|-----------|---------------|
| **v6** | Greedy multi-objective optimization only | Baseline — no post-selection corrections |
| **v7** | v6 + anchor quality-control | Weak anchors replaced by stronger nearby facilities; major hospitals without a plausible fallback promoted to anchors |
| **v8** | v7 + satellite bubble boundaries | HSA polygons union the anchor catchment with smaller secondary catchments around eligible nearby facilities |

All downstream notebooks select a bundle via `BOUNDARY_VERSION = "v6" | "v7" | "v8"` near the top of each notebook. See `HSA_V7_ALGORITHM_MODIFICATIONS_VS_MANUSCRIPT.md` for a full description of the v7 and v8 changes.

### Daily climate-health pipeline

A second modeling track built on daily data:

- `GEE_local_HSA_Daily_Climate.ipynb` extracts daily climate from Google Earth Engine (CHIRPS + ERA5-Land) for each HSA polygon.
- `generate_daily_disease_counts.py` produces daily diarrheal case counts per HSA from patient visit records.
- `prepare_daily_modeling_dataset.py` assembles a daily panel with 14-day climate lags and infrastructure covariates.
- `Generate_Daily_Modeling_Dataset.ipynb` orchestrates these steps.
- `run_climate_models_daily.ipynb` runs two modeling tracks:
  - **Track A**: Explanatory quasi-Poisson DLNM — tests whether climate associations are modified by sanitation/infrastructure quality.
  - **Track B**: Predictive OLS at five forecast horizons.

See `DAILY_CLIMATE_HEALTH_EXPLANATION_PREDICTION.md` for methodology and results.

### DLNM module

The `dlnm/` subdirectory contains a Python implementation of distributed lag non-linear models:

- `dlnm_crossbasis.py` — natural spline cross-basis construction and cumulative RR computation
- `dlnm_quasipoisson.py` — quasi-Poisson GLM fitting with Pearson-chi2 scale
- `dlnm_env_screening.py` — automated screening of environmental exposures
- `dlnm_daily_lags.py` — lag-specific effect extraction

Import with `from dlnm.dlnm_crossbasis import ns_basis, build_crossbasis, cumulative_rr`.

### Improved patient allocation

`Patient_Allocation_Probabilistic_v2.ipynb` (using updated `patient_allocation.py`) replaces the previous nearest-anchor fallback with an admissibility-limited fallback: facilities outside all HSA radii are assigned only to anchors within a distance limit derived from the anchor's service radius, with same-governorate preference for major facilities. Facilities that fail the admissibility check are reported rather than silently attached to a distant anchor.

---

## Repository structure

```
jordan-hsa-optimization_v2/
├── data/
│   ├── adm_boundaries/              Administrative boundaries (governorate/district/subdistrict)
│   ├── SYNMODINF_facility_coordinates.csv   INF facility locations
│   ├── SYNMODINF_groups_of_diagnoses.csv    ICD groupings for INF network
│   ├── SYNMODINF_patient_visits.csv         Synthetic INF patient visits (2019–2024)
│   ├── SYNMODNCD_facility_coordinates.csv   NCD facility locations
│   ├── SYNMODNCD_groups_of_diagnoses.csv    ICD groupings for NCD network
│   ├── SYNMODNCD_patient_visits.csv         Synthetic NCD patient visits
│   ├── jordan_boundary.gpkg
│   ├── jordan_governorates.gpkg
│   └── hsa_metadata.csv                     JMP sanitation quality scores per HSA
│   [WorldPop rasters not included — see Installation below]
├── dlnm/                            DLNM cross-basis module
├── out/                             Runtime outputs (gitignored except .gitkeep)
├── HSA_FINAL.ipynb                  HSA delineation (produces v6, v7, v8 bundles)
├── Patient_Allocation_Probabilistic_v2.ipynb
├── Patient_Allocation_for_Modeling.ipynb
├── GEE_local_Climate_Features_by_Facilities.ipynb
├── GEE_local_HSA_Daily_Climate.ipynb
├── GEE_local_HSA_Weekly_Climate_Lagged.ipynb
├── GEE_local_HSA_Weekly_Climate_Lagged_chunked.ipynb
├── GEE_Climate_Features_by_Facilities.ipynb
├── GEE_HSA_Weekly_Climate_Lagged.ipynb
├── Generate_Modeling_Dataset.ipynb
├── Generate_Daily_Modeling_Dataset.ipynb
├── run_climate_health_modeling.ipynb
├── run_climate_models_daily.ipynb
├── compare_delineations.ipynb
├── hsa_optimization.py              Core algorithm (v6/v7/v8 via flags)
├── patient_allocation.py            Probabilistic gravity allocation (v2 fallback)
├── generate_daily_disease_counts.py
├── prepare_daily_modeling_dataset.py
├── [... other scripts]
└── [... documentation]
```

---

## Synthetic data

`SYNMOD` files preserve the statistical properties of the real data, including temporal structure, seasonal patterns, and diagnosis-category distributions. Facility coordinates and ICD groupings are identical to the real data. Patient IDs and specific visit records are synthetic.

**Caveat**: Climate associations and explanatory DLNM results using SYNMOD data should be treated as pipeline validation, not scientific findings. Real outcome data is required for substantive inference.

---

## Installation

```bash
git clone <repo-url>
cd jordan-hsa-optimization_v2
pip install -r requirements.txt
earthengine authenticate   # required for GEE notebooks
```

### WorldPop rasters

The population rasters are not committed (too large). Download them from WorldPop and place in `data/`:

| File | URL |
|------|-----|
| `jor_ppp_2020_UNadj.tif` | https://www.worldpop.org — Jordan 2020 unconstrained |
| `jor_ppp_2020_constrained.tif` | https://www.worldpop.org — Jordan 2020 constrained |

---

## Running the pipeline

### Step 1 — Climate features by facility

Extract facility-level climate features (required by HSA_FINAL.ipynb):

```bash
# Local execution:
jupyter notebook GEE_local_Climate_Features_by_Facilities.ipynb
# Or upload to Google Colab:
# GEE_Climate_Features_by_Facilities.ipynb
```

Copy the output `{NETWORK}_Facilities_Climate_Features_with_clusters.csv` into `out/`.

### Step 2 — HSA delineation (all three variants)

```bash
jupyter notebook HSA_FINAL.ipynb
```

This runs all five optimization modes for each of the three algorithm variants (v6, v7, v8). Output files are written to `out/` with the pattern `{NETWORK}_{mode}_hsas_{variant}.geojson`. One full execution produces 15 boundary files (5 modes × 3 variants).

### Step 3 — Patient allocation

Set `BOUNDARY_VERSION` in the notebook, then run:

```bash
jupyter notebook Patient_Allocation_Probabilistic_v2.ipynb
```

Repeat for each boundary version you want to use downstream.

### Step 4a — Weekly climate aggregation (for weekly disease modeling)

**Note**: Pre-computed weekly climate CSVs are available for v6 boundaries. For v7 or v8 boundaries, re-run the GEE notebook and download the new exports.

```bash
# Local:
jupyter notebook GEE_local_HSA_Weekly_Climate_Lagged.ipynb
# After export finishes, place CSVs in:
# out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD/FINAL_HSA_CLIMATE/
```

### Step 4b — Daily climate aggregation (for daily disease modeling)

**Note**: Pre-computed daily climate CSVs are available for v7 boundaries.

```bash
jupyter notebook GEE_local_HSA_Daily_Climate.ipynb
# After export finishes, place CSVs in:
# out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/
```

### Step 5 — Generate disease counts

**Weekly** (requires real or SYNMOD patient visits):
Run `Generate_Modeling_Dataset.ipynb` with `BOUNDARY_VERSION` set.

**Daily** (uses real data by default; pass `--patient-file` for synthetic):
```bash
python generate_daily_disease_counts.py \
  --boundary-version v7 \
  --patient-file data/SYNMODINF_patient_visits.csv   # omit for real data
```

### Step 6 — Assemble modeling datasets

**Daily**:
```bash
python prepare_daily_modeling_dataset.py
# output: out/modeling/INF_footprint_daily_modeling_dataset.csv
```

**Weekly**:
```bash
jupyter notebook Generate_Modeling_Dataset.ipynb
```

### Step 7 — Run models

**Daily DLNM + predictive**:
```bash
jupyter notebook run_climate_models_daily.ipynb
```

**Weekly climate-health**:
```bash
jupyter notebook run_climate_health_modeling.ipynb
```

### Optional — Compare delineation methods

```bash
jupyter notebook compare_delineations.ipynb
```

---

## Workflow diagram

```
Step 1  Climate by Facility (GEE_local_Climate_Features_by_Facilities)
            │
            ▼
Step 2  HSA_FINAL.ipynb
            │  ┌─────────────────────┐
            │  │ v6: greedy only      │
            │  │ v7: + anchor QC      │  → out/{NETWORK}_{mode}_hsas_{v6|v7|v8}.geojson
            │  │ v8: + bubbles        │
            │  └─────────────────────┘
            │
            ▼
Step 3  Patient_Allocation_Probabilistic_v2  (BOUNDARY_VERSION = v6|v7|v8)
            │  → out/INF_footprint_facility_hsa_assignments_{version}.csv
            │
     ┌──────┴──────┐
     ▼             ▼
Step 4a            Step 4b
Weekly GEE         Daily GEE
(v6 pre-computed)  (v7 pre-computed)
     │             │
     ▼             ▼
Step 5a            Step 5b
Generate_Modeling  generate_daily_disease_counts.py
_Dataset.ipynb     (--boundary-version v7)
     │             │
     ▼             ▼
Step 6a            Step 6b
Weekly modeling    prepare_daily_modeling_dataset.py
dataset            daily modeling dataset
     │             │
     ▼             ▼
run_climate_health  run_climate_models_daily.ipynb
_modeling.ipynb     Track A: DLNM (explanatory)
                    Track B: OLS horizons (predictive)
```

---

## Climate data note

Weekly climate CSVs (CHIRPS + ERA5-Land + TerraClimate, one file per HSA per variable) are available for **v6 boundaries** only. For other boundary versions, re-run `GEE_local_HSA_Weekly_Climate_Lagged.ipynb` or the chunked variant.

Daily climate CSVs (CHIRPS + ERA5-Land hourly aggregated to daily) are available for **v7 boundaries** only. For v6 or v8, re-run `GEE_local_HSA_Daily_Climate.ipynb`.

---

## Documentation

| File | Contents |
|------|----------|
| `HSA_V7_ALGORITHM_MODIFICATIONS_VS_MANUSCRIPT.md` | Detailed description of v7 and v8 algorithm changes vs. the manuscript |
| `DAILY_CLIMATE_HEALTH_EXPLANATION_PREDICTION.md` | Daily pipeline methodology and results |
| `METHODOLOGY_probabilistic_allocation.md` | Population allocation methodology |
| `HSA_POPULATION_CLIPPING.md` | Why and how HSA polygons are clipped to inhabited WorldPop cells |
| `CLIMATE_HEALTH_MODELING.md` | Weekly climate-health modeling methodology |
| `SPATIAL_METHODS_COMPARISON.md` | Comparison of delineation approaches |
| `DATA_FLOW_ANALYSIS.md` | End-to-end data flow description |
| `ANALYSIS_VERIFICATION.md` | Verification checks on outputs |
| `SETUP_INSTRUCTIONS.md` | GEE and Google Drive credential setup |

---

## Citation

```bibtex
@software{hsa_climate_health_v2_2025,
  title  = {Hospital Service Area Optimization and Climate-Health Analysis, v2},
  author = {Zaslavsky, Ilya},
  year   = {2025},
  note   = {Three-variant HSA delineation with daily DLNM epidemiological pipeline}
}
```

---

## License

MIT License. See [LICENSE](LICENSE).

**Data licenses**: Administrative boundaries: ODbL (OpenStreetMap). Synthetic patient data: public domain. Climate data: see individual source licenses (CHIRPS, ERA5-Land, TerraClimate, WorldPop).
