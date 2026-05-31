# HSA v7 Algorithm Modifications Compared With the GeoHealth Manuscript

This note describes the algorithmic changes implemented in:

- `HSA_v7_FINAL.ipynb`
- `Patient_Allocation_Probabilistic_v2.ipynb`
- `hsa_optimization.py`
- `patient_allocation.py`

It is written specifically as a comparison against the algorithm described in:

`/Users/ilya/WORK_PROJECTS/gc3wefh/HSA_paper/Zaslavsky_etal_GeoHealth_HSA_Jordan_main.docx`

The short version is that the manuscript describes a greedy multi-objective HSA anchor-selection algorithm followed by gravity-based population allocation. The v7 implementation keeps that core algorithm, but adds two governance/quality-control steps around the greedy selection and tightens the out-of-radius fallback rule during allocation. These changes were introduced after diagnosing an implausible result in which large southern facilities, especially Maan Hospital and Queen Rania Hospital, could be absorbed by smaller or distant anchors under a nearest-anchor fallback.

## 1. Baseline Algorithm in the Manuscript

The manuscript describes the HSA construction workflow as:

1. Start from fixed facility locations and patient/facility volumes.
2. Compute adaptive service radii:
   - urban base radius: 10 km
   - rural base radius: 18 km
   - volume adjustment: approximately -3 km to +3 km
3. Run a greedy multi-objective facility-selection algorithm.
4. Stop when the selected service areas reach the target population coverage.
5. Clip service areas to Jordan and inhabited WorldPop cells for exposure aggregation.
6. Resolve overlap through gravity-based population allocation.

The manuscript describes the greedy score as balancing:

- coverage gain
- facility size/patient volume
- climatic diversity
- progress toward target coverage
- overlap penalty
- distance/access penalty

For allocation, the manuscript describes three cases:

| Case | Manuscript behavior |
|---|---|
| Case 1 | Facility falls inside one HSA radius: assign to that anchor. |
| Case 2 | Facility falls outside all HSA radii: assign to the nearest HSA anchor. |
| Case 3 | Facility falls inside overlapping HSA radii: split using gravity weights. |

This was a reasonable first formulation, but the Case 2 rule was too permissive. A large facility outside every selected HSA could be attached to a small or distant anchor solely because that anchor was the nearest selected anchor.

## 2. Problem Identified

The issue was exposed by the INF-FOOTPRINT daily climate pipeline. The old footprint had 17 HSAs and a problematic southern HSA centered on `Bsaira Comprehensive Center`. That HSA could receive large southern facilities in downstream allocation or climate aggregation logic, even though much larger and more clinically defensible facilities existed nearby or regionally:

- `Maan Hospital`
- `Queen Rania Hospital`
- `Tafilah Governmental Hospital`

The specific conceptual failure was not a geometry validity problem. It was an algorithmic issue:

1. The greedy optimizer can select a small facility because it provides local coverage, climate/geographic representation, or marginal objective gain at that iteration.
2. Greedy selection does not automatically reconsider that anchor after nearby larger facilities become relevant.
3. The allocation fallback can then attach large uncovered facilities to the nearest selected anchor, even when that anchor is clinically and operationally inferior.

This is a known limitation of greedy algorithms for set-cover and maximum-coverage style problems. Greedy methods are myopic: each selected anchor is locally attractive at selection time, but the algorithm does not perform later exchange, swap, or dominance correction unless explicitly added. In this setting, the failure mode is not only mathematical suboptimality; it is also a face-validity problem for named HSA anchors.

## 3. What v7 Keeps Unchanged

The v7 algorithm does not replace the manuscript's framework. It preserves the core structure:

- adaptive radius construction
- multi-objective greedy selection
- mode-specific objective weights
- overlap pruning
- inhabited-footprint HSA polygons
- gravity-based allocation for overlap cases
- mode variants such as FEWEST, FOOTPRINT, DISTANCE, and governorate-constrained modes

The modifications are guardrails around anchor identity and fallback behavior. They are intended to prevent absurd anchor assignments while retaining the original optimization logic.

## 4. Modification 1: Anchor Upgrade / Demotion

### Purpose

After greedy selection, v7 checks whether any selected anchor is a weak local representative that should be replaced by a stronger nearby facility.

This handles cases where the greedy objective selected a small primary or comprehensive center, but a larger hospital or stronger facility lies inside the same local service area. The selected small facility is not discarded from the system; it is demoted from anchor status and remains a normal facility that can be assigned during patient allocation.

### Implementation

Implemented in:

`hsa_optimization.py::upgrade_selected_anchors_to_stronger_facilities`

Called from:

`HSA_v7_FINAL.ipynb`

### Current parameters

| Parameter | Value | Meaning |
|---|---:|---|
| `UPGRADE_WEAK_SELECTED_ANCHORS` | `True` | Enables the correction. |
| `ANCHOR_UPGRADE_SEARCH_RADIUS_MULTIPLIER` | `1.0` | Search within the selected anchor's service radius. |
| `ANCHOR_UPGRADE_MIN_VOLUME_RATIO` | `2.0` | Candidate is eligible if at least twice as large, unless stronger type also qualifies it. |
| `ANCHOR_UPGRADE_MIN_ABSOLUTE_VOLUME_GAIN` | `100.0` | Candidate must exceed original anchor by at least 100 diagnosis records/volume units. |
| `ANCHOR_UPGRADE_REQUIRE_SAME_GOVERNORATE` | `True` | Replacement is constrained to the same governorate when governorate metadata are available. |

### Facility type ranking

The upgrade step uses a simple ordinal type ranking:

| Type | Rank |
|---|---:|
| Hospital | 3 |
| Comprehensive center | 2 |
| Primary center | 1 |
| Other/unknown | 0 |

### Replacement rule

For each selected anchor, v7 searches unselected facilities within the anchor's service radius. A candidate can replace the selected anchor if:

1. the candidate is not already selected;
2. it is in the same governorate, when the same-governorate guard applies;
3. its volume exceeds the selected anchor's volume;
4. its absolute volume gain is at least 100;
5. it is either a stronger facility type or at least twice as large by volume.

If multiple candidates qualify, the chosen replacement favors:

1. higher facility type;
2. larger volume ratio;
3. larger volume gain;
4. shorter distance.

The replacement inherits the original selected anchor's service radius and optimization metadata. This is important: the correction changes the anchor identity and location, but does not let the post-processing step create an unconstrained new catchment radius.

### Current INF-FOOTPRINT effect

In the current v7 INF-FOOTPRINT run, five anchor upgrades were applied:

| Original selected anchor | Replacement anchor | Original volume | Replacement volume | Distance km | Volume ratio |
|---|---|---:|---:|---:|---:|
| North Madaba Comprehensive Center | AL-Nadeem Hospital | 448 | 2,175 | 3.88 | 4.85 |
| Prince Hashem Primary Center | Al-Iman Hospital | 357 | 620 | 7.12 | 1.74 |
| Bsaira Comprehensive Center | Tafilah Governmental Hospital | 161 | 658 | 11.71 | 4.09 |
| Khazzan Primary Center | Princess Basma Comprehensive Clinic | 72 | 476 | 4.38 | 6.61 |
| Jadaa Primary Center | Faqqou Comprehensive Center | 9 | 676 | 5.76 | 75.11 |

The Bsaira correction is the most relevant for the original failure. Under v7, `Bsaira Comprehensive Center` is not retained as the HSA anchor. It is demoted to an ordinary facility, and `Tafilah Governmental Hospital` becomes the anchor for that local HSA.

## 5. Modification 2: Major Uncovered Facility Promotion

### Purpose

After anchor upgrades, v7 checks whether any major facility is:

1. not already selected as an anchor;
2. not covered by any selected HSA service radius;
3. lacking a plausible fallback anchor.

If all three conditions are true, the facility is promoted to an HSA anchor.

This prevents large hospitals from being absorbed by distant or small anchors simply because the original greedy selection did not need them to reach the population coverage target.

### Implementation

Implemented in:

`hsa_optimization.py::promote_major_uncovered_facilities`

Called from:

`HSA_v7_FINAL.ipynb`

### Current parameters

| Parameter | Value | Meaning |
|---|---:|---|
| `PROMOTE_MAJOR_UNCOVERED_FACILITIES` | `True` | Enables major-orphan promotion. |
| `MAJOR_FACILITY_POP_THRESHOLD` | `25000.0` | Major-facility threshold. In HSA selection this is applied to available facility volume fields where population is not yet available. |
| `MAJOR_FACILITY_VOLUME_QUANTILE` | `0.80` | Facilities above the 80th percentile of positive volume are major. |
| `MAJOR_FACILITY_VOLUME_THRESHOLD` | `None` | If unset, computed from the 80th percentile. |
| `ORPHAN_FALLBACK_RADIUS_MULTIPLIER` | `1.5` | Fallback allowance is at least 1.5 times the nearest anchor radius. |
| `ORPHAN_FALLBACK_MIN_DISTANCE_KM` | `30.0` | Fallback allowance is at least 30 km. |
| `REQUIRE_SAME_GOVERNORATE_FOR_MAJOR_FALLBACK` | `True` | Major facilities should not fall back across governorates unless very close. |

### Major-facility rule

A facility is considered major if any of the following hold:

- it is a hospital;
- its volume is above the computed 80th percentile threshold;
- its volume exceeds the configured absolute threshold.

In patient allocation, where allocated population is available, the analogous major-facility rule also uses allocated population.

### Fallback plausibility rule

For a non-selected facility, v7 computes the nearest selected anchor and defines a fallback limit:

`fallback_limit = min(100 km, max(1.5 * nearest_anchor_radius, 30 km))`

A fallback is plausible only if:

- the facility is within that fallback limit; and
- for major facilities, the fallback is in the same governorate, unless the cross-governorate distance is within the 30 km minimum allowance.

If a major uncovered facility has no plausible fallback, it is promoted to an anchor.

### Current INF-FOOTPRINT effect

In the current v7 INF-FOOTPRINT run, two major uncovered hospitals were promoted:

| Promoted facility | Type | Governorate | Volume | Nearest prior anchor | Distance km | Fallback limit km | Same governorate |
|---|---|---|---:|---|---:|---:|---|
| Maan Hospital | Hospital | Ma'an | 4,534 | Tafilah Governmental Hospital | 72.65 | 30.0 | False |
| Queen Rania Hospital | Hospital | Ma'an | 1,512 | Tafilah Governmental Hospital | 64.60 | 30.0 | False |

This is the core correction for the southern Jordan issue. Under v7, these facilities are no longer forced into a Tafilah/Bsaira-type fallback. They become anchors, producing a Maan-anchored southern HSA structure.

The final current INF-FOOTPRINT anchor set has 19 anchors, not the 17 anchors reported in the manuscript's older run. The added anchors reflect the new face-validity guardrails rather than a change in the underlying target coverage objective.

## 6. Modification 3: Hardened Patient Allocation Fallback

### Purpose

The manuscript's allocation Step 2 says that facilities outside all HSA radii are assigned to the nearest HSA anchor. That rule is now too permissive for v7.

In `Patient_Allocation_Probabilistic_v2.ipynb`, Case 2 has been changed from:

`outside all HSAs -> nearest anchor`

to:

`outside all HSAs -> nearest admissible anchor, otherwise exclude and report as requiring anchor promotion`

### Implementation

Implemented in:

`patient_allocation.py`

Used by:

`Patient_Allocation_Probabilistic_v2.ipynb`

### Current fallback parameters

| Parameter | Value |
|---|---:|
| `max_distance_km` | 100 |
| `fallback_radius_multiplier` | 1.5 |
| `fallback_min_distance_km` | 30.0 |
| `major_facility_pop_threshold` | 25,000 |
| `major_facility_volume_quantile` | 0.80 |
| `require_same_governorate_for_major` | `True` |

### Case 2 behavior in v2 allocation

For a facility outside all HSA radii:

1. Compute distance to every anchor.
2. For each anchor, compute:

   `anchor_limit = min(100 km, max(anchor_radius * 1.5, 30 km))`

3. Keep only anchors within their `anchor_limit`.
4. Prefer same-governorate admissible anchors.
5. For major facilities, require same-governorate fallback unless the fallback is a nearby cross-governorate fallback within 30 km.
6. If no anchor is admissible, mark the facility:

   `EXCLUDED: Requires anchor promotion`

This makes the allocation step diagnostic. It no longer silently hides a bad HSA design by assigning an important facility to an implausible nearest anchor.

### Current allocation behavior

In the current v2 allocation run for INF-FOOTPRINT:

- 19 HSA anchors are loaded from `INF_footprint_hsas_v2.geojson`.
- 188 facilities are allocated.
- Case 2 has a stricter fallback guard:
  - maximum absolute fallback: 100 km
  - radius multiplier: 1.5
  - minimum allowance: 30 km
  - major-population threshold: 25,000
- One facility is reported as excluded because it lacks an admissible fallback:
  - `Swaqa Correctional Primary`, 4,543 people
  - nearest anchor: `Faqqou Comprehensive Center`
  - distance: 35.7 km

That exclusion is intentional. It flags a residual edge case rather than forcing a questionable assignment.

## 7. Implementation Safeguard: Metric Distance Calculations

During debugging, one important implementation issue was found: some distance comparisons were being made in a geographic CRS, which can make distances look like tiny degree values rather than kilometers.

The new upgrade and promotion helpers explicitly reproject to:

`EPSG:32637`

before computing distances. This is necessary for southern Jordan decisions such as Maan and Queen Rania, where a mistaken degree/kilometer comparison can prevent major-orphan promotion.

This CRS fix is not a conceptual change to the algorithm, but it is essential for the algorithm to behave as described.

## 8. Resulting Current Anchor Sets

Current v7 output files show the following anchor counts:

| Mode | Current anchors | Notes |
|---|---:|---|
| INF-FEWEST | 18 | Includes Maan Hospital, Princess Salma Hospital, Queen Rania Hospital as promoted major orphans. |
| INF-FOOTPRINT | 19 | Includes Maan Hospital and Queen Rania Hospital as promoted major orphans. |
| INF-DISTANCE | 21 | Requires many anchor upgrades but no additional major-orphan promotion. |

Current INF-FOOTPRINT anchors:

1. Al-Basheer Hospital
2. Al Hussain New Salt Hospital
3. AL-Zarqa Hospital
4. Dr. Jamel Al-Totanji Hospital
5. AL-Ramtha Hospital
6. AL-Shuneh Hospital
7. Jarash Hospital
8. Princess Raya Hospital
9. Al-Karak Hospital
10. Al-Mafraq Gynecology and Pediatrics Hospital
11. Aqaba Comprehensive Center
12. AL-Nadeem Hospital
13. Mabroukeh Primary Center
14. Al-Iman Hospital
15. Tafilah Governmental Hospital
16. Princess Basma Comprehensive Clinic
17. Faqqou Comprehensive Center
18. Maan Hospital
19. Queen Rania Hospital

Compared with the manuscript's older INF-FOOTPRINT result, this current output should be described as a revised algorithmic version because the anchor count and several anchor identities have changed.

## 9. Why This Is a Post-Greedy Correction

The user question that motivated this change was whether this is a known problem with greedy algorithms. Yes: this is a classic limitation.

Greedy selection optimizes the next local gain. It does not naturally perform:

- exchange moves;
- anchor swaps;
- dominance checks;
- facility hierarchy checks;
- retrospective face-validity corrections;
- constraints on downstream fallback plausibility.

In this application, the objective is not purely mathematical coverage. The selected anchors must also be defensible health-system aggregation units. A small facility can be a valid coverage contributor, but still be a poor HSA anchor when a much larger hospital lies in the same local service area.

There are two general ways to handle this:

1. Add more constraints inside the greedy algorithm.
2. Keep the greedy algorithm simple and add deterministic post-selection correction.

The v7 implementation uses the second approach. It is easier to audit, easier to explain, and preserves comparability with the original manuscript algorithm.

If this were to become a fully integrated optimization problem, the upgrade and promotion logic could be folded into the greedy score or expressed as hard constraints:

- do not select a lower-tier anchor if a same-governorate higher-tier facility within the same catchment dominates it;
- require every major hospital to be either covered by a same-governorate anchor or selected as an anchor;
- penalize selected anchor sets that would force major-facility fallback beyond the admissible distance.

For the current workflow, the explicit audit tables are preferable because they show exactly which anchors were changed and why.

## 10. Manuscript Text That Would Need Revision

If the paper is updated to reflect v7, the following manuscript sections should be revised:

### Section 2.3: Multi-Objective Weighted Scoring Optimization Algorithm

The greedy algorithm description should add a post-selection anchor quality-control step:

- weak selected anchors are compared with stronger nearby facilities;
- replacements are allowed only within the local service radius;
- replacements are constrained to the same governorate where possible;
- service radius and optimization metadata are preserved.

### Figure 2 / Algorithm Box

The algorithm box should add two steps after the greedy loop:

1. `Upgrade weak selected anchors to stronger nearby facilities`.
2. `Promote major uncovered facilities lacking plausible fallback`.

### Section 2.4: Patient Allocation

The Case 2 rule should be changed from:

`If a facility falls outside all HSA radii, it is reassigned to the nearest HSA anchor.`

to:

`If a facility falls outside all HSA radii, it is assigned to the nearest admissible HSA anchor, where admissibility is limited by distance, service radius, and for major facilities governorate consistency. Facilities without an admissible fallback are excluded from allocation and reported for possible anchor promotion.`

### Results: Optimized HSA Networks

The reported INF-FOOTPRINT anchor count and anchor names should be updated if v7 becomes the manuscript version. The current v7 INF-FOOTPRINT output has 19 anchors and includes:

- `Maan Hospital`
- `Queen Rania Hospital`
- `Tafilah Governmental Hospital`

It no longer treats `Bsaira Comprehensive Center` as the HSA anchor.

### Results: Population Allocation

The allocation results should be rerun and reported under the v2 fallback rules. The older statement that all outside facilities are assigned to the nearest anchor is no longer accurate for the revised method.

## 11. Suggested Revised Algorithm Box

```text
Algorithm: Greedy HSA Selection with Anchor Quality Control

Inputs:
  Facilities F with locations, facility types, governorates, and volumes
  Population grid P
  Optimization mode and coverage target

Precompute:
  For each facility f:
    Estimate local population density
    Assign urban/rural base radius
    Apply volume-based radius adjustment
    Store final service radius r_f

Greedy selection:
  S = empty set
  While covered population < target:
    For each unselected facility f:
      compute multi-objective score:
        coverage gain
        volume
        climate/geographic diversity
        progress toward coverage target
        overlap penalty
        distance/access penalty
    Select facility with highest positive score
    Add it to S
    Update covered population

Anchor upgrade:
  For each selected anchor s in S:
    Search unselected facilities within s service radius
    Keep same-governorate candidates when available
    If a candidate is larger and stronger by type or volume:
      replace s as anchor
      keep s as a normal facility
      preserve s service radius and optimization metadata

Major-orphan promotion:
  For each non-selected facility f:
    If f is major and outside all selected service radii:
      Find nearest selected anchor
      Compute fallback limit:
        min(100 km, max(1.5 * nearest radius, 30 km))
      If fallback is not plausible:
        add f to S as a forced anchor

Return:
  Final anchor set S
  Anchor upgrade audit
  Major-orphan promotion audit
```

## 12. Bottom Line

The modified algorithm should be described as:

> The original greedy HSA optimizer with deterministic anchor-quality guardrails and constrained fallback allocation.

The substantive change is not that the optimizer has a different objective. The change is that selected anchors must now pass a face-validity check against stronger nearby facilities, and major uncovered hospitals can no longer be hidden inside distant nearest-anchor fallbacks.

For the motivating example, the revised algorithm behaves as desired:

- `Bsaira Comprehensive Center` is demoted from anchor status.
- `Tafilah Governmental Hospital` becomes the local Tafilah anchor.
- `Maan Hospital` and `Queen Rania Hospital` are promoted as southern anchors because their fallback to Tafilah is too distant and cross-governorate.

