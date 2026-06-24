#!/usr/bin/env python3
"""
Generate daily diarrheal case counts per HSA.

Input:
  data/INF_patient_visits.csv
  {OUT_DIR}/INF_footprint_facility_hsa_assignments_{BOUNDARY_VERSION}.csv

Output:
  {OUT_DIR}/INF_footprint_daily_diarrheal_{BOUNDARY_VERSION}.csv
  Columns: hsa_id, date, diarrheal_count  (float, gravity-weighted)
"""

import re
import sys
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR        = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", "out")))
_real_visits = BASE_DIR / "data" / "INF_patient_visits.csv"
PATIENT_FILE    = _real_visits if _real_visits.exists() else BASE_DIR / "data" / "SYNMODINF_patient_visits.csv"
OUT_DIR         = BASE_DIR / DEFAULT_OUT_DIR
_DEFAULT_BV     = os.environ.get("BOUNDARY_VERSION", os.environ.get("PIPELINE_VERSION", "v7"))
ALLOC_FILE      = OUT_DIR / f"INF_footprint_facility_hsa_assignments_{_DEFAULT_BV}.csv"
OUT_FILE        = OUT_DIR / f"INF_footprint_daily_diarrheal_{_DEFAULT_BV}.csv"

# Codes changed mid-2022. Data has a system gap June 2-30, 2022 (zero visits
# across all diagnoses — confirmed in raw data). Effective start is 2022-07-01.
# We retain 2022-06-01 as the climate buffer start (handled in prepare script).
CODE_VALID_FROM = "2022-07-01"
STUDY_END       = "2024-01-31"

# Known reporting gaps: days with zero records across ALL diagnoses (not true zeros).
# These should be flagged rather than treated as disease-free days.
REPORTING_GAPS = [
    # June 2-30 2022: system-wide data gap at start of collection
    *[f"2022-06-{d:02d}" for d in range(2, 31)],
    # May 30-31 2023: two-day reporting gap (Tuesday-Wednesday)
    "2023-05-30",
    "2023-05-31",
]

# ---------------------------------------------------------------------------
def parse_hsa_weights(s: str) -> dict:
    """Parse 'HSA1:92.2%; HSA2:7.8%' → {'HSA1': 0.922, 'HSA2': 0.078}."""
    if not isinstance(s, str) or not s.strip():
        return {}
    out = {}
    for part in s.split(";"):
        part = part.strip()
        m = re.match(r"^(.+):([\d.]+)%", part)
        if m:
            out[m.group(1).strip()] = float(m.group(2)) / 100.0
    return out


def normalize_hsa_name(name: str) -> str:
    """'Al-Basheer Hospital' → 'Al-Basheer_Hospital'"""
    return name.replace(" ", "_")


def main():
    global OUT_DIR, ALLOC_FILE, OUT_FILE, PATIENT_FILE
    parser = argparse.ArgumentParser(description="Generate daily diarrheal case counts per HSA")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument(
        "--patient-file",
        default=None,
        help="Path to patient visits CSV. Defaults to data/INF_patient_visits.csv. "
             "Pass data/SYNMODINF_patient_visits.csv to run on synthetic data.",
    )
    parser.add_argument(
        "--boundary-version",
        default="v7",
        help="HSA boundary bundle version to use for facility-to-HSA assignments "
             "(v6, v7, or v8). Must match the BOUNDARY_VERSION used in "
             "Population_Allocation_Probabilistic_v2.ipynb. Default: v7.",
    )
    args = parser.parse_args()

    OUT_DIR = Path(args.out_dir)
    if not OUT_DIR.is_absolute():
        OUT_DIR = BASE_DIR / OUT_DIR
    ALLOC_FILE = OUT_DIR / f"INF_footprint_facility_hsa_assignments_{args.boundary_version}.csv"
    OUT_FILE = OUT_DIR / f"INF_footprint_daily_diarrheal_{args.boundary_version}.csv"
    if args.patient_file:
        PATIENT_FILE = Path(args.patient_file)
        if not PATIENT_FILE.is_absolute():
            PATIENT_FILE = BASE_DIR / PATIENT_FILE

    print("=" * 60)
    print("DAILY DIARRHEAL COUNTS — INF FOOTPRINT")
    print("=" * 60)

    # 1. Load allocations
    print("\n[1/4] Loading facility→HSA allocations...")
    alloc = pd.read_csv(ALLOC_FILE)
    alloc = alloc[~alloc["excluded"]].copy()

    facility_weights: dict[str, dict[str, float]] = {}
    for _, row in alloc.iterrows():
        fid = row["facility_id"]
        weights = parse_hsa_weights(str(row.get("all_containing_hsas", "")))
        if not weights:
            weights = {row["primary_hsa"]: 1.0}
        # Normalize HSA names (space → underscore)
        facility_weights[fid] = {normalize_hsa_name(h): w for h, w in weights.items()}

    print(f"  {len(facility_weights)} facilities mapped")

    # 2. Load patient visits
    print("\n[2/4] Loading and filtering patient visits...")
    pv = pd.read_csv(PATIENT_FILE, low_memory=False)
    pv["date"] = pd.to_datetime(pv["datetimediagnosisentered"], errors="coerce").dt.date
    pv = pv.dropna(subset=["date"])

    diarrhea = pv[
        (pv["general_category"] == "Diarrheal Diseases")
        & (pv["date"] >= pd.to_datetime(CODE_VALID_FROM).date())
        & (pv["date"] <= pd.to_datetime(STUDY_END).date())
    ].copy()

    print(f"  {len(diarrhea):,} diarrheal visits in study window")

    # 3. Expand each visit to weighted HSA-day records
    print("\n[3/4] Applying gravity-model weights...")
    records = []
    unmatched_facilities = set()
    for _, row in diarrhea.iterrows():
        fac = row["healthfacility"]
        weights = facility_weights.get(fac)
        if weights is None:
            unmatched_facilities.add(fac)
            continue
        for hsa, w in weights.items():
            records.append({"hsa_id": hsa, "date": str(row["date"]), "weight": w})

    if unmatched_facilities:
        print(f"  WARNING: {len(unmatched_facilities)} facilities not in allocation table")
        print(f"    Examples: {sorted(unmatched_facilities)[:5]}")

    weighted = pd.DataFrame(records)
    print(f"  {len(weighted):,} weighted visit-HSA records")

    # 4. Aggregate to HSA-day
    print("\n[4/4] Aggregating to HSA-day...")
    daily = (
        weighted.groupby(["hsa_id", "date"])["weight"]
        .sum()
        .reset_index()
        .rename(columns={"weight": "diarrheal_count"})
    )
    daily["date"] = pd.to_datetime(daily["date"]).dt.date

    # Build complete grid: all HSAs × all study days → fill 0 where no cases
    all_hsas = sorted(daily["hsa_id"].unique())
    all_dates = pd.date_range(CODE_VALID_FROM, STUDY_END).date
    grid = pd.MultiIndex.from_product([all_hsas, all_dates], names=["hsa_id", "date"])
    daily = (
        daily.set_index(["hsa_id", "date"])
        .reindex(grid, fill_value=0)
        .reset_index()
    )

    # Flag reporting gaps as NaN (not true disease-free days)
    gap_set = set(pd.to_datetime(REPORTING_GAPS).date)
    gap_mask = daily["date"].isin(gap_set)
    daily.loc[gap_mask, "diarrheal_count"] = np.nan
    daily["is_reporting_gap"] = gap_mask.astype(int)
    print(f"  Flagged {gap_mask.sum()} HSA-day rows as reporting gaps")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily.to_csv(OUT_FILE, index=False)
    print(f"  Saved: {OUT_FILE}")
    print(f"  Shape: {daily.shape}")
    print(f"  HSAs: {daily['hsa_id'].nunique()}")
    print(f"  Date range: {daily['date'].min()} to {daily['date'].max()}")
    print(f"  Total weighted cases: {daily['diarrheal_count'].sum():.0f}")
    print(f"  Non-zero days: {(daily['diarrheal_count'] > 0).sum():,}")

    # Per-HSA summary
    print("\n  Top HSAs by total cases:")
    top = daily.groupby("hsa_id")["diarrheal_count"].sum().nlargest(5)
    for hsa, n in top.items():
        print(f"    {hsa}: {n:.0f}")


if __name__ == "__main__":
    main()
