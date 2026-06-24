# Delineating Hospital Service Areas in Data-Scarce Settings
## Theory, Algorithm, and Validation

**Webinar 1 of 3 — 90 minutes**

*Zaslavsky et al., GeoHealth (in review)*

---

## Agenda

- Why HSAs matter for health systems analysis
- What existing methods get wrong in LMICs
- The optimization framework: objectives, constraints, algorithm
- Post-greedy anchor quality control (v7 and v8)
- Comparison with fixed-radius and Voronoi alternatives
- Limitations and future directions

---

## What Is a Hospital Service Area?

An HSA is a geographic unit representing the primary catchment of one or more healthcare facilities.

HSAs serve three purposes in health research:

- **Epidemiological surveillance**: aggregate disease cases to a stable geographic unit
- **Health equity analysis**: compare access, utilization rates, and disease burden across regions
- **Environmental health**: link climate and environmental exposures to health outcomes at appropriate spatial scales

The classic US definition (Dartmouth Atlas, 1996) derives HSAs from Medicare claims: draw a boundary around the plurality of patients for each hospital. That requires individual patient origin data.

---

## The LMIC Problem

In low- and middle-income countries, patient origin data are rarely available in machine-readable form.

**What is usually available:**

- Facility locations (GPS coordinates)
- Facility type and administrative capacity
- Population distribution rasters (WorldPop, GPWv4)
- Administrative boundaries

**What is not available:**

- Patient addresses or origin ZIP codes
- Individual travel routes
- Insurance claims linked to providers

Methods designed for the US context cannot be directly applied.

---

## Why Not Just Use Fixed-Radius Buffers?

The intuitive fallback: draw a 15 km circle around each facility. Problems:

| Metric | Fixed 15 km (all facilities) | Optimized HSA |
|--------|-------------------------------|---------------|
| Spatial units | 184 | 17 |
| Coverage multiplier | 24.5× | 1.31× |
| Usable for disease rates | No | Yes |

A 24.5× multiplier means each person is counted in 24 facilities on average. Disease rates computed from fixed-radius denominators are meaningless.

Fixed buffers also ignore facility capacity, patient volume, and geographic accessibility.

---

## Why Not Voronoi Tessellation?

Voronoi (nearest-facility) tessellation partitions space without overlap — but:

- Assigns every pixel to the nearest facility regardless of capacity
- Produces 154 units for 154 INF facilities; too fine for surveillance
- Spatial concordance with clinically meaningful catchments: 10.4%
- Compactness: 0.655 (highly irregular shapes)

Neither method selects which facilities should anchor population aggregation units.

---

## The Core Insight

Not all facilities should be HSA anchors.

A primary care clinic serving 200 patients should not be an independent surveillance unit. A regional hospital serving 50,000 patients should be.

**HSA delineation is a facility selection problem** with two coupled objectives:

1. Select a small set of anchor facilities that collectively cover the target population
2. Delineate service area boundaries that minimize overlap and reflect travel accessibility

The optimization must balance these objectives against each other, across varying urban–rural geographies, without patient origin data.

---

## Adaptive Service Radii

Before optimization, each facility receives an individual service radius.

**Base radius:**

- Urban facilities: 10 km
- Rural facilities: 18 km (determined by population density at facility location)

**Volume adjustment:** ±3 km scaled by patient volume relative to the network median.

High-volume facilities receive slightly larger radii; low-volume facilities receive slightly smaller radii. The range is capped to prevent very large facilities from dominating at the expense of geographic coverage.

These radii define the spatial footprint each facility *could* claim as its service area if selected.

---

## The Multi-Objective Score

At each greedy iteration, every unselected facility receives a score:

```
score = w₁·coverage_gain
      + w₂·volume_contribution
      + w₃·climate_diversity_gain
      + w₄·coverage_progress
      - w₅·overlap_penalty
      - w₆·distance_penalty
```

The facility with the highest positive score is added to the anchor set.

**Coverage gain**: population newly covered by this facility's radius (not already covered).

**Overlap penalty**: population already covered by previously selected facilities, counted again by this radius.

**Distance penalty**: mean travel distance from covered pixels to this facility.

**Climate diversity**: how different this facility's climate profile is from already-selected facilities.

---

## Five Optimization Modes

The same algorithm runs with different objective weights, producing different trade-offs:

| Mode | Priority |
|------|----------|
| `fewest` | Minimize anchor count; maximize coverage per anchor |
| `footprint` | Balance coverage and overlap; general-purpose |
| `distance` | Minimize travel distance; maximizes access equity |
| `governorate_fewest` | At least one anchor per governorate |
| `governorate_tau_coverage` | Governorate-constrained with coverage threshold τ |

Each mode produces a different set of anchor facilities and boundary geometries. The `footprint` mode is the primary mode used in downstream modeling.

---

## Greedy Selection: Illustrated

```
Iteration 1:
  Select facility with highest score → Al-Basheer Hospital (Amman)
  Covers ~3.2M population (31% of Jordan)

Iteration 2:
  Select next best → AL-Zarqa Hospital
  Adds ~1.1M (not already covered)
  Overlap penalty applied where radii intersect

...

Iteration 17:
  Coverage target reached (90%)
  Stop
```

The algorithm takes ~0.3 seconds per iteration. Five modes × 17 anchors = 85 scoring calculations per run.

---

## The Greedy Limitation

Greedy algorithms are myopic: each selection is locally optimal at the time of selection.

Two failure modes are known in this problem:

**Failure 1 — Weak anchor selection**: The greedy step selects a small primary center because it provides marginal coverage gain or climate diversity. A much larger hospital lies within the same service radius but was not considered at that iteration.

**Failure 2 — Major-facility orphaning**: A large regional hospital is not selected because the coverage target was reached before reaching its area. The default fallback (nearest selected anchor) may assign it to a small or distant facility — a clinically implausible result.

Both failures occurred in the INF-FOOTPRINT run on Jordan data, particularly for southern facilities.

---

## v7: Anchor Upgrade / Demotion

After greedy selection, v7 checks each selected anchor against nearby unselected facilities.

**Replacement is applied when:**

- An unselected facility lies within the selected anchor's service radius
- It is in the same governorate (when metadata is available)
- Its patient volume is at least 2× larger, or it is a higher facility type
- The volume gain is at least 100 diagnosis records

The weaker facility is *demoted* to a regular facility (still allocatable). The stronger facility inherits the original anchor's service radius and optimization metadata.

**Five replacements in INF-FOOTPRINT:**

| Demoted anchor | New anchor | Volume ratio |
|----------------|------------|-------------|
| Bsaira Comprehensive Center | Tafilah Governmental Hospital | 4.09× |
| North Madaba Comprehensive Center | AL-Nadeem Hospital | 4.85× |
| Jadaa Primary Center | Faqqou Comprehensive Center | 75.1× |

---

## v7: Major-Orphan Promotion

After anchor upgrades, v7 checks whether any major facility is uncovered without a plausible fallback.

**A major facility is any hospital or facility above the 80th volume percentile.**

**Plausible fallback requires:**

- Distance ≤ min(100 km, max(1.5 × nearest anchor radius, 30 km))
- Same-governorate anchor for major facilities

If no plausible fallback exists, the facility is promoted to an anchor.

**Two promotions in INF-FOOTPRINT:**

| Promoted facility | Volume | Nearest prior anchor | Distance | Cross-governorate |
|-------------------|--------|----------------------|----------|-------------------|
| Maan Hospital | 4,534 | Tafilah Gov. Hospital | 72.6 km | Yes |
| Queen Rania Hospital | 1,512 | Tafilah Gov. Hospital | 64.6 km | Yes |

Result: 19 anchors instead of 17 in the southern anchor set.

---

## v8: Satellite Bubble Boundaries

v8 adds a third step after anchor upgrade and major-orphan promotion.

For each selected anchor, v8 identifies *satellite facilities*: unselected facilities that:

- Lie within or near the anchor's service radius
- Are above a minimum volume threshold
- Would improve local geographic or demographic coverage if given a small secondary catchment

Each satellite receives a smaller "bubble" radius (proportional to its volume). The HSA polygon is the union of the anchor catchment and all satellite bubbles.

This creates more complex, non-circular HSA shapes that better reflect secondary service hubs — at the cost of more complex boundary geometry.

---

## Hardened Fallback Allocation

The patient allocation step assigns each facility to its HSA based on three cases:

| Case | Condition | Rule |
|------|-----------|------|
| 1 | Inside exactly 1 HSA radius | 100% to that HSA |
| 2 | Outside all HSA radii | Nearest *admissible* anchor only |
| 3 | Inside 2+ overlapping radii | Gravity-weighted split |

In v1, Case 2 was "nearest anchor" with no distance limit. In v2, admissibility requires:

- Distance ≤ min(100 km, max(1.5 × anchor radius, 30 km))
- Same-governorate preference for major facilities

Facilities failing admissibility are **excluded and reported**, not silently attached.

---

## Gravity Model for Population Allocation

For Case 3 (overlapping HSA radii), and for pixel-to-facility allocation:

```
Attractiveness(facility_i) = Volume_i^0.75 / Distance_i^1.5

Probability(facility_i | pixel) = Attractiveness_i / Σ_j Attractiveness_j
```

Parameters (α = 0.75, β = 1.5) represent moderate volume sensitivity and moderate distance decay — calibrated to Jordan's geography and facility network.

The same gravity formula is used throughout: pixel→facility and facility→HSA. This consistency eliminates seams where different allocation rules would produce discontinuous population counts.

---

## Comparison: v6 vs v7 vs v8

| Feature | v6 | v7 | v8 |
|---------|----|----|-----|
| Algorithm | Greedy only | + Anchor QC | + Satellite bubbles |
| INF anchors (footprint) | 17 | 19 | 19 |
| Anchor identity check | No | Yes | Yes |
| Major-orphan guard | No | Yes | Yes |
| Boundary shape | Circular | Circular | Non-circular |
| Usable for downstream? | Yes | Yes | Yes |
| Recommended for? | Baseline/paper | Default | Boundary sensitivity |

All three versions are produced by a single run of `HSA_FINAL.ipynb`.

---

## Spatial Methods Comparison

| Method | Units | Coverage | Multiplier | Compactness | Surveillance-ready |
|--------|-------|----------|------------|-------------|-------------------|
| Optimized HSA (v7) | 17–19 | 90.6% | 1.31× | 0.999 | Yes |
| Fixed 10 km | 184 | 90.5% | 15.2× | 0.988 | No |
| Fixed 18 km | 184 | 96.9% | 30.9× | 0.977 | No |
| Voronoi | 154 | 99.7% | 1.0× | 0.655 | No (too fine) |
| Governorate | 12 | 99.7% | 1.0× | 0.510 | No (too coarse) |

The optimized approach is the only one that is simultaneously surveillance-ready, appropriately granular, and low-overlap.

---

## Validating HSA Face Validity

Face validity checks (applied informally throughout):

1. **Type check**: Are anchors hospitals or high-volume facilities, not primary centers?
2. **Geographic coverage**: Is each governorate represented?
3. **Population range**: Do HSAs avoid extreme size disparities?
4. **Named facility check**: Are well-known regional hospitals in their expected HSA?
5. **Cross-governorate check**: Are no major hospitals assigned across governorate lines?

The v7 anchor upgrade and major-orphan promotion steps formalize checks 1, 4, and 5 as automated tests run at the end of every optimization.

---

## Limitations

**Algorithm limitations:**

- Greedy selection is not globally optimal; post-hoc correction handles the two known failure modes but not all possible suboptimal selections
- Service radii are calibrated to Jordan; transferring to other countries requires parameter review
- The algorithm requires population rasters and facility volumes; pure location-only inputs yield lower-quality results

**Data limitations:**

- Synthetic patient visits (SYNMOD) preserve statistical structure but should not be used for substantive clinical inference
- WorldPop 2020 rasters are the most recent available; demographic shifts after 2020 are not reflected

**Scope limitations:**

- Method validated on two Jordan networks; external validation in another LMIC is pending

---

## Open Questions for Discussion

1. How sensitive are downstream epidemiological results to the choice of v6, v7, or v8 boundaries?
2. Can the anchor upgrade parameters (2× volume ratio, same-governorate constraint) be derived analytically rather than set empirically?
3. For networks with very high facility density (urban cores), are 10 km urban radii still appropriate?
4. Is a single gravity model parameterization (α=0.75, β=1.5) transferable across different country contexts?

---

## Summary

- HSA delineation is a facility selection + boundary construction problem
- Fixed-radius and Voronoi methods fail for LMIC surveillance due to extreme overlap or excessive fragmentation
- The greedy multi-objective algorithm selects anchors balancing coverage, overlap, volume, and climate diversity
- v7 adds two deterministic post-selection guardrails: anchor upgrade and major-orphan promotion
- v8 adds satellite bubble boundaries for non-anchor facilities
- All three variants are produced by a single notebook and selectable in all downstream steps

**Code**: `HSA_FINAL.ipynb` → produces `{NETWORK}_{MODE}_hsas_{v6|v7|v8}.geojson`

---

## Further Reading

- Dartmouth Atlas methodology: Wennberg & Cooper (1996)
- Gravity model for healthcare: Luo & Wang (2003)
- Multi-objective greedy coverage: Hochbaum (1996) approximation bounds
- WorldPop: Tatem (2017), *Scientific Data*
- CHIRPS precipitation: Funk et al. (2015)
- ERA5-Land: Muñoz-Sabater et al. (2021)
