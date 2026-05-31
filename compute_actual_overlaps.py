#!/usr/bin/env python3
"""
PROPER HSA OVERLAP ANALYSIS
Compute actual polygon-to-polygon intersections

The overlap_frac field in properties might be measuring something else
(like overlap during optimization). This script calculates TRUE overlaps.
"""

import json
import os
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import unary_union
import pandas as pd

# Load the GeoJSON
OUT_DIR = Path(os.environ.get("HSA_OUT_DIR", os.environ.get("PIPELINE_OUT_DIR", f"out_{os.environ.get('PIPELINE_VERSION', 'v7')}")))
geojson_path = OUT_DIR / "INF_footprint_hsas_v2.geojson"

with open(geojson_path, 'r') as f:
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
    name = props.get('FacilityName', props.get('anchor_name', 'Unknown'))
    
    # Calculate area in km²
    area_km2 = geom.area * 111 * 111  # Rough conversion for lat/lon to km²
    
    hsas.append({
        'name': name,
        'geometry': geom,
        'area_km2': area_km2,
        'population': props.get('hsa_population', 0),
        'stored_overlap_frac': props.get('overlap_frac', 0)
    })

print(f"Loaded {len(hsas)} HSAs")
print()

# Compute ACTUAL overlaps between each pair
print("Computing pairwise overlaps...")
print()

overlaps = []
overlap_matrix = {}

for i, hsa1 in enumerate(hsas):
    overlap_matrix[hsa1['name']] = {}
    
    for j, hsa2 in enumerate(hsas):
        if i < j:  # Only check each pair once
            intersection = hsa1['geometry'].intersection(hsa2['geometry'])
            
            if not intersection.is_empty and intersection.area > 1e-10:  # Has overlap
                overlap_area_km2 = intersection.area * 111 * 111
                overlap_pct_hsa1 = (intersection.area / hsa1['geometry'].area) * 100
                overlap_pct_hsa2 = (intersection.area / hsa2['geometry'].area) * 100
                
                overlaps.append({
                    'hsa1': hsa1['name'],
                    'hsa2': hsa2['name'],
                    'overlap_km2': overlap_area_km2,
                    'pct_of_hsa1': overlap_pct_hsa1,
                    'pct_of_hsa2': overlap_pct_hsa2
                })
                
                # Store in matrix
                overlap_matrix[hsa1['name']][hsa2['name']] = overlap_pct_hsa1
                overlap_matrix[hsa2['name']][hsa1['name']] = overlap_pct_hsa2

print("="*100)
print("TOP 20 LARGEST OVERLAPS")
print("="*100)
print()

overlaps_sorted = sorted(overlaps, key=lambda x: x['overlap_km2'], reverse=True)

print(f"{'HSA 1':<40} {'HSA 2':<40} {'Overlap km²':>12} {'% of HSA1':>10} {'% of HSA2':>10}")
print("-"*120)

for overlap in overlaps_sorted[:20]:
    print(f"{overlap['hsa1']:<40} {overlap['hsa2']:<40} {overlap['overlap_km2']:>12.1f} "
          f"{overlap['pct_of_hsa1']:>9.1f}% {overlap['pct_of_hsa2']:>9.1f}%")

print()
print("="*100)
print("OVERLAP SUMMARY BY HSA")
print("="*100)
print()

# Calculate total overlap for each HSA
hsa_overlap_summary = {}
for hsa in hsas:
    name = hsa['name']
    
    # Find all overlaps involving this HSA
    involved_overlaps = [o for o in overlaps if o['hsa1'] == name or o['hsa2'] == name]
    
    # Calculate total overlapping area
    total_overlap_area = 0
    overlapping_partners = []
    
    for o in involved_overlaps:
        if o['hsa1'] == name:
            total_overlap_area += o['overlap_km2']
            overlapping_partners.append(o['hsa2'])
        else:
            total_overlap_area += o['overlap_km2']
            overlapping_partners.append(o['hsa1'])
    
    # Calculate as percentage of HSA area
    overlap_pct = (total_overlap_area / hsa['area_km2']) * 100 if hsa['area_km2'] > 0 else 0
    
    hsa_overlap_summary[name] = {
        'area_km2': hsa['area_km2'],
        'total_overlap_km2': total_overlap_area,
        'overlap_pct': overlap_pct,
        'num_overlapping_hsas': len(overlapping_partners),
        'partners': overlapping_partners,
        'stored_overlap_frac': hsa['stored_overlap_frac']
    }

# Sort by overlap percentage
sorted_summary = sorted(hsa_overlap_summary.items(), key=lambda x: x[1]['overlap_pct'], reverse=True)

print(f"{'HSA Name':<45} {'Area km²':>10} {'Overlap km²':>12} {'Overlap %':>10} {'# Partners':>12}")
print("-"*100)

for name, stats in sorted_summary:
    print(f"{name:<45} {stats['area_km2']:>10.1f} {stats['total_overlap_km2']:>12.1f} "
          f"{stats['overlap_pct']:>9.1f}% {stats['num_overlapping_hsas']:>12}")

print()
print("="*100)
print("SPECIFIC QUESTIONS")
print("="*100)
print()

# Check Al-Basheer specifically
basheer_stats = hsa_overlap_summary.get('Al-Basheer Hospital', {})
print(f"AL-BASHEER HOSPITAL:")
print(f"  Total area: {basheer_stats.get('area_km2', 0):,.1f} km²")
print(f"  Overlapping area: {basheer_stats.get('total_overlap_km2', 0):,.1f} km²")
print(f"  Overlap percentage: {basheer_stats.get('overlap_pct', 0):.1f}%")
print(f"  Number of overlapping HSAs: {basheer_stats.get('num_overlapping_hsas', 0)}")
print(f"  Overlaps with: {', '.join(basheer_stats.get('partners', []))}")
print(f"  Stored overlap_frac field: {basheer_stats.get('stored_overlap_frac', 0):.4f}")
print()

# Check Bsaira
bsaira_stats = hsa_overlap_summary.get('Bsaira Comprehensive Center', {})
print(f"BSAIRA COMPREHENSIVE CENTER:")
print(f"  Total area: {bsaira_stats.get('area_km2', 0):,.1f} km²")
print(f"  Overlapping area: {bsaira_stats.get('total_overlap_km2', 0):,.1f} km²")
print(f"  Overlap percentage: {bsaira_stats.get('overlap_pct', 0):.1f}%")
print(f"  Number of overlapping HSAs: {bsaira_stats.get('num_overlapping_hsas', 0)}")
print()

# HSAs with NO overlaps
no_overlap_hsas = [name for name, stats in hsa_overlap_summary.items() 
                   if stats['num_overlapping_hsas'] == 0]

print(f"HSAs WITH NO OVERLAPS ({len(no_overlap_hsas)}):")
for name in no_overlap_hsas:
    print(f"  - {name}")

print()
print("="*100)
print("AMMAN METRO AREA DETAILED OVERLAPS")
print("="*100)
print()

amman_hsas = ['Al-Basheer Hospital', 'Al Hussain New Salt Hospital', 
              'AL-Zarqa Hospital', 'Dr. Jamel Al-Totanji Hospital']

print("Pairwise overlaps among Amman metro HSAs:")
print()
for overlap in overlaps_sorted:
    if overlap['hsa1'] in amman_hsas and overlap['hsa2'] in amman_hsas:
        print(f"{overlap['hsa1']:<40} ↔ {overlap['hsa2']:<40}")
        print(f"  Overlap area: {overlap['overlap_km2']:>8.1f} km²")
        print(f"  As % of {overlap['hsa1']}: {overlap['pct_of_hsa1']:>5.1f}%")
        print(f"  As % of {overlap['hsa2']}: {overlap['pct_of_hsa2']:>5.1f}%")
        print()

print("="*100)
print("SUMMARY STATISTICS")
print("="*100)
print()

total_overlaps = len(overlaps)
hsas_with_overlaps = len([s for s in hsa_overlap_summary.values() if s['num_overlapping_hsas'] > 0])
hsas_without_overlaps = len(hsas) - hsas_with_overlaps

mean_overlap_pct = sum(s['overlap_pct'] for s in hsa_overlap_summary.values()) / len(hsas)
max_overlap_pct = max(s['overlap_pct'] for s in hsa_overlap_summary.values())

print(f"Total number of pairwise overlaps: {total_overlaps}")
print(f"HSAs with at least one overlap: {hsas_with_overlaps} of {len(hsas)}")
print(f"HSAs with no overlaps: {hsas_without_overlaps} of {len(hsas)}")
print(f"Mean overlap percentage: {mean_overlap_pct:.1f}%")
print(f"Maximum overlap percentage: {max_overlap_pct:.1f}%")

print()
print("="*100)
print("CONCLUSION")
print("="*100)
print()

if basheer_stats.get('num_overlapping_hsas', 0) > 0:
    print("❌ Al-Basheer Hospital DOES have overlaps!")
    print(f"   It overlaps with {basheer_stats.get('num_overlapping_hsas', 0)} other HSAs")
else:
    print("✓ Al-Basheer Hospital has NO overlaps")

if bsaira_stats.get('num_overlapping_hsas', 0) == 0:
    print("✓ Bsaira Comprehensive Center has NO overlaps (user was correct!)")
else:
    print("❌ Bsaira Comprehensive Center DOES have overlaps")

print()
print("The 'overlap_frac' field in the GeoJSON properties likely measures")
print("something different (e.g., overlap during optimization with governorates)")
print("rather than HSA-to-HSA overlap.")
print()
print("="*100)
