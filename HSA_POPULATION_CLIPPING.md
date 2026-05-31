# HSA Population Clipping: Rationale, Implementation, and Downstream Impact

**Date:** 2026-03-27
**Affects:** `hsa_optimization.py`, `HSA_v6_FINAL.ipynb`, `hsa_mapping_working.py`

---

## What Changed

HSA service areas are no longer saved as full circles. After the optimizer selects facilities and assigns service radii, each circular boundary is clipped to the subset of that circle containing inhabited WorldPop cells. The resulting geometry is a **MultiPolygon** of populated patches — towns, villages, and neighbourhoods — with desert, open plateau, and water bodies excluded.

### Key parameters in `HSA_v6_FINAL.ipynb` (cell 5)

```python
hsa_optimization.clip_hsas_to_population(
    hsas_gdf,
    str(DATA_DIR / 'jor_ppp_2020_constrained.tif'),
    min_pop=0.0,
    coarsen=2,          # 100 m → 200 m effective resolution
    min_patch_km2=0.5,  # drop isolated patches smaller than 0.5 km²
    smooth_m=500,       # morphological closing + simplify at 500 m scale
)
```

The original circular geometry is preserved in a `circle_geometry_wkt` column on every feature for reference.

---

## Rationale

### Why clip at all

Circular service areas in Jordan include large uninhabited areas — the eastern Badiya desert, the Wadi Araba rift, the Gulf of Aqaba, and the Syrian border zone. Including these in GEE climate extractions averages climate signal over landscape that contributes nothing to the disease burden. For the same reason, maps showing circular HSAs over the population raster are visually misleading.

### Why the constrained WorldPop raster, not the UNadj raster

WorldPop produces two population surfaces for Jordan:

| Raster | Method | Desert cells |
|---|---|---|
| `jor_ppp_2020_UNadj.tif` | Dasymetric modelling distributes population to **all land cells** | Small positive values in desert (e.g. 0.001 pp/pixel) |
| `jor_ppp_2020_constrained.tif` | Population placed **only where building footprints are detected** | NoData (−99999) in desert |

Using UNadj, `pop > 0` is true for essentially every land cell, so no desert is ever clipped. The constrained raster produces real zeros in the desert and is the correct choice for identifying inhabited vs uninhabited land.

### Why `min_patch_km2 = 0.5`

Even with the constrained raster, isolated single buildings exist in the desert — military posts, tourist facilities, isolated farms. If retained, the morphological closing merges these with the main populated cluster and effectively re-inflates the circle. Dropping connected components smaller than 0.5 km² eliminates these outliers while preserving genuine village clusters (typically > 1 km²).

### Why `smooth_m = 500` (morphological closing, not convex hull)

After pixel vectorisation, raw populated-cell polygons have staircase edges at 200 m resolution. Two smoothing strategies were considered:

**Convex hull** — rejected. If two village clusters sit on opposite edges of a service radius, their convex hull spans the full diameter and re-introduces the desert gap. Not appropriate for climate extraction purposes.

**Morphological closing at 500 m** — adopted. `buffer(+500 m).buffer(−500 m)` merges nearby clusters (villages within ~1 km of each other) into a single smooth patch while leaving large desert gaps (> 1 km) intact. Followed by Douglas-Peucker simplification at 250 m tolerance to remove remaining pixel-scale vertices. This is defensible because:

- The disease rate denominator is the population of the HSA.
- The relevant climate signal is what that population *experiences*: local temperature, precipitation, soil moisture in the areas where they live, farm, and travel.
- Merging adjacent village clusters captures the inhabited zone plus immediate surroundings without bridging distant desert.

### Why not convex hull for GEE extraction

The purpose of GEE extraction is to characterise the climate experienced by the HSA population. For a coastal city like Aqaba, a convex hull would include the Gulf of Aqaba. For two clusters on opposite ends of a rural HSA, a convex hull would include a large uninhabited plateau between them. The MultiPolygon approach averages only over where people actually are.

---

## Typical results (FEWEST mode, INF network)

| Facility | Retained area | Patches | Notes |
|---|---|---|---|
| Al-Karak Hospital | ~10% of circle | 12 | Karak plateau: many villages, clear inter-village gaps |
| Aqaba Comprehensive | ~8% of circle | 7 | Coastal strip; sea removed |
| Khazzan Primary | ~4% of circle | 5 | Desert fringe; very sparse settlement |
| Al-Basheer Hospital | ~99% of circle | 1 | Urban Amman: nearly fully built-out |

---

## Map visualisation

`hsa_mapping_working.py` now renders two layers per HSA:

- **Dashed green outline**: full service-radius circle clipped to country boundary (reference; appears circular on screen)
- **Solid green fill**: population-clipped MultiPolygon patches (actual inhabited area)

The gap between the two shows excluded desert. For urban HSAs (Al-Basheer, AL-Zarqa) the gap is invisible. For rural/desert-adjacent HSAs (Aqaba, Khazzan) the gap is large and visually obvious.

---

## Downstream pipeline impact

### 1. Patient Allocation (`Patient_Allocation_for_Modeling.ipynb`)

**No changes needed.** The allocator uses facility coordinates and a gravity model; it does not spatially intersect with HSA polygons. The GeoJSON geometry is loaded for reference only.

### 2. GEE Facility-Level Climate (`GEE_Climate_Features_by_Facilities.ipynb`)

**No changes needed.** This notebook extracts climate at facility *points* with a fixed buffer (2 500 m). It does not use HSA polygon boundaries.

### 3. GEE HSA Weekly Climate — **primary extraction** (`GEE_HSA_Weekly_Climate_Lagged.ipynb`, `GEE_local_HSA_Weekly_Climate_Lagged.ipynb`)

**Works as-is; validate before running at scale.**

The notebook already contains explicit MultiPolygon handling in its Earth Engine server-side code (`_force_planar()` handles both `Polygon` and `MultiPolygon`). The geometry cleaning pipeline (`buffer(0)` → `simplify()` → morphological close) is already present.

Action items before running:
- Confirm `bestEffort=True` and `tileScale=4` are set on all `reduceRegion()` calls (complex MultiPolygons can exceed EE tile memory limits).
- Run a single-HSA test for an Aqaba or Khazzan geometry before full batch export.
- Note that extracted mean values now represent the **inhabited-area-weighted** climate signal rather than the full-circle average. This is the correct quantity for health modelling and is a substantive improvement.

### 4. Compare Delineations (`compare_delineations.ipynb`, `compare_spatial_methods_v2.py`)

**Partial fix needed.**

- Overlap and coverage metrics use `rasterio.mask` and `unary_union`; these handle MultiPolygon correctly — no change.
- **Shape compactness** (`4π·area / perimeter²`) is meaningless for a MultiPolygon of disconnected patches (the perimeter sums all patch boundaries; compactness approaches zero even for compact villages).

  Fix: compute compactness on the **convex hull of the union** as a measure of geographic spread, and add a separate `n_patches` column. Update `compute_shape_metrics()` in `compare_spatial_methods_v2.py`:

  ```python
  # For MultiPolygon: use convex hull for compactness, report patch count
  if geom_utm.geom_type == 'MultiPolygon':
      hull = geom_utm.convex_hull
      area_for_compactness = hull.area / 1e6
      perimeter_for_compactness = hull.length / 1000
      n_patches = len(list(geom_utm.geoms))
  else:
      area_for_compactness = geom_utm.area / 1e6
      perimeter_for_compactness = geom_utm.length / 1000
      n_patches = 1
  compactness = (4 * np.pi * area_for_compactness) / (perimeter_for_compactness ** 2)
  ```

### 5. Generate Modeling Dataset (`Generate_Modeling_Dataset.ipynb`, `prepare_ml_dataset.py`)

**No changes needed.** Operates entirely on CSV data from GEE exports. Geometry type has no effect.

### 6. Climate-Health Modeling (`run_climate_health_modeling.ipynb` and all model scripts)

**No changes needed.** All modelling operates on the tabular dataset produced in step 5.

---

## Summary

| Stage | Change required |
|---|---|
| HSA generation (`HSA_v6_FINAL.ipynb`) | **Done** — constrained raster, min_patch, smooth_m=500 |
| Maps (`hsa_mapping_working.py`) | **Done** — dashed circle + solid populated patches |
| Patient allocation | None |
| GEE facility climate | None |
| GEE HSA weekly climate | Validate `bestEffort`/`tileScale`; run single-HSA test first |
| Compare delineations | Fix `compute_shape_metrics()` for MultiPolygon compactness |
| Generate modeling dataset | None |
| Climate-health modeling | None |
