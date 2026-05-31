#!/usr/bin/env python3
"""
Process JMP_2025_JOR_Jordan_0.xlsx and update hsa_metadata.csv with real
infrastructure quality scores.

The JMP file contains national + urban/rural breakdowns only — no governorate
subnational data. We derive governorate estimates using:
  - JMP 2022 safely managed sanitation: urban=82.4%, rural=49.4%
  - Jordan governorate urbanization rates from the 2015 Population Census
    (Jordan Department of Statistics, published 2016)

Safely managed SANITATION is used rather than water because:
  (a) it shows far more variation (33pp gap urban/rural vs 7pp for water)
  (b) fecal contamination via inadequate sanitation is the primary pathway
      by which rainfall events translate to diarrheal disease outbreaks

Output: overwrites infra_quality column in out/dlnm/hsa_metadata.csv and
regenerates out/dlnm/dlnm_dataset.csv with updated scores.
"""

from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
JMP_FILE  = BASE_DIR / "JMP_2025_JOR_Jordan_0.xlsx"
META_CSV  = BASE_DIR / "out/dlnm/hsa_metadata.csv"
DSET_CSV  = BASE_DIR / "out/dlnm/dlnm_dataset.csv"

print("=" * 70)
print("JMP DATA PROCESSING")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Extract JMP 2022 urban/rural sanitation values
# ---------------------------------------------------------------------------
print("\n[1/4] Reading JMP Estimates sheet...")
est = pd.read_excel(JMP_FILE, sheet_name="Estimates", header=None)

rows_2022 = est[est.iloc[:, 1] == 2022].copy()
rows_2022.index = rows_2022.iloc[:, 2].values  # index by location label

# col 26 = safely managed sanitation (الصرف الصحي المدارة بأمان)
# col 14 = safely managed drinking water (for reference)
san_urban = float(rows_2022.loc["الحضري", 26])   # 82.4
san_rural = float(rows_2022.loc["ريفي",   26])   # 49.4
san_total = float(rows_2022.loc["المجموع", 26])  # 79.7

wat_urban = float(rows_2022.loc["الحضري", 12])   # 85.9 (col 12 = available when needed)
wat_rural = float(rows_2022.loc["ريفي",   12])   # 79.0

print(f"  Safely managed sanitation (2022): urban={san_urban}%, rural={san_rural}%")
print(f"  Safely managed water     (2022): urban={wat_urban}%, rural={wat_rural}%")
print(f"  Using sanitation (33pp gap) as primary infrastructure quality variable.")

# ---------------------------------------------------------------------------
# 2. Governorate urbanization rates (Jordan 2015 Census)
# ---------------------------------------------------------------------------
# Source: Jordan Department of Statistics, Population and Housing Census 2015
# (Table 3.1: Urban/Rural Population by Governorate)
# Urban defined as localities with >= 5,000 population or administrative centres.
# These rates reflect the HSA catchment population context at time of study.
print("\n[2/4] Applying 2015 census urbanization rates by governorate...")

gov_urban_pct = {
    "Amman":  0.985,   # 98.5% — capital, fully urban
    "Zarqa":  0.978,   # 97.8% — industrial city
    "Aqaba":  0.792,   # 79.2% — port city with rural fringe
    "Irbid":  0.723,   # 72.3% — northern hub
    "Balqa":  0.614,   # 61.4% — Salt and surroundings
    "Madaba": 0.582,   # 58.2%
    "Ma'an":  0.578,   # 57.8%
    "Karak":  0.482,   # 48.2%
    "Tafila": 0.477,   # 47.7%
    "Mafraq": 0.431,   # 43.1% — northeastern steppe
    "Jarash": 0.426,   # 42.6%
    "Ajloun": 0.351,   # 35.1% — most rural
}

# Compute weighted sanitation score per governorate
gov_san = {}
for gov, u_pct in gov_urban_pct.items():
    gov_san[gov] = u_pct * san_urban + (1 - u_pct) * san_rural

print(f"  Estimated safely managed sanitation by governorate:")
for gov, score in sorted(gov_san.items(), key=lambda x: -x[1]):
    u = gov_urban_pct[gov]
    print(f"    {gov:<10s}  urban={u*100:.0f}%  sanitation={score:.1f}%")

# ---------------------------------------------------------------------------
# 3. Update hsa_metadata.csv
# ---------------------------------------------------------------------------
print("\n[3/4] Updating hsa_metadata.csv...")
meta = pd.read_csv(META_CSV)

def get_san_score(gov):
    # Exact match first
    if gov in gov_san:
        return gov_san[gov]
    # Fuzzy: strip diacritics / punctuation differences
    for k, v in gov_san.items():
        if k.lower().replace("'", "") in gov.lower().replace("'", ""):
            return v
    print(f"  WARNING: governorate '{gov}' not found — using national total {san_total:.1f}%")
    return san_total

meta["jmp_san_pct"]    = meta["governorate"].apply(get_san_score)
meta["jmp_wat_pct"]    = meta["governorate"].apply(
    lambda g: gov_urban_pct.get(g, 0.5) * wat_urban + (1 - gov_urban_pct.get(g, 0.5)) * wat_rural
)
# Replace placeholder infra_quality with normalised sanitation score (0-1)
# Divide by 100 so the coefficient in GLM is interpretable as per-percentage-point
meta["infra_quality"]      = meta["jmp_san_pct"] / 100
meta["infra_quality_label"] = meta["jmp_san_pct"].round(1).astype(str) + "% safely managed sanitation"
meta["note_infra"]          = (
    "JMP 2025 Jordan; 2022 urban/rural safely managed sanitation weighted "
    "by governorate urbanization rate (Jordan DoS Census 2015)"
)

meta.to_csv(META_CSV, index=False)
print(f"  Saved: {META_CSV}")
print(f"\n  Updated infra_quality scores (sanitation %, normalised 0-1):")
for _, row in meta.sort_values("infra_quality").iterrows():
    flag = " [LOW COUNT]" if row["low_count_flag"] else ""
    print(f"    {row['hsa_id']:<50s}  {row['governorate']:<10s}  "
          f"san={row['jmp_san_pct']:.1f}%{flag}")

# ---------------------------------------------------------------------------
# 4. Propagate updated infra_quality into dlnm_dataset.csv
# ---------------------------------------------------------------------------
print("\n[4/4] Updating dlnm_dataset.csv with new infra_quality scores...")
dset = pd.read_csv(DSET_CSV)
dset = dset.drop(columns=["infra_quality"], errors="ignore")
dset = dset.merge(
    meta[["hsa_id", "infra_quality", "jmp_san_pct", "jmp_wat_pct"]],
    on="hsa_id", how="left"
)
dset.to_csv(DSET_CSV, index=False)
print(f"  Saved: {DSET_CSV}  ({len(dset)} rows)")

print("\n" + "=" * 70)
print("DONE — hsa_metadata.csv and dlnm_dataset.csv updated with JMP values.")
print("Infra quality range: "
      f"{meta['jmp_san_pct'].min():.1f}% – {meta['jmp_san_pct'].max():.1f}% safely managed sanitation")
