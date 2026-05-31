#!/usr/bin/env python3
"""Generate the three daily-analysis notebooks."""
import nbformat as nbf
from pathlib import Path

BASE = Path(__file__).resolve().parent
nb4 = nbf.v4

def md(text):
    return nb4.new_markdown_cell(text)

def code(text):
    return nb4.new_code_cell(text)

def notebook(cells):
    nb = nb4.new_notebook()
    nb.cells = cells
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3", "language": "python", "name": "python3"
    }
    return nb

# ============================================================================
# 1. GEE_local_HSA_Daily_Climate.ipynb
# ============================================================================

gee_cells = [
md("""\
# HSAs → Daily Climate (CHIRPS + ERA5)

Exports one row per HSA per calendar day for the study period.
Output: `{OUT_DIR}/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/INF_HSA_<NAME>_daily.csv`

Columns: `FacilityName, date, P_precip, T_mean_C, T_max_C, T_min_C,
Td_C, DTR_C, wind_speed_ms, SM1, SM2, hours_above_30C, heat_index_C`

**Run once** before `Generate_Daily_Modeling_Dataset.ipynb`.
"""),

code("""\
# STEP 0 — Earth Engine init + config
import ee, re, time, os
from datetime import date, timedelta

PROJECT = "ee-izaslavsky"
try:
    ee.Initialize(project=PROJECT)
except Exception:
    ee.Authenticate()
    ee.Initialize(project=PROJECT)

# ── Date range ───────────────────────────────────────────────────────────────
# Start 14 days before first valid outcome date so lag windows are complete.
DAY_START = "2022-06-01"   # 14-day buffer before 2022-06-15 model start
DAY_END   = "2024-01-31"

NETWORK   = "INF"
MODE      = "footprint"
PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v7")
DATA_DIR  = os.environ.get("HSA_DATA_DIR", "data")
OUT_DIR   = os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", f"out_{PIPELINE_VERSION}"))

TEST_MODE       = True    # set False for full run
TEST_HSA_COUNT  = 2
TEST_DAY_COUNT  = 5

COLL = {
    "CHIRPS":  "UCSB-CHG/CHIRPS/DAILY",
    "ERA5":    "ECMWF/ERA5_LAND/HOURLY",
}
SCALE = {"CHIRPS": 5550, "ERA5": 9000}

print(f"EE initialized  |  {DAY_START} → {DAY_END}")
print(f"TEST_MODE = {TEST_MODE}")
"""),

code("""\
# STEP 1 — Load HSA GeoJSON
import geopandas as gpd, geemap, os

GEOJSON_PATH = os.path.join(OUT_DIR, f"{NETWORK}_{MODE}_hsas_v2.geojson")
gdf = gpd.read_file(GEOJSON_PATH).to_crs(4326)
id_col = "FacilityName"
gdf = gdf[~gdf.geometry.is_empty][[id_col, "geometry"]].copy()

ee_fc_hsa = geemap.gdf_to_ee(gdf, geodesic=False)
ids = gdf[id_col].tolist()
print(f"Loaded {len(ids)} HSAs")
"""),

code("""\
# STEP 2 — Build daily date list
from datetime import date, timedelta

start = date.fromisoformat(DAY_START)
end   = date.fromisoformat(DAY_END)

all_days = []
d = start
while d <= end:
    all_days.append(d.isoformat())
    d += timedelta(days=1)

print(f"{len(all_days)} days: {all_days[0]} → {all_days[-1]}")
"""),

code("""\
# STEP 3 — Geometry helpers (reused from weekly notebook)
SIMPLIFY_M   = 10
CLEAN_BUF_M  = 1
MAX_ERROR_M  = 10
FALLBACK_M   = 250

def _with_retry(fn, label, retries=4, backoff=5):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (2 ** attempt))

def _force_planar(g):
    t = ee.String(g.type())
    c = g.coordinates()
    return ee.Geometry(ee.Algorithms.If(
        t.equals("Polygon"),
        ee.Geometry.Polygon(c, None, False),
        ee.Algorithms.If(
            t.equals("MultiPolygon"),
            ee.Geometry.MultiPolygon(c, None, False),
            g,
        ),
    ))

def robust_ee_geom(hid):
    feat = ee_fc_hsa.filter(ee.Filter.eq(id_col, hid)).first()
    g = _force_planar(ee.Feature(feat).geometry())
    g = g.buffer(0, MAX_ERROR_M).simplify(SIMPLIFY_M)
    if CLEAN_BUF_M:
        g = g.buffer(CLEAN_BUF_M, MAX_ERROR_M).buffer(-CLEAN_BUF_M, MAX_ERROR_M)
    area_ok = ee.Number(g.area(MAX_ERROR_M)).gt(0)
    fallback = g.centroid(MAX_ERROR_M).buffer(FALLBACK_M).bounds()
    g2 = ee.Geometry(ee.Algorithms.If(area_ok, g, fallback))
    _with_retry(lambda: g2.type().getInfo(), "geom")
    return g2

print("Geometry helpers ready")
"""),

code("""\
# STEP 4 — Daily climate extraction function

def make_daily_fc(hsa_id, geom, days_list):
    \"\"\"
    Returns ee.FeatureCollection: one Feature per day with all climate vars.
    Uses ERA5 scale (9000m) for all bands — CHIRPS is spatially averaged at
    that scale, which is fine for HSA-level analysis.
    \"\"\"
    days_ee = ee.List(days_list)

    def process_day(date_str):
        d0 = ee.Date(date_str)
        d1 = d0.advance(1, "day")

        # CHIRPS precipitation (daily total)
        chirps = (ee.ImageCollection(COLL["CHIRPS"])
                  .filterDate(d0, d1)
                  .select("precipitation")
                  .map(lambda im: im.unmask(0))
                  .mean()
                  .rename("P_precip"))

        # ERA5 hourly → daily aggregates
        era5 = ee.ImageCollection(COLL["ERA5"]).filterDate(d0, d1)
        t    = era5.select("temperature_2m")
        td   = era5.select("dewpoint_temperature_2m")
        u    = era5.select("u_component_of_wind_10m")
        v    = era5.select("v_component_of_wind_10m")
        sm1  = era5.select("volumetric_soil_water_layer_1")
        sm2  = era5.select("volumetric_soil_water_layer_2")

        t_mean = t.mean().subtract(273.15).rename("T_mean_C")
        t_max  = t.max() .subtract(273.15).rename("T_max_C")
        t_min  = t.min() .subtract(273.15).rename("T_min_C")
        td_c   = td.mean().subtract(273.15).rename("Td_C")
        # DTR: max-min in Kelvin = max-min in Celsius
        dtr    = t.max().subtract(t.min()).rename("DTR_C")
        wspd   = u.mean().hypot(v.mean()).rename("wind_speed_ms")
        sm1_m  = sm1.mean().rename("SM1")
        sm2_m  = sm2.mean().rename("SM2")
        # Hours above 30°C (subtract 273.15 from each hourly image, then threshold)
        t_c    = t.map(lambda img: img.subtract(273.15))
        h30    = t_c.map(lambda img: img.gt(30)).sum().rename("hours_above_30C")
        # Simplified heat index: T + 0.4*(Td - T)  [all in Celsius]
        hi     = t_mean.add(td_c.subtract(t_mean).multiply(0.4)).rename("heat_index_C")

        img = (chirps
               .addBands(t_mean).addBands(t_max).addBands(t_min)
               .addBands(td_c).addBands(dtr).addBands(wspd)
               .addBands(sm1_m).addBands(sm2_m)
               .addBands(h30).addBands(hi))

        r = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=SCALE["ERA5"],
            maxPixels=1e9,
            bestEffort=True,
            tileScale=4,
        )

        return ee.Feature(None, {
            "FacilityName":   hsa_id,
            "date":           date_str,
            "P_precip":       r.get("P_precip"),
            "T_mean_C":       r.get("T_mean_C"),
            "T_max_C":        r.get("T_max_C"),
            "T_min_C":        r.get("T_min_C"),
            "Td_C":           r.get("Td_C"),
            "DTR_C":          r.get("DTR_C"),
            "wind_speed_ms":  r.get("wind_speed_ms"),
            "SM1":            r.get("SM1"),
            "SM2":            r.get("SM2"),
            "hours_above_30C": r.get("hours_above_30C"),
            "heat_index_C":   r.get("heat_index_C"),
        })

    return ee.FeatureCollection(days_ee.map(process_day))

print("Daily climate function ready")
"""),

code("""\
# STEP 5 — Export loop (one task per HSA)
import os

DRIVE_FOLDER = "INF_DAILY_CLIMATE"

def _safe_name(s, maxlen=100):
    return re.sub(r"[^a-zA-Z0-9_\\-]", "_", str(s))[:maxlen]

ids_use  = ids[:TEST_HSA_COUNT] if TEST_MODE else ids
days_use = all_days[:TEST_DAY_COUNT] if TEST_MODE else all_days

print(f"Exporting {len(ids_use)} HSAs × {len(days_use)} days → Drive/{DRIVE_FOLDER}")
print()

all_tasks = []
all_expected = []

for hsa_id in ids_use:
    time.sleep(3)
    try:
        geom = robust_ee_geom(hsa_id)
        fc   = make_daily_fc(hsa_id, geom, days_use)

        safe  = _safe_name(hsa_id)
        desc  = f"{NETWORK}_daily_{safe}"
        fname = f"{NETWORK}_HSA_{safe}_daily"

        task = ee.batch.Export.table.toDrive(
            collection=fc,
            description=desc[:100],
            folder=DRIVE_FOLDER,
            fileNamePrefix=fname,
            fileFormat="CSV",
            selectors=["FacilityName", "date",
                       "P_precip", "T_mean_C", "T_max_C", "T_min_C",
                       "Td_C", "DTR_C", "wind_speed_ms", "SM1", "SM2",
                       "hours_above_30C", "heat_index_C"],
        )
        task.start()
        all_tasks.append(task)
        all_expected.append(fname + ".csv")
        print(f"  ✓ Started: {fname}.csv")
    except Exception as e:
        print(f"  ✗ FAILED {hsa_id}: {e}")

print(f"\\n{len(all_tasks)} tasks submitted")
"""),

code("""\
# STEP 6 — Wait for exports, then download
import os, time
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

LOCAL_DIR = os.path.join(OUT_DIR, "DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY")
os.makedirs(LOCAL_DIR, exist_ok=True)

CLIENT_SECRETS = "client_secrets.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
creds = flow.run_local_server(port=0)
drive_svc = build("drive", "v3", credentials=creds)

def get_folder_id(svc, name):
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    res = svc.files().list(q=q, fields="files(id,name)").execute()
    return res["files"][0]["id"]

def list_folder(svc, folder_id):
    items, token = [], None
    while True:
        res = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            pageToken=token,
            fields="nextPageToken,files(id,name)",
            pageSize=1000,
        ).execute()
        items.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return {f["name"]: f["id"] for f in items}

folder_id = get_folder_id(drive_svc, DRIVE_FOLDER)
expected  = set(all_expected)

# Poll until all tasks complete and files appear on Drive
while True:
    states = [t.status().get("state") for t in all_tasks]
    done   = sum(s == "COMPLETED" for s in states)
    failed = [s for s in states if s in {"FAILED", "CANCELLED"}]
    drive_files = list_folder(drive_svc, folder_id)
    have = len(set(drive_files) & expected)
    print(f"Tasks {done}/{len(all_tasks)} complete | Drive files {have}/{len(expected)}")
    if failed:
        raise RuntimeError(f"Export(s) failed/cancelled: {failed}")
    if done == len(all_tasks) and have == len(expected):
        break
    time.sleep(60)

# Download
print("\\nDownloading...")
for fname in sorted(expected):
    fid = drive_files[fname]
    path = os.path.join(LOCAL_DIR, fname)
    with open(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, drive_svc.files().get_media(fileId=fid))
        done = False
        while not done:
            _, done = dl.next_chunk()
    print(f"  ✓ {fname}")

print(f"\\nAll files downloaded to: {os.path.abspath(LOCAL_DIR)}")
"""),
]

nb_gee = notebook(gee_cells)
nbf.write(nb_gee, str(BASE / "GEE_local_HSA_Daily_Climate.ipynb"))
print("Written: GEE_local_HSA_Daily_Climate.ipynb")


# ============================================================================
# 2. Generate_Daily_Modeling_Dataset.ipynb
# ============================================================================

gen_cells = [
md("""\
# Generate Daily Modeling Dataset

**Prerequisites**
1. `GEE_local_HSA_Daily_Climate.ipynb` completed and files downloaded to
   `{OUT_DIR}/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY/`
2. `data/INF_patient_visits.csv` present

**Outputs**
- `{OUT_DIR}/INF_footprint_daily_diarrheal.csv` — daily case counts per HSA
- `{OUT_DIR}/modeling/INF_footprint_daily_modeling_dataset.csv` — merged panel
"""),

code("""\
# Config
from pathlib import Path
import os
import subprocess, sys

BASE_DIR = Path(".")
PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v7")
OUT_DIR = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", f"out_{PIPELINE_VERSION}")))
MODELING_DIR = OUT_DIR / "modeling"
MODELING_DIR.mkdir(parents=True, exist_ok=True)
print("Working directory:", BASE_DIR.resolve())
print("Output directory:", OUT_DIR)
"""),

code("""\
# STEP 1 — Daily disease counts
print("=" * 60)
print("STEP 1: Daily diarrheal counts")
print("=" * 60)

result = subprocess.run(
    [sys.executable, "generate_daily_disease_counts.py", "--out-dir", str(OUT_DIR)],
    capture_output=False,
)
if result.returncode != 0:
    raise RuntimeError("generate_daily_disease_counts.py failed")
print("Done.")
"""),

code("""\
# STEP 2 — Assemble modeling dataset
print("=" * 60)
print("STEP 2: Assemble daily modeling dataset")
print("=" * 60)

result = subprocess.run(
    [sys.executable, "prepare_daily_modeling_dataset.py", "--out-dir", str(OUT_DIR)],
    capture_output=False,
)
if result.returncode != 0:
    raise RuntimeError("prepare_daily_modeling_dataset.py failed")
print("Done.")
"""),

code("""\
# STEP 3 — Verify output
import pandas as pd

df = pd.read_csv(MODELING_DIR / "INF_footprint_daily_modeling_dataset.csv",
                 parse_dates=["date"])
print(f"Shape:       {df.shape}")
print(f"HSAs:        {df['hsa_id'].nunique()}")
print(f"Date range:  {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Columns:     {list(df.columns[:12])} ...")
print()
print("Non-zero outcome days:", (df["diarrheal_count"] > 0).sum())
print("Zero-count fraction:  ", f"{(df['diarrheal_count']==0).mean()*100:.1f}%")
print()
print("Climate coverage (non-null P_precip):",
      f"{df['P_precip'].notna().sum():,} / {len(df):,}")
print()
print("Lag columns present (sample):")
lag_cols = [c for c in df.columns if "lag" in c][:8]
print(" ", lag_cols)
"""),
]

nb_gen = notebook(gen_cells)
nbf.write(nb_gen, str(BASE / "Generate_Daily_Modeling_Dataset.ipynb"))
print("Written: Generate_Daily_Modeling_Dataset.ipynb")


# ============================================================================
# 3. run_climate_models_daily.ipynb
# ============================================================================

model_cells = [
md("""\
# Daily Climate-Health Models: Explanatory and Predictive

Two tracks, sharing the same daily panel dataset.

**Track A — Explanatory (DLNM, no AR)**
Quasi-Poisson GLM with seasonal spline + DOW dummies + DLNM cross-basis.
Tests whether climate affects daily diarrheal cases, independent of AR structure.
Fits main effect and infrastructure-quality interaction.

**Track B — Predictive (multi-horizon)**
Evaluates climate's contribution at forecast horizons 1, 7, 14, 21, 28 days.
Compares AR+Seasonal+Climate vs AR+Seasonal vs Climate-only (no AR) vs Seasonal-only.
The climate-only row is the key early-warning system benchmark.

**Input:** `{OUT_ROOT}/modeling/INF_footprint_daily_modeling_dataset.csv`
"""),

code("""\
# Setup
import sys
from pathlib import Path
import os
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Add dlnm/ directory so we can import the cross-basis functions
DLNM_DIR = Path("..") / "jordan-hsa-dlnm" / "dlnm"
sys.path.insert(0, str(DLNM_DIR))
from dlnm_crossbasis import ns_basis, build_crossbasis, cumulative_rr

PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", "v7")
OUT_ROOT = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", f"out_{PIPELINE_VERSION}")))
DATA_FILE = OUT_ROOT / "modeling" / "INF_footprint_daily_modeling_dataset.csv"
OUT_DIR   = OUT_ROOT / "modeling" / "daily_models"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("Libraries loaded")
print(f"Output: {OUT_DIR.resolve()}")
"""),

code("""\
# Load data
df = pd.read_csv(DATA_FILE, parse_dates=["date"])
df = df.sort_values(["hsa_id", "date"]).reset_index(drop=True)
print(f"Loaded: {df.shape}  HSAs={df['hsa_id'].nunique()}  "
      f"dates={df['date'].dt.date.min()} to {df['date'].dt.date.max()}")

# HSAs with mean > 1 case/day (avoid sparse fitting)
hsa_means = df.groupby("hsa_id")["diarrheal_count"].mean()
low_count_hsas = hsa_means[hsa_means < 1.0].index.tolist()
if low_count_hsas:
    print(f"Excluding {len(low_count_hsas)} low-count HSAs: {low_count_hsas}")

df_full = df[~df["hsa_id"].isin(low_count_hsas)].copy().reset_index(drop=True)
print(f"Analysis dataset: {df_full.shape}  HSAs={df_full['hsa_id'].nunique()}")
"""),

code("""\
# ─── Base predictors (shared across both tracks) ─────────────────────────────

outcome    = df_full["diarrheal_count"].values.astype(float)
infra      = df_full["infra_quality"].fillna(df_full["infra_quality"].mean()).values
infra_c    = infra - infra.mean()

# HSA fixed effects
hsa_dummies = pd.get_dummies(df_full["hsa_id"], drop_first=True, dtype=float)

# Seasonal spline: ~5 knots per year of study
n_days = int(df_full["day_of_study"].max()) + 1
n_int  = max(5, n_days // 90)          # roughly one interior knot per quarter
spline_t, spline_knots = ns_basis(df_full["day_of_study"].values, n_interior_knots=n_int)

# DOW dummies (reference = Monday/0)
dow_dummies = pd.get_dummies(df_full["day_of_week"],
                             prefix="dow", drop_first=True, dtype=float)


# Calendar indicators (validated against raw attendance data):
#   is_friday    — Friday 54% of uniform attendance; captured by DOW dummy but
#                  included as explicit column for easy interpretation
#   is_ramadan   — 27% reduction in daily visits during Ramadan
#   is_eid_fitr  — multi-day drop after Ramadan (Eid al-Fitr)
#   is_eid_adha  — sharp 1-2 day drop for Eid al-Adha
# Note: Saturday is NOT a low-attendance day in Jordan (100% of uniform).
#       Other secular holidays show inconsistent signals and are excluded.
for col in ["is_ramadan", "is_eid_fitr", "is_eid_adha"]:
    if col not in df_full.columns:
        df_full[col] = 0
        print(f"  WARNING: {col} not found, set to 0")

calendar_X = np.c_[
    df_full["is_ramadan"].values.astype(float),
    df_full["is_eid_fitr"].values.astype(float),
    df_full["is_eid_adha"].values.astype(float),
]

base_X = np.c_[
    hsa_dummies.values,
    spline_t,
    dow_dummies.values,   # includes Friday dummy (day_of_week==4)
    calendar_X,
]
print(f"Base design matrix: {base_X.shape}")
print(f"  HSA FE:     {hsa_dummies.shape[1]}")
print(f"  Spline:     {spline_t.shape[1]} (df={n_int+1})")
print(f"  DOW:        {dow_dummies.shape[1]} (Fri= {int((df_full['day_of_week']==4).sum())} days)")
print(f"  Ramadan:    {int(df_full['is_ramadan'].sum())} HSA-days")
print(f"  Eid Fitr:   {int(df_full['is_eid_fitr'].sum())} HSA-days")
print(f"  Eid Adha:   {int(df_full['is_eid_adha'].sum())} HSA-days")
"""),

md("## Track A — Explanatory DLNM"),

code("""\
# ─── Track A: precipitation cross-basis ──────────────────────────────────────
# Lag 0 = same-day precip; lag 1-14 = prior days
lag_vals = np.arange(0, 15, dtype=float)   # 0..14

PRECIP_VARS = ["P_precip"] + [f"P_precip_lag{k}" for k in range(1, 15)]
Q_precip = df_full[PRECIP_VARS].values  # shape (n_obs, 15)

# Knot strategy: 80th pct of non-zero values
all_p = Q_precip.flatten()
nonzero_p = all_p[all_p > 0]
zero_frac  = (all_p == 0).mean()
int_knot_p = np.percentile(nonzero_p, 80) if zero_frac > 0.3 else np.percentile(all_p, 50)
exp_all_knots_p = np.array([all_p.min(), int_knot_p, all_p.max()])

lag_int_knots = np.array([3.0, 7.0])
lag_all_knots = np.array([lag_vals[0], lag_int_knots[0], lag_int_knots[1], lag_vals[-1]])

CB_precip, _, cb_meta = build_crossbasis(
    Q_precip,
    exp_n_int=1,
    lag_n_int=2,
    exp_all_knots=exp_all_knots_p,
    lag_all_knots=lag_all_knots,
    lag_values=lag_vals,
)
print(f"Precipitation cross-basis: {CB_precip.shape}")
print(f"  Zero fraction: {zero_frac:.1%}")
print(f"  Interior knot: {int_knot_p:.2f} mm")
print(f"  Lag knots: {lag_all_knots}")
"""),

code("""\
# ─── Fit quasi-Poisson models ─────────────────────────────────────────────────

def fit_qp(X, y):
    m = sm.GLM(y, sm.add_constant(X.astype(float), has_constant="add"),
               family=sm.families.Poisson())
    return m.fit(scale="X2")

def ftest(res_r, res_f):
    dD  = res_r.deviance - res_f.deviance
    ddf = int(round(res_r.df_resid - res_f.df_resid))
    if ddf <= 0:
        return np.nan, np.nan
    F = (dD / ddf) / res_f.scale
    p = 1 - stats.f.cdf(F, ddf, res_f.df_resid)
    return float(F), float(p)

CB_x_infra = CB_precip * infra_c[:, None]

print("Fitting base model...")
res_base  = fit_qp(pd.DataFrame(base_X), outcome)

print("Fitting main-effect model (base + CB_precip)...")
res_main  = fit_qp(np.c_[base_X, CB_precip], outcome)

print("Fitting interaction model (base + CB_precip + CB×infra)...")
res_inter = fit_qp(np.c_[base_X, CB_precip, CB_x_infra], outcome)

F_main, p_main = ftest(res_base,  res_main)
F_int,  p_int  = ftest(res_main,  res_inter)

print()
print("═" * 55)
print("Track A: Precipitation DLNM results")
print("═" * 55)
print(f"  φ (dispersion):              {res_inter.scale:.2f}")
print(f"  Main effect F-test:          F={F_main:.3f}  p={p_main:.4f}")
print(f"  Sanitation interaction:      F={F_int:.3f}   p={p_int:.4f}")
"""),

code("""\
# ─── Cumulative RR plot ───────────────────────────────────────────────────────
n_cb = CB_precip.shape[1]
n_base_const = base_X.shape[1] + 1   # +1 for constant added by fit_qp
coef_cb  = np.asarray(res_inter.params)[n_base_const : n_base_const + n_cb]
vcov_cb  = np.asarray(res_inter.cov_params())[
    n_base_const : n_base_const + n_cb,
    n_base_const : n_base_const + n_cb,
]

# Reference: median non-zero precip
ref_val = np.percentile(nonzero_p, 50)

# Evaluate at percentiles of observed precip
eval_pts = np.percentile(nonzero_p, np.arange(5, 96, 5))

cum_log_rr, cum_se = cumulative_rr(coef_cb, vcov_cb, cb_meta, eval_pts, reference_exp=ref_val)
cum_rr = np.exp(cum_log_rr)
cum_lo = np.exp(cum_log_rr - 1.96 * cum_se)
cum_hi = np.exp(cum_log_rr + 1.96 * cum_se)

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(eval_pts, cum_rr, color="steelblue", lw=2, label="Cum. RR")
ax.fill_between(eval_pts, cum_lo, cum_hi, alpha=0.2, color="steelblue")
ax.axhline(1.0, color="black", lw=0.8, ls="--")
ax.axvline(ref_val, color="gray", lw=0.8, ls="--", label=f"ref={ref_val:.1f}mm")
ax.set_xlabel("Daily precipitation (mm)")
ax.set_ylabel("Cumulative RR (lags 0–14)")
ax.set_title("Track A: Precipitation effect on daily diarrheal counts")
ax.legend()
plt.tight_layout()
plt.savefig(OUT_DIR / "trackA_precip_cumRR.png", dpi=150)
plt.close()
print("Saved: trackA_precip_cumRR.png")
"""),

code("""\
# ─── Track A: screen additional exposures ─────────────────────────────────────

OTHER_VARS = {
    "T_mean_C":      "Daily mean temperature (°C)",
    "T_max_C":       "Daily max temperature (°C)",
    "Td_C":          "Dewpoint temperature (°C)",
    "SM1":           "Surface soil moisture (m³/m³)",
    "wind_speed_ms": "Wind speed (m/s)",
}

print(f"{'Variable':<16} {'F_main':>7} {'p_main':>8} {'F_int':>7} {'p_int':>8}  Sig")
print("-" * 60)

screen_results = []

for varname, desc in OTHER_VARS.items():
    lag_cols = [varname] + [f"{varname}_lag{k}" for k in range(1, 15)]
    if any(c not in df_full.columns for c in lag_cols):
        print(f"  {varname:<14} SKIP (columns missing)")
        continue

    Q = df_full[lag_cols].values
    all_v = Q.flatten()
    zero_f = (all_v == 0).mean()
    nonzero_v = all_v[all_v > 0]
    if len(nonzero_v) == 0:
        continue
    ik = np.percentile(nonzero_v, 80) if zero_f > 0.3 else np.percentile(all_v, 50)
    ik = np.clip(ik, all_v.min() + 1e-6, all_v.max() - 1e-6)

    CB, _, meta_v = build_crossbasis(
        Q, exp_n_int=1, lag_n_int=2,
        exp_all_knots=np.array([all_v.min(), ik, all_v.max()]),
        lag_all_knots=lag_all_knots,
        lag_values=lag_vals,
    )
    CB_xi = CB * infra_c[:, None]

    res_m = fit_qp(np.c_[base_X, CB],       outcome)
    res_i = fit_qp(np.c_[base_X, CB, CB_xi], outcome)

    Fm, pm = ftest(res_base, res_m)
    Fi, pi = ftest(res_m,    res_i)

    sig = "***" if pi < 0.001 else ("**" if pi < 0.01 else ("*" if pi < 0.05 else ""))
    print(f"  {varname:<14} {Fm:>7.3f} {pm:>8.4f} {Fi:>7.3f} {pi:>8.4f}  {sig}")
    screen_results.append(dict(variable=varname, description=desc,
                               F_main=Fm, p_main=pm, F_int=Fi, p_int=pi))

import pandas as pd
screen_df = pd.DataFrame(screen_results).sort_values("p_int")
screen_df.to_csv(OUT_DIR / "trackA_screening.csv", index=False)
print("\\nSaved: trackA_screening.csv")
"""),

md("## Track B — Predictive (multi-horizon)"),

code("""\
# ─── Track B setup ────────────────────────────────────────────────────────────
# OLS on log(Y+0.5) for computational speed.
# For each horizon h, predict Y_{t+h} from features known at time t.
#
# Models:
#   Seasonal-only:          seasonal spline + DOW + HSA FE + Ramadan + Holiday
#   AR+Seasonal:            + AR(1-day lag) + AR(7-day lag)
#   Seasonal+Climate:       seasonal + climate cross-sum (no AR) — early-warning model
#   AR+Seasonal+Climate:    all three
#
# Climate features: sum over lags 0..14 per variable (parsimony).
# At horizon h, all lags 0..14 at time t are available (past data).

HORIZONS = [1, 7, 14, 21, 28]

# Climate feature matrix: sum of lags 0-14 for each variable (cross-sum approximation)
# This avoids refitting a full cross-basis for each horizon
CLIM_SUM_COLS = {}
for varname in ["P_precip", "T_mean_C", "Td_C", "SM1"]:
    lag_cols = [varname] + [f"{varname}_lag{k}" for k in range(1, 15)]
    if all(c in df_full.columns for c in lag_cols):
        col_sum = df_full[lag_cols].sum(axis=1)
        CLIM_SUM_COLS[varname] = col_sum

clim_matrix = np.column_stack(list(CLIM_SUM_COLS.values())) if CLIM_SUM_COLS else None
print(f"Climate summary features: {list(CLIM_SUM_COLS.keys())}")
print(f"Climate matrix shape: {clim_matrix.shape if clim_matrix is not None else 'None'}")
"""),

code("""\
# ─── Horizon evaluation loop ──────────────────────────────────────────────────

# Temporal split: train on first 80% of dates, test on final 20% across all HSAs
n_obs = len(df_full)
unique_dates = np.array(sorted(df_full["date"].unique()))
split_idx = int(len(unique_dates) * 0.80)
split_date = unique_dates[split_idx]
date_values = df_full["date"].values
print(f"Temporal split date: {pd.Timestamp(split_date).date()}  "
      f"({split_idx}/{len(unique_dates)} dates in training period)")

# Outcomes and AR features per HSA (shift must respect HSA boundaries)
Y_log = np.log(df_full["diarrheal_count"].values + 0.5)

def make_ar_features(h):
    ar1 = df_full.groupby("hsa_id")["diarrheal_count"].shift(1).fillna(0).values
    ar7 = df_full.groupby("hsa_id")["diarrheal_count"].shift(7).fillna(0).values
    return np.c_[np.log(ar1 + 0.5), np.log(ar7 + 0.5)]

def make_future_y(h):
    return df_full.groupby("hsa_id")["diarrheal_count"].shift(-h).values

def r2_oos(y_true, y_pred):
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if len(yt) == 0 or len(yt) != len(yp):
        return np.nan
    ss_res = np.sum((yt - yp)**2)
    ss_tot = np.sum((yt - yt.mean())**2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else np.nan

results_B = []

for h in HORIZONS:
    Y_future = make_future_y(h)
    Y_future_log = np.log(np.where(Y_future > 0, Y_future, 0) + 0.5)
    valid = ~np.isnan(Y_future)

    ar = make_ar_features(h)
    X_seas  = base_X
    X_ar    = np.c_[base_X, ar]
    X_sclim = np.c_[base_X, clim_matrix] if clim_matrix is not None else base_X
    X_full  = np.c_[base_X, ar, clim_matrix] if clim_matrix is not None else X_ar

    train_mask = valid & (date_values < split_date)
    test_mask  = valid & (date_values >= split_date)

    row = {"horizon_days": h}

    for label, X in [
        ("Seasonal-only",            X_seas),
        ("AR+Seasonal",              X_ar),
        ("Seasonal+Climate (no AR)", X_sclim),
        ("AR+Seasonal+Climate",      X_full),
    ]:
        Xc_tr = sm.add_constant(X[train_mask], has_constant="add")
        Xc_te = sm.add_constant(X[test_mask],  has_constant="add")

        try:
            fit = sm.OLS(Y_future_log[train_mask], Xc_tr).fit()
            pred = fit.predict(Xc_te)
            r2 = r2_oos(Y_future_log[test_mask], pred)
        except Exception as e:
            print(f"  WARNING: {label} h={h}d failed: {e}")
            r2 = np.nan

        row[label] = round(r2, 4)

    # Climate contribution over AR baseline
    ar_r2   = row.get("AR+Seasonal", np.nan)
    full_r2 = row.get("AR+Seasonal+Climate", np.nan)
    row["ΔR² (climate)"] = round(full_r2 - ar_r2, 4) if not np.isnan(ar_r2 + full_r2) else np.nan

    results_B.append(row)
    print(f"h={h:2d}d  AR+Seas={ar_r2:.3f}  +Clim={full_r2:.3f}  "
          f"Clim-only={row.get('Seasonal+Climate (no AR)',np.nan):.3f}  "
          f"ΔR²={row['ΔR² (climate)']:.4f}")

results_B_df = pd.DataFrame(results_B)
results_B_df.to_csv(OUT_DIR / "trackB_horizon_results.csv", index=False)
print("\\nSaved: trackB_horizon_results.csv")
"""),

code("""\
# ─── Track B: horizon plot ────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
hors = [r["horizon_days"] for r in results_B]

ax = axes[0]
for model in ["Seasonal-only", "AR+Seasonal", "Seasonal+Climate (no AR)", "AR+Seasonal+Climate"]:
    vals = [r.get(model, np.nan) for r in results_B]
    ax.plot(hors, vals, marker="o", label=model)
ax.set_xlabel("Forecast horizon (days)")
ax.set_ylabel("Out-of-sample R²")
ax.set_title("Track B: Model R² by forecast horizon")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

ax = axes[1]
delta = [r["ΔR² (climate)"] for r in results_B]
delta_plot = [0 if np.isnan(d) else d for d in delta]
colors = ["#9ca3af" if np.isnan(d) else ("#d62728" if d < 0 else "#2ca02c") for d in delta]
ax.bar(hors, delta_plot, color=colors, width=2)
ax.axhline(0, color="black", lw=0.8)
ax.set_xlabel("Forecast horizon (days)")
ax.set_ylabel("ΔR² from adding climate to AR+Seasonal")
ax.set_title("Track B: Incremental climate contribution by horizon")
ax.grid(True, alpha=0.3, axis="y")

plt.tight_layout()
plt.savefig(OUT_DIR / "trackB_horizon_R2.png", dpi=150)
plt.close()
print("Saved: trackB_horizon_R2.png")
"""),

code("""\
# ─── Summary table (both tracks) ─────────────────────────────────────────────
print("\\n" + "═" * 70)
print("SUMMARY")
print("═" * 70)

print("\\nTrack A — Explanatory (DLNM, no AR terms)")
print(f"  Precipitation main effect:  F={F_main:.3f}  p={p_main:.4f}")
print(f"  Sanitation interaction:     F={F_int:.3f}   p={p_int:.4f}")
print(f"  Dispersion φ:              {res_inter.scale:.2f}")

print("\\nTrack B — Predictive (multi-horizon OLS on log scale)")
print(results_B_df.to_string(index=False))

print("\\nKey finding:")
if p_int < 0.05:
    print("  Track A: Precipitation effect modified by sanitation infrastructure (p<0.05).")
    print("  Climate does affect diarrheal risk, but the magnitude depends on whether")
    print("  sanitation can buffer the exposure-to-contamination pathway.")
else:
    print("  Track A: No significant precipitation effect or sanitation interaction detected.")

valid_deltas = [r["ΔR² (climate)"] for r in results_B if not np.isnan(r["ΔR² (climate)"])]
if valid_deltas:
    max_delta = max(valid_deltas)
    best_h    = [r["horizon_days"] for r in results_B
                 if r["ΔR² (climate)"] == max_delta][0]
    if max_delta > 0:
        print(f"  Track B: Peak climate contribution at h={best_h}d (ΔR²={max_delta:.4f}).")
        print("  Climate adds predictive value where ΔR² is positive;")
        print("  AR terms usually dominate at short horizons.")
    else:
        print(f"  Track B: Climate did not improve holdout R² at any tested horizon; "
              f"least negative ΔR² was h={best_h}d (ΔR²={max_delta:.4f}).")
else:
    print("  Track B: No valid out-of-sample R² values were produced.")
"""),
]

nb_model = notebook(model_cells)
nbf.write(nb_model, str(BASE / "run_climate_models_daily.ipynb"))
print("Written: run_climate_models_daily.ipynb")

print("\nAll notebooks created.")
