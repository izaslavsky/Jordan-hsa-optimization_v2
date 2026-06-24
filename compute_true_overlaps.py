#!/usr/bin/env python3
"""
PROPER HSA OVERLAP ANALYSIS
Compute actual polygon-to-polygon intersections

Run this from: jordan-hsa-optimization INF_FOOTPRINT/
"""

import json
import os
from pathlib import Path
from shapely.geometry import shape
import pandas as pd

# Load the GeoJSON
BOUNDARY_VERSION = os.environ.get("BOUNDARY_VERSION", os.environ.get("PIPELINE_VERSION", "v7"))
OUT_DIR = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", "out")))
with open(OUT_DIR / f'INF_footprint_hsas_{BOUNDARY_VERSION}.geojson', 'r') as f:
    data = json.load(f)

print("="*100)
print("ACTUAL HSA POLYGON OVERLAP ANALYSIS")
print("="*100)
print()

# Extract polygons
hsas = []
for feature in data['features']:
    geom = shape(feature['geometry'])
    props = feature['properties']
    name = props.get('FacilityName', 'Unknown')
    
    area_km2 = geom.area * 111 * 111  # Rough lat/lon to km²
    
    hsas.append({
        'name': name,
        'geometry': geom,
        'area_km2': area_km2,
        'stored_overlap_frac': props.get('overlap_frac', 0)
    })

print(f"Loaded {len(hsas)} HSAs\n")

# Compute pairwise overlaps
overlaps = []
for i, hsa1 in enumerate(hsas):
    for j, hsa2 in enumerate(hsas):
        if i < j:
            intersection = hsa1['geometry'].intersection(hsa2['geometry'])
            
            if not intersection.is_empty and intersection.area > 1e-10:
                overlap_km2 = intersection.area * 111 * 111
                pct_hsa1 = (intersection.area / hsa1['geometry'].area) * 100
                pct_hsa2 = (intersection.area / hsa2['geometry'].area) * 100
                
                overlaps.append({
                    'hsa1': hsa1['name'],
                    'hsa2': hsa2['name'],
                    'overlap_km2': overlap_km2,
                    'pct_of_hsa1': pct_hsa1,
                    'pct_of_hsa2': pct_hsa2
                })

# Sort by overlap area
overlaps_sorted = sorted(overlaps, key=lambda x: x['overlap_km2'], reverse=True)

print("="*100)
print("TOP 20 LARGEST OVERLAPS")
print("="*100)
print(f"\n{'HSA 1':<40} {'HSA 2':<40} {'Overlap km²':>12} {'% HSA1':>10} {'% HSA2':>10}")
print("-"*120)

for o in overlaps_sorted[:20]:
    print(f"{o['hsa1']:<40} {o['hsa2']:<40} {o['overlap_km2']:>12.1f} {o['pct_of_hsa1']:>9.1f}% {o['pct_of_hsa2']:>9.1f}%")

# Summary by HSA
print("\n" + "="*100)
print("OVERLAP SUMMARY BY HSA")
print("="*100)

hsa_summary = {}
for hsa in hsas:
    name = hsa['name']
    involved = [o for o in overlaps if o['hsa1'] == name or o['hsa2'] == name]
    
    total_overlap = sum(o['overlap_km2'] for o in involved)
    partners = []
    for o in involved:
        partners.append(o['hsa2'] if o['hsa1'] == name else o['hsa1'])
    
    overlap_pct = (total_overlap / hsa['area_km2']) * 100 if hsa['area_km2'] > 0 else 0
    
    hsa_summary[name] = {
        'area_km2': hsa['area_km2'],
        'total_overlap_km2': total_overlap,
        'overlap_pct': overlap_pct,
        'num_partners': len(partners),
        'partners': partners
    }

sorted_summary = sorted(hsa_summary.items(), key=lambda x: x[1]['overlap_pct'], reverse=True)

print(f"\n{'HSA':<45} {'Area km²':>10} {'Overlap km²':>12} {'Overlap %':>10} {'Partners':>10}")
print("-"*100)

for name, stats in sorted_summary:
    print(f"{name:<45} {stats['area_km2']:>10.1f} {stats['total_overlap_km2']:>12.1f} {stats['overlap_pct']:>9.1f}% {stats['num_partners']:>10}")

# Check specific HSAs
print("\n" + "="*100)
print("SPECIFIC CHECKS")
print("="*100)

basheer = hsa_summary.get('Al-Basheer Hospital', {})
print(f"\nAL-BASHEER HOSPITAL:")
print(f"  Overlaps with: {basheer.get('num_partners', 0)} HSAs")
print(f"  Partners: {', '.join(basheer.get('partners', []))}")
print(f"  Total overlap: {basheer.get('overlap_pct', 0):.1f}% of area")

bsaira = hsa_summary.get('Bsaira Comprehensive Center', {})
print(f"\nBSAIRA COMPREHENSIVE CENTER:")
print(f"  Overlaps with: {bsaira.get('num_partners', 0)} HSAs")

no_overlap = [n for n, s in hsa_summary.items() if s['num_partners'] == 0]
print(f"\nHSAs WITH NO OVERLAPS ({len(no_overlap)}):")
for name in no_overlap:
    print(f"  - {name}")

# Amman metro area
print("\n" + "="*100)
print("AMMAN METRO AREA OVERLAPS")
print("="*100)

amman = ['Al-Basheer Hospital', 'Al Hussain New Salt Hospital', 'AL-Zarqa Hospital', 'Dr. Jamel Al-Totanji Hospital']
print()
for o in overlaps_sorted:
    if o['hsa1'] in amman and o['hsa2'] in amman:
        print(f"{o['hsa1']} ↔ {o['hsa2']}")
        print(f"  {o['overlap_km2']:.1f} km² ({o['pct_of_hsa1']:.1f}% / {o['pct_of_hsa2']:.1f}%)\n")

print("="*100)
print(f"TOTAL PAIRWISE OVERLAPS: {len(overlaps)}")
print(f"HSAs WITH OVERLAPS: {len([s for s in hsa_summary.values() if s['num_partners'] > 0])} of {len(hsas)}")
print("="*100)
