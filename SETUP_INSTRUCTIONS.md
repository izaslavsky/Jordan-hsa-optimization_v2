# Setup Instructions

This guide will help you set up your environment and run the HSA optimization and climate extraction workflows.

## Prerequisites

### Required Software
- **Python 3.8 or higher** ([Download](https://www.python.org/downloads/))
- **Git** ([Download](https://git-scm.com/downloads))
- **Jupyter Notebook** (installed via requirements.txt)

### Optional Software
- **QGIS** or **ArcGIS** - For viewing/editing GeoPackage boundary files ([QGIS Download](https://qgis.org/download/))
- **Google Earth Engine Account** - Required only for climate extraction notebooks ([Sign up](https://earthengine.google.com/signup/))

---

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/izaslavsky/jordan-hsa-optimization_v2.git
cd jordan-hsa-optimization_v2
```

### 2. Create Virtual Environment (Recommended)

**On Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**On macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Expected installation time**: 5-10 minutes depending on internet speed

### 4. Google Earth Engine Authentication (Required for Climate Notebooks)

Google Earth Engine (GEE) is required for all climate extraction notebooks.

You must complete this step **before running**:
- `GEE_local_Climate_Features_by_Facilities.ipynb`
- `GEE_local_HSA_Weekly_Climate_Lagged.ipynb`
- `GEE_local_HSA_Daily_Climate.ipynb`

#### Step 4.1 — Create a Google Earth Engine Account

If you do not already have one:
- Sign up at: https://earthengine.google.com/signup/
- Approval is usually fast (minutes to a few days)



#### Step 4.2 — Authenticate Earth Engine Locally

Run:

```
earthengine authenticate
```

This will:
1.	Open a browser window
2.	Ask you to sign in to Google
3.	Store Earth Engine credentials locally

Verify authentication:

```
python - <<EOF
import ee
ee.Initialize()
print("✓ Earth Engine authentication successful")
EOF
```

#### Step 4.3 — Project-based Initialization (Used in Notebooks)

Notebooks initialize Earth Engine using an explicit project ID:

```
ee.Initialize(project="ee-<your-project-id>")
```
If authentication fails, re-run:

```
earthengine authenticate
```

**Important Notes**

* Authentication is per machine (or per Colab runtime)
* Credentials expire occasionally; re-authenticate if errors appear
* GEE processing happens server-side; local CPU/RAM limits are not the bottleneck

### 5. Google Drive API Authentication (Required for Automated Downloads)

Climate extraction notebooks export large CSV files to **Google Drive**.
To automatically:
- detect when exports are complete
- list files every minute
- download results locally

the notebooks use the **Google Drive API**.

This requires OAuth credentials.



#### Step 5.1 — Create OAuth Credentials

1. Go to: https://console.cloud.google.com/
2. Select (or create) a project
3. Navigate to:
   **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth Client ID**
5. Application type: **Desktop app**
6. Download the JSON file

Rename it to:

```
client_secrets.json
```


#### Step 5.2 — Place Credentials File

Move the file to the **root of the repository**:

```
jordan-hsa-optimization/
├── client_secrets.json ← REQUIRED
├── .gitignore
├── notebooks/
└── ...
```
The notebooks load it with:

```
CLIENT_SECRETS_PATH = "client_secrets.json"
```

#### Step 5.3 — Add to .gitignore (CRITICAL)
Add the following line to `.gitignore:`
```
# Google OAuth credentials
client_secrets.json
```

⚠️ **Never commit this file.**

If you accidentally commit it:
1.	Revoke the credentials in Google Cloud Console
2.	Generate a new OAuth client
3.	Rewrite Git history if needed
 
#### Step 5.4 — First-Time Login Flow

The first time you run a notebook that accesses Drive:
* A browser window will open
* You will be asked to approve read-only Drive access
* Credentials are cached locally for future runs

Scopes used:
```
https://www.googleapis.com/auth/drive.readonly
```

### Colab Users (Alternative)
If running in **Google Colab**, you may skip OAuth entirely and instead mount Drive:
```
from google.colab import drive
drive.mount('/content/drive')
```
Local execution **requires OAuth**; Colab does not.

---
## Running the Notebooks

### Start Jupyter Notebook Server

```bash
jupyter notebook
```

This will open Jupyter in your web browser at `http://localhost:8888`

### Notebook Execution Order

**For HSA optimization only:**
1. Open `HSA_FINAL.ipynb`
2. Run all cells sequentially (Cell → Run All)
3. Produces v6, v7, and v8 boundary bundles in a single run

**For the weekly climate-health workflow:**
1. `GEE_local_Climate_Features_by_Facilities.ipynb` — extract climate by facility (required by HSA_FINAL)
2. `HSA_FINAL.ipynb` — delineate boundaries (all three variants: v6, v7, v8)
3. `Population_Allocation_Probabilistic_v2.ipynb` — assign population to HSAs; set `BOUNDARY_VERSION`
4. `GEE_local_HSA_Weekly_Climate_Lagged.ipynb` — aggregate weekly climate per HSA polygon
5. `Generate_Modeling_Dataset.ipynb` — build `{NETWORK}_{MODE}_modeling_dataset_{VERSION}.csv`
6. `run_climate_health_modeling.ipynb` — train and evaluate weekly models

**For the daily DLNM pipeline (runs in parallel with steps 4–6 above):**
1. `GEE_local_HSA_Daily_Climate.ipynb` — aggregate daily climate per HSA polygon
2. Run `generate_daily_disease_counts.py` then `prepare_daily_modeling_dataset.py`
3. `run_climate_models_daily.ipynb` — quasi-Poisson DLNM (Track A) and predictive OLS (Track B)

**Optional:**
- `compare_delineations.ipynb` — compare v6/v7/v8 boundaries and model coefficients

### Expected Runtime

- **HSA Optimization**: 5-15 minutes (depends on dataset size and optimization parameters)
- **Climate Extraction (GEE)**: 30 minutes to 2+ hours (depends on spatial extent, temporal range, and GEE server load)
---
## Data Files

All necessary data files are included in the `data/` directory:

### Population Raster Data
- `data/jor_ppp_2020_UNadj.tif` - WorldPop 2020 population density (UN-adjusted, ~10.2M total)
  - Resolution: 100m × 100m
  - Used in HSA optimization for coverage calculations
  - Source: WorldPop (www.worldpop.org)
- `data/jor_ppp_2020_constrained.tif` - WorldPop 2020 population density (constrained to settlement patterns, ~7M total)
  - Resolution: 100m × 100m
  - Alternative population dataset, used as a background population density layer for mapping
  - Source: WorldPop (www.worldpop.org)

### Administrative Boundaries
- `data/adm_boundaries/*.gpkg` - Governorate, district, and subdistrict boundaries
- `data/jordan_boundary.gpkg` - National boundary
- `data/jordan_governorates.gpkg` - Governorate boundaries (used in GOVERNORATE modes)

**Viewing boundaries**: Open `.gpkg` files in QGIS or use GeoPandas:
```python
import geopandas as gpd
districts = gpd.read_file('data/adm_boundaries/dis_simpl_20m.gpkg')
districts.plot()
```

### Synthetic Patient Data and Facility Coordinates

Files use the `SYNMOD` prefix, followed by `INF` (infectious diseases) or `NCD` (non-communicable diseases):

- `data/SYNMODINF_facility_coordinates.csv` — INF facility locations (lat/lon)
- `data/SYNMODNCD_facility_coordinates.csv` — NCD facility locations (lat/lon)
- `data/SYNMODINF_patient_visits.csv` — synthetic INF patient visits (2019–2024)
- `data/SYNMODNCD_patient_visits.csv` — synthetic NCD patient visits
- `data/SYNMODINF_groups_of_diagnoses.csv` — ICD code groupings for INF network
- `data/SYNMODNCD_groups_of_diagnoses.csv` — ICD code groupings for NCD network

Real patient data files (`INF_patient_visits.csv`, `NCD_patient_visits.csv`) are blocked by `.gitignore` and never committed to this repository.

**Privacy Note**: SYNMOD files preserve temporal structure, seasonal patterns, and diagnosis distributions but contain no real patient records.

---

## Troubleshooting

### Common Issues

**Issue 1: "ModuleNotFoundError: No module named 'geopandas'"**

**Solution**: Install geopandas and its dependencies:
```bash
pip install geopandas
```

If this fails, install GDAL first (Windows users may need pre-built wheels from https://www.lfd.uci.edu/~gohlke/pythonlibs/)

---

**Issue 2: "earthengine.ee_exception.EEException: Please authorize access to your Earth Engine account"**

**Solution**: Run Earth Engine authentication:
```bash
earthengine authenticate
```

---

**Issue 3: Google Earth Engine tasks timeout or fail**

**Solution**:
- Check your GEE asset quota (may be full)
- Reduce spatial or temporal extent in notebook parameters
- Split large exports into smaller batches
- Check Earth Engine status page: https://status.earthengine.google.com/

---

**Issue 4: Notebook kernel dies during optimization**

**Solution**:
- Increase available RAM (close other applications)
- Reduce dataset size in notebook parameters
- Use a subset of patient data for testing

---

**Issue 5: Cannot open GeoPackage files**

**Solution**:
- Install GDAL: `pip install GDAL` (or use QGIS which includes GDAL)
- Check file path is correct (use absolute paths if relative paths fail)
- Verify file integrity: `gpd.read_file('file.gpkg')` should not raise errors

---

**Issue 6: Drive polling shows files but Drive UI is empty**

**Explanation**:
- Google Drive API can list files before the web UI refreshes
- Export placeholders may exist before finalization
- Always trust API visibility over the UI during active exports

**Resolution**:
- Wait until Earth Engine tasks are COMPLETED
- Refresh Drive UI or recheck after several minutes

---

**Issue 7: Polling loop stalls after all GEE tasks complete but one file never appears**

**Explanation**: Google Drive occasionally renames a file to `filename (1).csv` when a previous run left a file with the same name. The exact filename match fails even though the export succeeded.

**Resolution**: The weekly and daily GEE notebooks detect this automatically. After 10 polling intervals with all tasks COMPLETED but files still missing, the loop searches Drive for fuzzy-matched names (same stem, same extension) and downloads under the canonical filename. No manual action is required. If the loop raises `RuntimeError: stall after N polls`, check your Drive folder for `(1)` duplicates and delete the older copy.

---
## Verifying Installation

Run this Python script to verify your environment:

```python
import sys
print(f"Python version: {sys.version}")

# Check core packages
import numpy
import pandas
import geopandas
import matplotlib
import earthengine

print(f"NumPy: {numpy.__version__}")
print(f"Pandas: {pandas.__version__}")
print(f"GeoPandas: {geopandas.__version__}")
print(f"Matplotlib: {matplotlib.__version__}")
print(f"Earth Engine: {earthengine.__version__}")

# Test data loading
districts = geopandas.read_file('data/adm_boundaries/dis_simpl_20m.gpkg')
print(f"\nSuccessfully loaded {len(districts)} districts")

print("\n✅ Environment setup complete!")
```

Expected output should show no errors and display package versions.

---

## Performance Notes

### Memory Requirements
- **HSA Optimization**: 4-8 GB RAM recommended
- **Climate Extraction**: 8-16 GB RAM recommended (GEE handles heavy processing server-side)

### Disk Space
- **Repository**: ~50 MB
- **Generated outputs**: 100 MB - 5 GB (depends on number of climate variables and spatial resolution)

### CPU Usage
- HSA optimization is CPU-intensive (benefits from multi-core processors)
- Climate extraction relies on Google Earth Engine servers (local CPU not critical)

## Next Steps

After successful setup:
1. Read through `HSA_FINAL.ipynb` to understand the three-variant optimization workflow
2. Set `BOUNDARY_VERSION = "v7"` in downstream notebooks for the primary modeling track
3. Run climate extraction notebooks if you have access to Google Earth Engine
4. See `PIPELINE_GUIDE.md` for step-by-step instructions across all network/mode/version combinations

## Getting Help

If you encounter issues not covered here:
- **Check documentation**: Read notebook markdown cells for parameter descriptions
- **GitHub Issues**: [Open an issue](https://github.com/izaslavsky/HSA_algo_public/issues)
- **Email**: [Contact information]

---

**Last Updated**: June 2026
