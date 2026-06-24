#!/usr/bin/env python3
"""
Assemble the daily modeling dataset for climate-health analysis.

Inputs:
  {OUT_DIR}/INF_footprint_daily_diarrheal_{ver}.csv           (from generate_daily_disease_counts.py)
  {OUT_DIR}/DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY_{VER}/        (from GEE_local_HSA_Daily_Climate.ipynb)
  data/hsa_metadata.csv                                        (sanitation quality)

Outputs:
  {OUT_DIR}/modeling/INF_footprint_daily_modeling_dataset_{ver}.csv
  Columns:
    hsa_id, date, diarrheal_count
    P_precip, T_mean_C, T_max_C, T_min_C, Td_C, DTR_C,
    wind_speed_ms, SM1, SM2, hours_above_30C, heat_index_C   (contemporaneous)
    *_lag{k} for k in 1..14  (climate lags for cross-basis)
    day_of_study, day_of_week, month, is_ramadan, is_holiday
    infra_quality
"""

import sys
import os
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR         = Path(__file__).resolve().parent
DEFAULT_OUT_DIR  = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", "out")))
PIPELINE_OUT_DIR = BASE_DIR / DEFAULT_OUT_DIR
HEALTH_FILE      = PIPELINE_OUT_DIR / "INF_footprint_daily_diarrheal.csv"
CLIMATE_DIR      = PIPELINE_OUT_DIR / "DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY"
META_FILE        = BASE_DIR / "data" / "hsa_metadata.csv"
OUT_DIR          = PIPELINE_OUT_DIR / "modeling"
OUT_FILE         = OUT_DIR / "INF_footprint_daily_modeling_dataset.csv"

MAX_LAG       = 14   # days of climate lag for cross-basis

CLIMATE_VARS  = [
    "P_precip", "T_mean_C", "T_max_C", "T_min_C",
    "Td_C", "DTR_C", "wind_speed_ms", "SM1", "SM2",
    "hours_above_30C", "heat_index_C",
]

# ── Calendar features (validated against raw attendance data) ─────────────────
#
# Observed patterns (Jordan INF data, 2022-07-01 to 2024-01-31):
#   Friday:      54% of uniform daily total — only day with strong attendance drop
#   Saturday:   100% of uniform — normal healthcare day in Jordan
#   Ramadan:     27% reduction in daily visits vs non-Ramadan
#   Eid al-Fitr: multi-day drop immediately following Ramadan
#   Eid al-Adha: sharp 1-2 day drop, strong recovery after
#
# DOW dummies in the model handle Friday automatically.
# Ramadan, Eid Fitr, and Eid Adha are separate indicators because their
# health-seeking suppression mechanism differs from day-of-week patterns.
# Secular public holidays show inconsistent signals and are excluded.

# Ramadan: reduced health-seeking during fasting month
RAMADAN_PERIODS = [
    ("2022-04-02", "2022-05-01"),
    ("2023-03-22", "2023-04-20"),
    ("2024-03-10", "2024-04-08"),
]

# Eid al-Fitr: first 3 days after Ramadan end (confirmed drop then recovery)
EID_FITR_DAYS = [
    "2022-05-02", "2022-05-03", "2022-05-04",
    "2023-04-21", "2023-04-22", "2023-04-23",
]

# Eid al-Adha: 1-2 day drop observed in raw data (Jun 27-28, 2023)
EID_ADHA_DAYS = [
    "2022-07-09", "2022-07-10",
    "2023-06-27", "2023-06-28",
]


def _date_set(lst):
    return set(pd.Timestamp(d).date() for d in lst)


def build_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add calendar indicator columns to df (which must have a 'date' column
    of datetime type and a 'day_of_week' column of int type 0=Mon..6=Sun).

    Columns added:
      is_ramadan      — 1 during Ramadan (health-seeking suppression)
      is_eid_fitr     — 1 on Eid al-Fitr days (multi-day closure effect)
      is_eid_adha     — 1 on Eid al-Adha days (sharp short-term closure)
      is_friday       — 1 on Fridays (convenience alias; already in DOW dummy)
    """
    dates = df["date"]

    # Ramadan
    ram = pd.Series(0, index=df.index)
    for s, e in RAMADAN_PERIODS:
        ram[(dates >= pd.Timestamp(s)) & (dates <= pd.Timestamp(e))] = 1
    df["is_ramadan"] = ram

    # Eid al-Fitr
    eid_f_set = _date_set(EID_FITR_DAYS)
    df["is_eid_fitr"] = dates.dt.date.map(lambda d: int(d in eid_f_set))

    # Eid al-Adha
    eid_a_set = _date_set(EID_ADHA_DAYS)
    df["is_eid_adha"] = dates.dt.date.map(lambda d: int(d in eid_a_set))

    # Friday convenience indicator (day_of_week == 4)
    df["is_friday"] = (df["day_of_week"] == 4).astype(int)

    return df


def main():
    global HEALTH_FILE, CLIMATE_DIR, OUT_DIR, OUT_FILE
    parser = argparse.ArgumentParser(description="Assemble the daily modeling dataset")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument(
        "--boundary-version",
        default="v7",
        help="HSA boundary version (v6, v7, v8). Derives default health-file, "
             "climate-dir, and output filenames. Default: v7.",
    )
    parser.add_argument("--health-file", default=None)
    parser.add_argument("--climate-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    ver = args.boundary_version
    pipeline_out = Path(args.out_dir)
    if not pipeline_out.is_absolute():
        pipeline_out = BASE_DIR / pipeline_out
    HEALTH_FILE = Path(args.health_file) if args.health_file else pipeline_out / f"INF_footprint_daily_diarrheal_{ver}.csv"
    CLIMATE_DIR = Path(args.climate_dir) if args.climate_dir else pipeline_out / f"DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY_{ver.upper()}"
    OUT_DIR = Path(args.output_dir) if args.output_dir else pipeline_out / "modeling"
    OUT_FILE = OUT_DIR / f"INF_footprint_daily_modeling_dataset_{ver}.csv"

    print("=" * 60)
    print("DAILY MODELING DATASET PREPARATION")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load daily health data
    print("\n[1/6] Loading daily health data...")
    health = pd.read_csv(HEALTH_FILE, parse_dates=["date"])
    print(f"  {len(health):,} rows, {health['hsa_id'].nunique()} HSAs")

    # 2. Load daily climate CSVs (one per HSA from GEE export)
    print("\n[2/6] Loading daily climate data...")
    climate_files = sorted(CLIMATE_DIR.glob("INF_HSA_*_daily.csv"))
    if not climate_files:
        print(f"  ERROR: No climate CSVs found in {CLIMATE_DIR}")
        print("  Run GEE_local_HSA_Daily_Climate.ipynb first.")
        sys.exit(1)

    clim_frames = []
    for f in climate_files:
        df = pd.read_csv(f, parse_dates=["date"])
        # Normalize HSA name from FacilityName column
        if "FacilityName" in df.columns:
            df["hsa_id"] = (
                df["FacilityName"]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .str.replace(" ", "_")
            )
            df = df.drop(columns=["FacilityName"])
        clim_frames.append(df)

    climate = pd.concat(clim_frames, ignore_index=True)
    # Keep only needed columns
    keep = ["hsa_id", "date"] + [v for v in CLIMATE_VARS if v in climate.columns]
    climate = climate[keep].copy()
    print(f"  {len(climate):,} rows, vars: {[v for v in CLIMATE_VARS if v in climate.columns]}")

    # 3. Merge health + climate
    print("\n[3/6] Merging health and climate...")
    df = health.merge(climate, on=["hsa_id", "date"], how="left")
    n_missing_clim = df[CLIMATE_VARS[0]].isna().sum() if CLIMATE_VARS[0] in df.columns else 0
    print(f"  Merged: {len(df):,} rows, {n_missing_clim} rows missing climate")

    # 4. Sort and build lag matrix
    print(f"\n[4/6] Building lag matrix (lags 1–{MAX_LAG})...")
    df = df.sort_values(["hsa_id", "date"]).reset_index(drop=True)

    available_climate_vars = [var for var in CLIMATE_VARS if var in df.columns]
    grouped = df.groupby("hsa_id", sort=False)
    lag_blocks = []
    for lag in range(1, MAX_LAG + 1):
        shifted = grouped[available_climate_vars].shift(lag)
        shifted.columns = [f"{var}_lag{lag}" for var in available_climate_vars]
        lag_blocks.append(shifted)
    if lag_blocks:
        df = pd.concat([df, *lag_blocks], axis=1).copy()

    # Drop rows where any lag is missing (first MAX_LAG days per HSA)
    lag_cols = [f"{var}_lag{MAX_LAG}" for var in available_climate_vars]
    before = len(df)
    df = df.dropna(subset=lag_cols).reset_index(drop=True)
    print(f"  Dropped {before - len(df)} rows with insufficient lag history")
    print(f"  Remaining: {len(df):,} rows")

    # 5. Add temporal and calendar features
    print("\n[5/6] Adding temporal and calendar features...")

    # Drop known reporting gaps before building time index
    if "is_reporting_gap" in df.columns:
        gap_rows = df["is_reporting_gap"] == 1
        print(f"  Removing {gap_rows.sum()} reporting-gap rows from model dataset")
        df = df[~gap_rows].copy().reset_index(drop=True)

    # Also drop rows with NaN diarrheal_count (gap-flagged)
    before = len(df)
    df = df.dropna(subset=["diarrheal_count"]).reset_index(drop=True)
    if len(df) < before:
        print(f"  Dropped {before - len(df)} additional NaN-outcome rows")

    study_start = df["date"].min()
    df["day_of_study"] = (df["date"] - study_start).dt.days.astype(float)
    df["day_of_week"]  = df["date"].dt.dayofweek   # 0=Mon, 4=Fri, 6=Sun
    df["month"]        = df["date"].dt.month
    df["year"]         = df["date"].dt.year

    df = build_calendar_features(df)

    print(f"  is_ramadan days:  {df['is_ramadan'].sum()}")
    print(f"  is_eid_fitr days: {df['is_eid_fitr'].sum()}")
    print(f"  is_eid_adha days: {df['is_eid_adha'].sum()}")
    print(f"  is_friday days:   {df['is_friday'].sum()}")

    # 6. Merge sanitation quality
    print("\n[6/6] Merging sanitation quality...")
    if META_FILE.exists():
        meta = pd.read_csv(META_FILE)
        # hsa_metadata uses 'hsa_id' already normalized
        if "infra_quality" in meta.columns:
            df = df.merge(meta[["hsa_id", "infra_quality"]], on="hsa_id", how="left")
            n_miss = df["infra_quality"].isna().sum()
            print(f"  Merged infra_quality ({n_miss} missing)")
        else:
            print(f"  WARNING: 'infra_quality' not found in metadata")
            df["infra_quality"] = np.nan
    else:
        print(f"  WARNING: metadata file not found at {META_FILE}")
        df["infra_quality"] = np.nan

    # Save
    df.to_csv(OUT_FILE, index=False)
    print(f"\nSaved: {OUT_FILE}")
    print(f"Shape: {df.shape}")
    print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"HSAs: {df['hsa_id'].nunique()}")
    print(f"Non-zero days: {(df['diarrheal_count'] > 0).sum():,}")
    print(f"Zeros: {(df['diarrheal_count'] == 0).mean()*100:.1f}%")

    # Daily summary
    print("\nPer-HSA daily case mean (top 5):")
    top = df.groupby("hsa_id")["diarrheal_count"].mean().nlargest(5)
    for hsa, m in top.items():
        print(f"  {hsa}: {m:.1f}/day")


if __name__ == "__main__":
    main()
