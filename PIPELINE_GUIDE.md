# Pipeline Guide: All Interesting Combinations

Step-by-step instructions for running the full pipeline across networks, HSA modes, and boundary versions.

---

## Automated Pipeline Runner

`run_pipeline.py` automates all six local-computation steps. The three GEE extraction notebooks still require manual execution (Earth Engine auth, Google Drive polling), but there is a dependency between them and the local steps that requires the run to be split into two phases.

### Why two phases?

Weekly and daily climate aggregation (GEE Steps B and C) operate on HSA *polygons*, which do not exist until Step 1 (HSA delineation) has run. The correct order is:

```
GEE Step A  ──►  pipeline Steps 1–2  ──►  GEE Steps B & C  ──►  pipeline Steps 3–6
(facility        (delineate HSAs,          (aggregate climate      (datasets +
 climate,         allocate pop)             per HSA polygon)        models)
 no HSAs
 needed)
```

### Phase 1: delineate boundaries

Run GEE Step A first (`GEE_local_Climate_Features_by_Facilities.ipynb` — needs only facility coordinates, no HSA boundaries). Then:

```bash
python run_pipeline.py \
    --network INF --hsa-mode footprint \
    --boundary-version v7 --disease-focus diarrheal \
    --study-start 2022-07-01 --study-end 2024-01-31 \
    --week-start 2019-01-07 --week-end 2024-01-29 \
    --ml-start-date 2022-06-27 --ml-end-date 2024-01-29 \
    --only-steps 1,2
```

This produces `out/INF_footprint_hsas_v7.geojson` (and v6/v8) plus the population allocation tables.

### Phase 2: run models

After running GEE Steps B (`GEE_local_HSA_Weekly_Climate_Lagged.ipynb`) and C (`GEE_local_HSA_Daily_Climate.ipynb`) using the boundaries from Phase 1:

```bash
python run_pipeline.py \
    --network INF --hsa-mode footprint \
    --boundary-version v7 --disease-focus diarrheal \
    --study-start 2022-07-01 --study-end 2024-01-31 \
    --week-start 2019-01-07 --week-end 2024-01-29 \
    --ml-start-date 2022-06-27 --ml-end-date 2024-01-29 \
    --only-steps 3,4,5,6
```

### Date parameters explained

Three separate date ranges appear in every `run_pipeline.py` invocation, each driven by a different data constraint:

| Parameter | Example | Controls |
|-----------|---------|----------|
| `--week-start` / `--week-end` | 2019-01-07 — 2024-01-29 | Weekly disease count aggregation |
| `--ml-start-date` / `--ml-end-date` | 2022-06-27 — 2024-01-29 | Weekly ML modeling window |
| `--study-start` / `--study-end` | 2022-07-01 — 2024-01-31 | Daily DLNM analysis window |

**`--week-start` / `--week-end`** span the full HMIS patient visit history. Disease counts are aggregated into ISO weeks across this entire range regardless of whether climate data exists. The period begins in 2019 because that is when the HMIS records start.

**`--ml-start-date` / `--ml-end-date`** define the subset of weeks where both disease counts *and* GEE climate features are available. Climate extraction by HSA polygon only covers from mid-2022 onward, so earlier weeks have disease counts but no predictors and cannot enter the model. The start is June 27 rather than July 1 because the weekly pipeline aligns to ISO week boundaries (Monday–Sunday): June 27 is the Monday of the week containing July 1.

**`--study-start` / `--study-end`** define the daily DLNM window. The start is July 1 rather than June 27 because the HMIS system had a confirmed system-wide reporting gap from June 2–30 2022 (recorded in `data/reporting_gaps.csv`): those dates show zero visits across all diagnoses, not true disease absence. The daily pipeline works in calendar days with no week-alignment offset, so July 1 is the first usable date.

The ML weekly start (June 27) and daily study start (July 1) are close but different for exactly this reason: one is week-aligned, the other is day-aligned to the end of the reporting gap.

### What the runner does

- **Pre-flight check:** imports every required package at startup and prints all missing ones with `pip install` commands before touching any notebook. A missing package fails in under a second rather than after 20+ minutes of execution.
- **Parameter injection:** injects NETWORK, HSA_MODE, BOUNDARY_VERSION, DISEASE_FOCUS, and all date ranges into notebook config cells automatically.
- **Reproducibility:** sets `PYTHONHASHSEED=42` in every kernel environment and prepends `random.seed(42)` / `np.random.seed(42)` as the first cell. Without a fixed seed, Python's hash randomization causes the greedy HSA optimizer to select different anchor facilities each run.
- **Progress output:** prints a heartbeat line every 30 seconds during each notebook, with wall-clock timestamps and elapsed time per step.
- **Failure artifacts:** saves the executed notebook (with all cell outputs) to `_pipeline_runs/{NETWORK}_{HSA_MODE}_{BOUNDARY_VERSION}/` for post-hoc inspection.

**Required packages** (beyond the base `requirements.txt`): `rasterio`, `affine`, and `adjustText`. The pre-flight check will tell you immediately if any are missing.

---

## Prerequisites

```bash
# Python environment
conda create -n hsa python=3.10 && conda activate hsa
pip install -r requirements.txt

# Google Earth Engine (one-time)
earthengine authenticate

# WorldPop rasters (download to data/)
#   https://www.worldpop.org → Jordan → Population → 2020 → 100m Unconstrained
#   jor_ppp_2020_UNadj.tif
#   jor_ppp_2020_constrained.tif
```

Check that all inputs are present:

```bash
ls data/SYNMODINF_facility_coordinates.csv    # INF synthetic facilities
ls data/SYNMODINF_patient_visits.csv          # INF synthetic visits
ls data/SYNMODNCD_facility_coordinates.csv    # NCD synthetic facilities
ls data/SYNMODNCD_patient_visits.csv          # NCD synthetic visits
ls data/jordan_boundary.gpkg                  # Jordan outline
ls data/jordan_governorates.gpkg              # Governorate boundaries
ls data/hsa_metadata.csv                      # JMP sanitation quality (v6 HSAs)
ls data/jor_ppp_2020_UNadj.tif               # WorldPop raster (if needed)
```

---

## Quick Start: Synthetic INF Footprint Pipeline (v7)

This is the minimal run to verify the pipeline end to end:

```bash
# Step 2: HSA delineation (all 3 variants in one run)
jupyter notebook HSA_FINAL.ipynb
# Set NETWORK = "INF"
# Produces: out/INF_footprint_hsas_v6.geojson, v7, v8

# Step 3: Population allocation for v7
jupyter notebook Population_Allocation_Probabilistic_v2.ipynb
# Set NETWORK="INF", HSA_MODE="footprint", BOUNDARY_VERSION="v7"
# Produces: out/INF_footprint_facility_hsa_assignments_v7.csv

# Step 5: Daily disease counts
python3 generate_daily_disease_counts.py \
  --boundary-version v7 \
  --patient-file data/SYNMODINF_patient_visits.csv

# Step 6: Modeling dataset
python3 prepare_daily_modeling_dataset.py

# Step 7: Daily models
jupyter notebook run_climate_models_daily.ipynb
# Set BOUNDARY_VERSION = "v7"
```

---

## Full Combination Matrix

### Dimension 1: Network

| Network | Facilities | Patient visits |
|---------|-----------|---------------|
| `INF` | 188 | `SYNMODINF_patient_visits.csv` (synthetic) |
| `NCD` | 192 | `SYNMODNCD_patient_visits.csv` (synthetic) |

Set `NETWORK` at the top of each notebook.

### Dimension 2: HSA Mode

| Mode | Use case |
|------|---------|
| `footprint` | General epidemiological modeling (recommended default) |
| `fewest` | Sensitivity: minimum anchor set |
| `distance` | Sensitivity: access-optimized boundaries |
| `governorate_fewest` | Policy: at least one anchor per governorate |
| `governorate_tau_coverage` | Policy: governorate-constrained with coverage threshold |

Set `HSA_MODE` in `Population_Allocation_Probabilistic_v2.ipynb`, `Generate_Modeling_Dataset.ipynb`, and downstream notebooks.

### Dimension 3: Boundary Version

| Version | Algorithm | When to use |
|---------|-----------|------------|
| `v6` | Greedy only | Baseline / paper comparison |
| `v7` | + Anchor QC | Default for all modeling |
| `v8` | + Satellite bubbles | Boundary sensitivity only |

---

## Combinations Actually Worth Running

Not all 2 × 5 × 3 = 30 combinations are meaningful. Recommended runs:

| Priority | Network | Mode | Version | Rationale |
|----------|---------|------|---------|-----------|
| **1** | INF | footprint | v7 | Primary modeling track |
| **2** | INF | footprint | v6 | Manuscript baseline comparison |
| **3** | INF | footprint | v8 | Boundary sensitivity check |
| **4** | NCD | footprint | v7 | Second network validation |
| **5** | INF | fewest | v7 | Sensitivity: fewer, larger HSAs |
| **6** | INF | distance | v7 | Sensitivity: access-focused |
| **7** | INF | governorate_fewest | v7 | Policy scenario |

Runs 1–4 are sufficient for the paper. Runs 5–7 are for robustness tables.

---

## Step-by-Step: All Seven Priority Combinations

### Step 1: Climate Features by Facility (once per network)

```bash
# INF network
jupyter notebook GEE_local_Climate_Features_by_Facilities.ipynb
# Set NETWORK = "INF"
# Copy output to: out/INF_Facilities_Climate_Features_with_clusters.csv

# NCD network
# Set NETWORK = "NCD"
# Copy output to: out/NCD_Facilities_Climate_Features_with_clusters.csv
```

This step only needs to run once per network, regardless of mode or version.

### Step 2: HSA Delineation (once per network — produces all modes and all versions)

```bash
jupyter notebook HSA_FINAL.ipynb
# Set NETWORK = "INF"   → produces 15 files (5 modes × 3 versions)
# Then NETWORK = "NCD"  → produces 15 more files
```

Output pattern: `out/{NETWORK}_{MODE}_hsas_{v6|v7|v8}.geojson`

Total files: 30 GeoJSONs for both networks.

### Step 3: Patient Allocation (once per network × mode × version)

For each combination in the priority table:

```bash
jupyter notebook Population_Allocation_Probabilistic_v2.ipynb
```

Set at the top:

```python
NETWORK = "INF"      # or "NCD"
HSA_MODE = "footprint"   # or "fewest", "distance", etc.
BOUNDARY_VERSION = "v7"  # or "v6", "v8"
```

Output: `out/{NETWORK}_{MODE}_facility_hsa_assignments_{VERSION}.csv`

**Run sequence for all seven priority combinations:**

| Run | NETWORK | HSA_MODE | BOUNDARY_VERSION |
|-----|---------|----------|-----------------|
| 1 | INF | footprint | v7 |
| 2 | INF | footprint | v6 |
| 3 | INF | footprint | v8 |
| 4 | NCD | footprint | v7 |
| 5 | INF | fewest | v7 |
| 6 | INF | distance | v7 |
| 7 | INF | governorate_fewest | v7 |

### Step 4a: Weekly Climate Aggregation

**Pre-computed for INF footprint v6** — skip this step if using v6 boundaries and the `DRIVE_CLIMATE_BY_HSA_DOWNLOAD/FINAL_HSA_CLIMATE/` folder is already populated.

For other versions:

```bash
jupyter notebook GEE_local_HSA_Weekly_Climate_Lagged.ipynb
# Set NETWORK = "INF", BOUNDARY_VERSION = "v7"  (or v8)
# After GEE export completes, copy CSV files to:
# out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD/FINAL_HSA_CLIMATE/
```

**Large-network or chunked export:**

```bash
jupyter notebook GEE_local_HSA_Weekly_Climate_Lagged_chunked.ipynb
```

### Step 4b: Daily Climate Aggregation

**Pre-computed for INF footprint v7** — skip if `out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/` already populated.

For other versions:

```bash
jupyter notebook GEE_local_HSA_Daily_Climate.ipynb
# Set BOUNDARY_VERSION = "v6"  (or v8 when ready)
# After GEE export, copy to: out/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/
```

### Steps 5–6: Daily Disease Counts and Modeling Dataset

```bash
# For each priority run that uses the daily pipeline:
python3 generate_daily_disease_counts.py \
  --boundary-version v7 \
  --patient-file data/SYNMODINF_patient_visits.csv   # omit for real data

python3 prepare_daily_modeling_dataset.py
```

For a different boundary version, pass `--boundary-version v6` etc. and ensure the corresponding allocation CSV exists.

### Step 6 (Weekly track): Generate Weekly Modeling Dataset

```bash
jupyter notebook Generate_Modeling_Dataset.ipynb
# Set NETWORK, HSA_MODE, BOUNDARY_VERSION at top
```

### Step 7: Run Models

**Daily (DLNM + predictive):**

```bash
jupyter notebook run_climate_models_daily.ipynb
# Set BOUNDARY_VERSION at top
```

**Weekly climate-health:**

```bash
jupyter notebook run_climate_health_modeling.ipynb
# Set BOUNDARY_VERSION at top
```

---

## Changing the Output Directory

All notebooks and scripts read the output directory from environment variables:

```bash
export HSA_OUT_DIR=/path/to/your/output

# Then run as usual:
jupyter notebook HSA_FINAL.ipynb
python3 generate_daily_disease_counts.py
```

This lets you keep outputs from different runs in separate directories without editing notebooks.

---

## Comparing Results Across Versions

After running Steps 1–7 for v6, v7, and v8:

```bash
jupyter notebook compare_delineations.ipynb
```

The notebook loads all three boundary files, computes anchor differences, IoU similarity, area changes, and (if coefficient files are present) DLNM estimate stability.

---

## Reproducing Paper Results

The paper uses:

- `NETWORK = "INF"`, `HSA_MODE = "footprint"`, `BOUNDARY_VERSION = "v7"` as the primary result
- `NETWORK = "NCD"`, `HSA_MODE = "footprint"`, `BOUNDARY_VERSION = "v7"` for cross-network comparison
- `BOUNDARY_VERSION = "v6"` as the manuscript-baseline comparison (Table S-X)

Weekly climate CSVs in the paper were generated with v6 boundaries. Daily climate CSVs were generated with v7 boundaries.

---

## Common Issues

**Missing packages (`rasterio`, `affine`, `adjustText`):** All three are required by the pipeline but are not always installed by a bare `pip install -r requirements.txt` on some platforms. Install explicitly:

```bash
pip install rasterio affine adjustText
```

When using `run_pipeline.py`, the pre-flight check catches all missing packages at startup and prints the exact `pip install` commands needed before any notebook runs.

**HSA optimizer produces different results on different runs:** The greedy anchor selection is sensitive to Python's hash randomization (`PYTHONHASHSEED`), which is re-randomized by default each time the interpreter starts. `run_pipeline.py` fixes this by setting `PYTHONHASHSEED=42` in every kernel's environment. When running notebooks manually, `PYTHONHASHSEED` is not set automatically, so results will vary between sessions unless you fix it yourself.

The simplest option is to add it to your shell profile so it applies to every Jupyter session:

```bash
echo 'export PYTHONHASHSEED=42' >> ~/.zshrc
source ~/.zshrc
```

If you prefer to set it per session rather than globally:

```bash
PYTHONHASHSEED=42 jupyter notebook
```

**GEE export stuck:** GEE exports are asynchronous. Check task status at https://code.earthengine.google.com/tasks. Large exports (daily, 2+ years, 19 HSAs) can take 60–120 minutes. If all tasks show COMPLETED but the polling loop keeps running, Drive likely renamed one file to `filename (1).csv` from a prior run — the notebooks detect this after 10 stall polls and fall back to a fuzzy name search automatically.

**`infra_quality` missing for new HSAs:** `data/hsa_metadata.csv` covers the v6 anchor set (17 HSAs). HSAs added in v7 (7 new anchors) have NaN `infra_quality`. Add JMP sanitation scores for those HSAs to use them in the DLNM effect-modifier analysis.

**Allocation table not found:** Run `Population_Allocation_Probabilistic_v2.ipynb` before `generate_daily_disease_counts.py`. The script looks for `out/INF_footprint_facility_hsa_assignments_{BOUNDARY_VERSION}.csv`.

**`generate_daily_disease_counts.py` reports `1 facility not in allocation table`:** `Swaqa Correctional Primary` is intentionally excluded (lacks an admissible HSA fallback). This is expected behavior.
