# Probabilistic Patient Allocation Methodology

## Overview

This document describes the two-step probabilistic allocation methodology used to assign population to Hospital Service Areas (HSAs) in Jordan.

## Problem Statement

HSAs created by the optimization algorithm are **overlapping circular regions** around hospital facilities. Each facility has a service radius (typically 10-25 km), and service areas overlap where circles intersect. This creates challenges for disease modeling:

1. **Double-counting problem**: Without proper allocation, the same population pixel can be counted in multiple overlapping HSAs
2. **Facility-to-HSA mapping**: The optimization identifies ~17-27 HSA anchors, but there are ~188 total facilities in each network that also serve patients

## Two-Step Solution

### Step 1: Probabilistic Pixel Allocation to ALL Facilities

Instead of assigning each 100m population pixel to exactly ONE facility (hard assignment), we **split each pixel's population across ALL reachable facilities** based on gravity model probabilities.

**Gravity Model Formula**:

```
Attractiveness(facility_i) = Volume_i^α / Distance_i^β

Probability(facility_i | pixel) = Attractiveness_i / Σ_j Attractiveness_j
```

**Parameters**:
| Parameter | Value | Description |
|-----------|-------|-------------|
| α (alpha) | 0.75 | Facility size weight - larger facilities attract from farther |
| β (beta) | 1.5 | Distance decay exponent - closer facilities more attractive |
| max_distance_km | 100 | Maximum travel distance considered |

**Population Allocation**:
```
Allocated_pop(facility_i, pixel) = Population(pixel) × Probability(facility_i | pixel)
```

**Advantages of Probabilistic Allocation**:
1. More realistic model of patient choice behavior
2. No arbitrary "winner-take-all" assignment
3. Accounts for patient flexibility in choosing facilities
4. Smooth allocation without sharp boundaries

### Step 2: Facility → HSA Aggregation (Three-Case Logic)

After allocating population to all ~188 facilities, we aggregate each facility's total population to HSAs based on spatial containment:

| Case | Condition | Assignment Rule |
|------|-----------|-----------------|
| **Case 1** | Facility inside exactly 1 HSA service circle | 100% of population to that HSA |
| **Case 2** | Facility outside ALL HSA service circles | Assign to nearest HSA anchor within 100km; if beyond 100km, exclude and report |
| **Case 3** | Facility inside 2+ overlapping HSA circles | Split proportionally using gravity model (same formula as Step 1) |

**Case 3 Formula** (Gravity-Based Proportional Allocation):
```
Weight(HSA_k) = Volume_k^α / Distance(facility, HSA_k_anchor)^β
Proportion(HSA_k) = Weight_k / Σ_j Weight_j
Allocated(HSA_k) = Facility_population × Proportion_k
```

This ensures consistency: **the same gravity model is used throughout** - both for pixel-to-facility allocation (Step 1) and for facility-to-HSA assignment in overlapping regions (Case 3 of Step 2).

## Output Files

### Primary Output
- `{NETWORK}_{MODE}_hsa_populations_probabilistic.csv`: HSA-level population totals for disease modeling

### Supporting Files
- `{NETWORK}_{MODE}_facility_allocations_probabilistic.csv`: Facility-level population allocations from pixels
- `{NETWORK}_{MODE}_facility_hsa_assignments.csv`: Detailed facility-to-HSA mapping showing which case applied

## Key Tables for Paper

### Table S-X: HSA Population Summary (Example: INF-FOOTPRINT)

| Rank | HSA Anchor | Allocated Population | # Facilities |
|------|------------|---------------------|--------------|
| 1 | Al-Basheer Hospital | 3,245,123 | 42 |
| 2 | AL-Zarqa Hospital | 1,123,456 | 28 |
| ... | ... | ... | ... |
| N | Total | 10,176,801 | 188 |

### Table S-Y: Facility Assignment Case Distribution

| Assignment Case | Facilities | % | Population | % |
|-----------------|------------|---|------------|---|
| Case 1: Inside 1 HSA | 145 | 77.1% | 8,234,567 | 80.9% |
| Case 2: Outside (nearest) | 38 | 20.2% | 1,789,012 | 17.6% |
| Case 3: Overlapping (proportional) | 5 | 2.7% | 153,222 | 1.5% |
| Excluded (beyond max) | 0 | 0.0% | 0 | 0.0% |
| **Total** | **188** | **100%** | **10,176,801** | **100%** |

### Table S-Z: Gravity Model Parameters

| Parameter | Symbol | Value | Justification |
|-----------|--------|-------|---------------|
| Facility size weight | α | 0.75 | Moderate volume effect |
| Distance decay | β | 1.5 | Moderate distance penalty |
| Maximum distance | d_max | 100 km | Jordan's geography |
| Population raster | - | 100m grid | WorldPop 2020 |

## Validation Checks

1. **Population coverage**: Allocated population should be ≥99% of raster total
2. **No double-counting**: Each pixel's population summed once across all facilities
3. **HSA completeness**: All HSA anchors should have assigned population
4. **Excluded facilities**: Should be minimal (<1% of total population)

## Implementation

**Files**:
- `population_allocation.py`: Core allocation module
- `Population_Allocation_Probabilistic_v2.ipynb`: Interactive notebook
- `allocate_population_probabilistic()`: Convenience function

**Key Methods**:
```python
# Step 1: Probabilistic allocation
allocator = PopulationAllocator(pop_raster, all_facilities, params)
facility_allocs = allocator.allocate_all_pixels_probabilistic_parallel()

# Step 2: Facility → HSA aggregation
hsa_summary, assignments = allocator.aggregate_facilities_to_hsas(
    facility_allocs, hsa_anchors, all_facilities
)
```

## Comparison to Hard Allocation

| Aspect | Hard Allocation | Probabilistic Allocation |
|--------|-----------------|-------------------------|
| Pixel assignment | 1 facility (max attractiveness) | All facilities (probability-weighted) |
| Boundary effects | Sharp transitions | Smooth gradients |
| Patient behavior model | Winner-take-all | Mixed preferences |
| Computational cost | Lower | Higher (~2x) |
| Double-counting | Eliminated at pixel level | Eliminated at pixel level |

Both methods eliminate double-counting. The probabilistic method provides a more realistic representation of patient choice behavior at the cost of additional computation.

## Consistency of Gravity Model

The same gravity model formula is used throughout the allocation process:

| Step | Context | Formula |
|------|---------|---------|
| Step 1 | Pixel → Facility | $W_i = V_i^\alpha / D_i^\beta$ |
| Step 2 (Case 3) | Facility → HSA (overlapping) | $W_k = V_k^\alpha / D_k^\beta$ |

Where:
- $V$ = Volume (patient volume at facility or HSA anchor)
- $D$ = Distance (pixel-to-facility or facility-to-anchor)
- $\alpha = 0.75$ (facility size weight)
- $\beta = 1.5$ (distance decay)

This consistency ensures that larger HSA anchors attract proportionally more population from facilities in overlapping service areas, just as larger facilities attract more population from pixels.

---

*Generated: 2026-02-12*
*Author: HSA Research Team*
