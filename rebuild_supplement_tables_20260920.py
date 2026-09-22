#!/usr/bin/env python3
"""Reconcile the tracked supplement against the 20 Sep 2026 output snapshot.

Existing tracked changes are preserved. New table and prose replacements are
attributed to Ilya Zaslavsky; map images are removed for author replacement.
"""

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import rasterio
from lxml import etree
from pyproj import Transformer
from rasterio.mask import mask
from shapely import wkt
from shapely.geometry import shape
from shapely.ops import transform, unary_union
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "HSA_paper" / "resubmission_091926"
SOURCE = OUT / "2026GH001924_Supporting_Information_Tracked_Changes_iz0920.docx"
DEST = OUT / "2026GH001924_Supporting_Information_Tables_Tracked_2026-09-20.docx"
MANIFEST = OUT / "2026GH001924_Supplement_Table_Snapshot_2026-09-20.json"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
FILES = {}
EDITS = {}
NOTES = []
PROSE = {
    "Service radii are initialized from local population density":
        "Service radii start from urban and rural defaults of 10 km and 18 km, using a local population-density threshold of 1,500 people/km². They are then scaled by each facility’s patient-volume percentile before the optimization begins.",
    "Step 2 aggregates facility-level assigned populations":
        "Step 2 brings facility-level allocations into the selected HSAs. A facility within one service radius contributes to that HSA; a facility within overlapping radii is split among the containing HSAs using the gravity weights. A facility outside all radii can be assigned to the nearest eligible anchor, subject to a distance guard. Population beyond the allocation range, and facilities that fail the fallback guard, are not assigned to a final HSA denominator.",
    "We used\u00a0jor_ppp_2020_constrained.tif":
        "For the inhabited-area polygons used in maps and climate extraction, we used the WorldPop 2020 constrained raster; optimization and population allocation used the UN-adjusted raster. The constrained surface identifies settled cells. We coarsened it to an effective 200 m grid with maximum pooling, removed isolated patches smaller than 0.5 km², closed small gaps, and simplified the boundaries at 250 m. These steps change the displayed and extracted footprint, not the service-radius circles used for optimization.",
    "All models used temporally ordered train/validation/test splits":
        "Weekly predictive models used temporally ordered train, validation, and test sets. We compared regularized linear and tree-based models with autoregressive and seasonal baselines. The added value of climate variables was assessed from the change in held-out R², with RMSE and MAE as complementary measures. The separate daily analysis addresses exposure–disease associations rather than forecast performance.",
    "HSA polygons are stored as service-radius circles":
        "HSA polygons are stored both as service-radius circles, used for the spatial comparison, and as inhabited-area patches, used for maps and climate extraction. In the INF network, mean inhabited area was 135 km², compared with 728 km² for the circles.",
    "Adding climate feature groups to temporal baselines did not improve":
        "Several individual climate variables produced small gains when added to the autoregressive baseline, but the gains were uneven and did not displace the importance of recent case counts. Table S2.5.2 shows the individual-variable comparisons.",
    "All three feature sets reduced test performance relative to the AR+Seasonal baseline":
        "In this broader feature-set comparison, all three climate sets performed worse than the autoregressive and seasonal baseline (test R² = 0.856), with the largest decline for the combined means-and-extremes set. That result describes this particular specification; the smaller parsimonious model showed a modest gain, and neither result settles whether weather is associated with disease at the daily scale.",
    "Linear and tree-based model families produced the same qualitative conclusion":
        "The parsimonious linear and tree-based models achieved similar test performance (Table S2.5.5). Across them, recent case counts supplied most of the predictive information, while the contribution of the added climate variables was modest and model-dependent.",
    "Variance decomposition confirms that climate terms don’t add explanatory value":
        "The NCD models likewise show little and inconsistent added predictive value from climate variables once recent counts and seasonal structure are included. The parsimonious model gains slightly, whereas several broader specifications lose test performance (Tables S3.5.3a–b).",
    "We tested α ∈ {0.5, 0.75, 1.0, 1.25}":
        "We tested α ∈ {0.5, 0.75, 1.0, 1.25} and β ∈ {1.0, 1.5, 2.0, 2.5}. Allocation concentration and the number of facilities receiving population changed across this grid (Table S4.1). The repeated disease-model R² values are a shared reference and noise check, not a model refit for each gravity setting; this table therefore tests allocation sensitivity, not downstream predictive robustness.",
    "Each perturbation re-runs the complete delineation":
        "We reran the delineation after each one-at-a-time change in an optimization weight. All 21 INF runs selected the same 18 anchors (Table S4.2). NCD was slightly more sensitive: three of 21 settings added a nineteenth anchor, while the others reproduced the 18-anchor baseline. Thus modest weight changes left the INF solution unchanged and only occasionally changed the NCD solution.",
    "Variance decomposition separates climate variation within service areas":
        "SRTM provides elevation summaries for each HSA. The elevation ICC was 0.90 for INF and 0.85 for NCD, indicating that most of the terrain variation in this calculation lay between HSAs. The temperature ICCs (0.72 and 0.75) come instead from a modeled latitude/lapse-rate surface built with estimated pixel elevations; they are not observed within-HSA ERA5 temperature variation or SRTM-downscaled temperature. Because the SRTM summaries cover whole HSA polygons and the temperature estimates use allocated pixels, these are descriptive contrasts rather than an exact variance partition on a common set of cells (Table S4.5).",
    "Most population is assigned with weak-to-moderate allocation probability":
        "Most allocated population falls in the moderate or weak assignment-probability tiers (Table S6.1). Probability is a measure of how decisively the gravity model favors a facility for a pixel; it should not be read as a direct measure of distance or urbanicity.",
    "Coverage diagnostics indicate that climate-model inference applies":
        "As an exploratory predictive check, we split the 18 HSAs by the population-weighted mean probability of each pixel’s top-choice facility. We then tested whether adding weekly temperature and rainfall to an autoregressive and seasonal model changed held-out fit in each half. The gain was modest in the higher-certainty half and negligible in the lower-certainty half (Table S6.2). This top-choice measure is not road access or urbanicity, and the comparison does not address daily exposure–disease associations.",
    "Allocated populations are concentrated within and near service radii":
        "Most population was assigned to a final HSA. The small remainder includes pixels beyond the allocation range and a facility that did not meet the outside-radius fallback rule. This limited remainder reduces one concern about coverage, but it does not by itself rule out selection bias in climate analyses.",
    "All maps show service areas as both full service-radius circles":
        "The map panels have been omitted from this working copy for replacement. The captions below retain the current HSA counts. The revised panels should show both the full service-radius circles and their inhabited portions.",
}


def source(path):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if str(path) not in FILES:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        FILES[str(path)] = {"sha256": digest.hexdigest(), "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    return path


def csv(path):
    return pd.read_csv(source(path))


def js(path):
    return json.loads(source(path).read_text())


def setc(table, row, col, value):
    EDITS[(table, row, col)] = str(value)


def nfmt(value):
    return f"{value:,.0f}"


def pct(value, digits=1):
    return f"{value:.{digits}f}%"


def r4(value):
    return f"{value:.4f}"


def signed(value, digits=4):
    return f"{value:+.{digits}f}"


def scenario_tables(network, table):
    modes = ["fewest", "footprint", "distance", "governorate_tau_coverage", "governorate_fewest"]
    # Independently evaluate all five final circle unions against one raster
    # and denominator. The GeoJSON geometry itself is the inhabited patch,
    # whereas the table's population coverage concerns service-radius circles.
    raster_path = source(ROOT / 'data' / 'jor_ppp_2020_UNadj.tif')
    with rasterio.open(raster_path) as src:
        total = float(np.maximum(src.read(1).astype(np.float64), 0).sum())
        for i, mode in enumerate(modes, 1):
            feat = js(ROOT / "out" / f"{network}_{mode}_hsas_v7.geojson")["features"]  # noqa: hardcode - reads the canonical delineation masters
            radii = [f["properties"]["service_radius_km"] for f in feat]
            circles = [wkt.loads(f['properties']['circle_geometry_wkt']) for f in feat]
            covered, _ = mask(src, [unary_union(circles)], crop=True, nodata=0)
            coverage = 100 * float(np.maximum(covered[0].astype(np.float64), 0).sum()) / total
            setc(table, i, 1, len(feat))
            setc(table, i, 2, pct(coverage))
            setc(table, i, 3, f"{np.mean(radii):.1f} km")
            setc(table, i, 4, f"{max(radii):.1f} km")
    NOTES.append(f"{network}: all five coverage percentages were recomputed from final service-circle WKT on the same 2020 UN-adjusted WorldPop raster and national denominator. At one decimal place they reproduce the previous table values.")


def spatial_methods(network, table):
    d = csv(ROOT / f"out_{network}_footprint_v7" / f"{network}_footprint_spatial_methods_comparison.csv")
    if len(d) != 7:
        raise ValueError("Unexpected spatial method rows")
    for i, (_, r) in enumerate(d.iterrows(), 1):
        setc(table, i, 0, r.method.replace(" (all)", ""))
        setc(table, i, 1, int(r.n_units))
        setc(table, i, 2, pct(r.coverage_pct))
        setc(table, i, 3, pct(r.overlap_pct, 1 if r.overlap_pct >= 1 else 3))
        setc(table, i, 4, f"{r.coverage_multiplier:.2f}×")
        setc(table, i, 5, f"{r.mean_compactness:.3f}")
        setc(table, i, 6, pct(r.concordance_pct))


def allocation(network, table):
    p = ROOT / f"out_{network}_footprint_v7"
    d = csv(p / f"{network}_footprint_hsa_populations_probabilistic_v7.csv")
    d = d.sort_values("allocated_patients", ascending=False).reset_index(drop=True)
    if len(d) != 18:
        raise ValueError(f"Expected 18 {network} allocations")
    total = d.allocated_patients.sum()
    facility_count = int(d.num_facilities_in_hsa.sum())
    for i, r in d.iterrows():
        row = i + 1
        for col, value in enumerate((row, r.anchor_name, nfmt(r.allocated_patients), int(r.num_facilities_in_hsa), pct(100 * r.allocated_patients / total))):
            setc(table, row, col, value)
    total_row = 19 if network == "INF" else 19
    for col, value in enumerate(("—", "TOTAL ASSIGNED TO FINAL HSAs", nfmt(total), facility_count, pct(100 * total / 10203129))):
        setc(table, total_row, col, value)
    for col, value in enumerate(("—", "NOT ASSIGNED TO FINAL HSAs", nfmt(10203129 - total), "—", pct(100 * (10203129 - total) / 10203129))):
        setc(table, total_row + 1, col, value)
    for col, value in enumerate(("—", "NATIONAL POPULATION (source denominator)", "10,203,129", "—", "100.0%")):
        setc(table, total_row + 2, col, value)
    if network == "INF":
        NOTES.append("INF allocation table loses one obsolete anchor row (19 to 18) while preserving the three summary rows.")
    NOTES.append(f"{network}: population not assigned to a final HSA includes excluded facilities as well as pixels beyond the allocation range; the former >100-km label was inaccurate.")


def assignment(network, table):
    d = csv(ROOT / f"out_{network}_footprint_v7" / f"{network}_footprint_facility_hsa_assignments_v7.csv")
    kinds = ["Case 1: Inside 1 HSA", "Case 2: Outside all HSAs", "Case 3: Inside 2+ HSAs"]
    # Match by case number, because descriptive suffixes have changed.
    for i in range(1, 4):
        part = d[d.assignment_case.astype(str).str.startswith(f"Case {i}:")]
        setc(table, i, 0, ["Within one service area", "Outside all service areas; nearest eligible anchor", "Within overlapping service areas"][i-1])
        setc(table, i, 1, len(part))
        setc(table, i, 2, pct(100 * len(part) / len(d)))
        setc(table, i, 3, ", ".join(part.facility_id.head(2)))
    excluded = d[d.excluded.astype(bool)]
    setc(table, 4, 0, "Excluded: exceeds allowed fallback distance")
    setc(table, 4, 1, len(excluded))
    setc(table, 4, 2, pct(100 * len(excluded) / len(d)))
    setc(table, 4, 3, ", ".join(excluded.facility_id))
    setc(table, 5, 1, len(d))
    setc(table, 5, 2, "100.0%")


def model_tables(network, offset):
    stem = f"{network}_footprint"
    base = ROOT / f"out_{network}_footprint_v7" / "modeling"
    comprehensive = csv(base / "results_comprehensive_v7" / f"{stem}_all_model_results.csv")
    pars = csv(base / "results_parsimonious_v7" / f"{stem}_parsimonious_model_results.csv")
    ar = csv(base / "results_parsimonious_v7" / f"{stem}_ar_lag_analysis.csv")
    thematic = csv(base / "results_parsimonious_v7" / f"{stem}_thematic_group_analysis.csv")
    summary = js(base / "results_parsimonious_v7" / f"{stem}_summary.json")
    # Baseline table (tables 6/21)
    baseline = comprehensive[(comprehensive.feature_set == "baseline") & (comprehensive.split == "test")]
    for row, model in enumerate(("mean_baseline", "seasonal_mean", "last_week"), 1):
        r = baseline.loc[baseline.model == model].iloc[0]
        setc(6 + offset, row, 1, f"{r.r2:.3f}")
        setc(6 + offset, row, 2, f"{r.rmse:.2f}")
    # AR lag table (7/22)
    for row, label in enumerate(("ar_lag1", "ar_lag2", "ar_lag1-2"), 1):
        value = ar.loc[ar.features == label, "test_r2"].iloc[0]
        setc(7 + offset, row, 1, r4(value))
    # Thematic single-feature screen (8/23): use each displayed variable, not a reselected one.
    thematic_rows = {"INF": [("baseline", "ar_lag1 + ar_lag2"), ("seasonal", "cos_week"),
                              ("temperature_max", "T_max_week_C"), ("temperature_mean", "T_mean_week_C"),
                              ("water_balance", "water_deficit_mm_week"), ("evaporation", "E_week_mm_per_day"),
                              ("heat_stress", "hours_above_30C_week"), ("humidity", "Td_d-2_C"),
                              ("soil_moisture", "SM1_week"), ("precip_daily", "P_d-3"),
                              ("precip_weekly", "P_sum_lag_w-1")],
                     "NCD": [("baseline", "ar_lag1 + ar_lag2"), ("humidity", "Td_d-7_C"),
                              ("evaporation", "E_d-2_mm_per_day"), ("precip_weekly", "P_total_week"),
                              ("heat_stress", "hours_above_30C_d-3"), ("temperature_max", "T_max_d-5_C"),
                              ("water_balance", "water_deficit_mm_week"), ("temperature_mean", "T_mean_d-14_C"),
                              ("seasonal", "sin_week"), ("precip_daily", "P_d-5")]}[network]
    for row, (_, variable) in enumerate(thematic_rows, 1):
        match = thematic.loc[thematic.variable == variable]
        if match.empty:
            NOTES.append(f"{network} thematic variable {variable} not found; table row retained")
            continue
        value = match.iloc[0]
        setc(8 + offset, row, 2, r4(value.test_r2))
        setc(8 + offset, row, 3, "—" if row == 1 else signed(value.improvement_over_baseline))
    # Component table (9/24) is recomputed because extended_interpretation.json
    # overwrites its AR/season values in a later model loop.
    clims = ["T_max_week_C", "T_mean_week_C"] if network == "INF" else ["Td_d-7_C", "E_d-2_mm_per_day"]
    chosen = "elasticnet" if network == "INF" else "ridge"
    split = {k: csv(base / "results_comprehensive_v7" / f"{stem}_{k}_data.csv") for k in ("train", "test")}
    outcome = [c for c in split["train"] if c.endswith("_count_adjusted")][0]
    for frame in split.values():
        frame["sin_week"] = np.sin(2 * np.pi * frame.week_of_year / 52)
        frame["cos_week"] = np.cos(2 * np.pi * frame.week_of_year / 52)
    sets = [["ar_lag1", "ar_lag2"], ["ar_lag1", "ar_lag2", "sin_week", "cos_week"],
            ["ar_lag1", "ar_lag2", "sin_week", "cos_week"] + clims]
    scores = []
    for features in sets:
        scaler = StandardScaler()
        xtrain = scaler.fit_transform(split["train"][features])
        xtest = scaler.transform(split["test"][features])
        model = ElasticNet(alpha=.1, l1_ratio=.5, max_iter=10000, random_state=42) if chosen == "elasticnet" else Ridge(alpha=1.0, random_state=42)
        model.fit(xtrain, split["train"][outcome])
        scores.append(float(r2_score(split["test"][outcome], model.predict(xtest))))
    if abs(scores[-1] - summary["test_r2"]) > 1e-8:
        raise ValueError(f"{network}: component recomputation did not reproduce published parsimonious test score")
    for row, score in enumerate(scores, 1):
        setc(9 + offset, row, 2, r4(score))
        setc(9 + offset, row, 3, "—" if row == 1 else signed(score - scores[row - 2]))
    # Comprehensive comparison (10/25), fixed feature definitions.
    for row, model in enumerate(("ridge", "elasticnet", "random_forest", "gradient_boosting"), 1):
        a = comprehensive[(comprehensive.model == model) & (comprehensive.split == "test")]
        prior = float(a.loc[a.feature_set == "ar_temporal", "r2"].iloc[0])
        full = float(a.loc[a.feature_set == "ar_climate_temporal_hsa", "r2"].iloc[0])
        for col, value in enumerate((r4(prior), r4(full), signed(full-prior), f"{100*(full-prior)/prior:+.1f}%"), 1):
            setc(10 + offset, row, col, value)
    # Parsimonious model-family performance (12/27).
    for row in range(1, 6):
        model = ["elasticnet", "ridge", "lasso", "random_forest", "gradient_boosting"][row-1] if network == "INF" else ["ridge", "lasso", "elasticnet", "random_forest", "gradient_boosting"][row-1]
        bysplit = pars.loc[pars.model == model].set_index("split")["r2"]
        for col, value in enumerate((bysplit["train"], bysplit["val"], bysplit["test"], bysplit["train"]-bysplit["test"]), 1):
            setc(12 + offset, row, col, f"{value:.3f}")
    # Mean-versus-extreme climate table (11/26) uses its own four-feature
    # AR+annual baseline; it must not be interchanged with comprehensive-model R².
    extreme = js(ROOT / f"out_{network}_footprint_v7" / "sensitivity" / "analysis_extreme_events_v7" / network / f"{stem}_analysis_summary.json")
    specs = {r["specification"]: r for r in extreme["model_comparison"]}
    for row, spec in enumerate(("B_AR_Seasonal_Means", "C_AR_Seasonal_Extremes", "D_AR_Seasonal_Both"), 1):
        r = specs[spec]
        setc(11 + offset, row, 1, r["n_features"] - 4)
        setc(11 + offset, row, 2, f"{100*r['contribution_over_baseline']:+.2f} pp")
    # Parsimonious feature importance (13/28) is normalized within model.
    imp = csv(base / "results_parsimonious_v7" / f"{stem}_feature_importance.csv")
    categories = {"INF": {"AR terms (lags 1-2)": ["ar_lag1", "ar_lag2"],
                          "Seasonal (Fourier)": ["sin_week", "cos_week"],
                          "Temperature": ["T_max_week_C", "T_mean_week_C"],
                          "Precipitation": [], "Humidity": [], "Soil moisture": []},
                  "NCD": {"AR terms (lags 1-2)": ["ar_lag1", "ar_lag2"],
                          "Seasonal (Fourier)": ["sin_week", "cos_week"],
                          "Humidity": ["Td_d-7_C"], "Evapotranspiration": ["E_d-2_mm_per_day"],
                          "Temperature": []}}[network]
    for row, features in enumerate(categories.values(), 1):
        for col, model in enumerate(("elasticnet", "ridge", "random_forest", "gradient_boosting"), 1):
            value = imp[(imp.model == model) & (imp.feature.isin(features))].importance.sum() * 100
            setc(13 + offset, row, col, f"{value:.1f}")
    # Anomaly model table (14/29): retain model labels and copy the same scenario's output.
    anomalies = csv(base / "results_anomalies_v7" / f"{stem}_anomaly_model_comparison.csv")
    for row, feature_set in enumerate(("ar_anomaly", "climate_anomaly", "ar_climate_anomaly"), 1):
        subset = anomalies.loc[anomalies.feature_set == feature_set]
        if not subset.empty:
            score = subset.loc[subset.model == "ridge", "test_r2"]
            if not score.empty:
                setc(14 + offset, row, 1, r4(score.iloc[0]))
    if network == "INF":
        for row, mode in ((1, "footprint"), (2, "fewest")):
            d = csv(ROOT / f"out_INF_{mode}_v7" / "modeling" / "results_comprehensive_v7" / f"INF_{mode}_all_model_results.csv")
            test = d[(d.split == "test") & (d.model == "ridge")].set_index("feature_set")["r2"]
            prev = float(test["ar_temporal"]); full = float(test["ar_climate_temporal_hsa"])
            setc(15, row, 1, 18)
            setc(15, row, 2, r4(prev)); setc(15, row, 3, r4(full)); setc(15, row, 4, signed(full-prev))
        setc(15, 1, 5, "Small positive gain in this comparison")
        setc(15, 2, 5, "Gain also seen without climate-diversity selection")


def diagnostics():
    for network, table in (("INF", 33), ("NCD", 37)):
        p = ROOT / f"out_{network}_footprint_v7" / "sensitivity" / "analysis_spatial_autocorrelation_v7" / network / f"{network}_footprint_spatial_autocorrelation_results.json"
        d = js(p)
        rows = d["aggregate_morans"]
        vals = [rows["inverse_distance"], rows["k_nearest"]]
        for row, v in enumerate(vals, 1):
            for col, key in enumerate(("I", "EI", "VI", "z_score", "p_value_normal"), 1):
                setc(table, row, col, f"{v[key]:.4f}")
            setc(table, row, 6, "Not significant at 0.05" if v["p_value_normal"] >= .05 else "Significant at 0.05")


def exclusions():
    d = js(ROOT / "out_INF_footprint_v7" / "sensitivity" / "analysis_exclusion_v7" / "INF_footprint_exclusion_summary.json")
    for row, key in enumerate(("strong", "moderate", "weak", "very_weak"), 1):
        r = d["by_probability_class"][key]
        setc(38, row, 2, nfmt(r["population"]))
        setc(38, row, 3, pct(r["population_pct"]))
    # The source percentages describe all probabilistically allocated pixels,
    # including the later-excluded facility, not just final HSA populations.
    NOTES.append("S6.1 probability tiers use 10,179,256 allocated-pixel population, including the subsequently excluded facility; this differs from the final-HSA allocation denominator.")


def sensitivity_tables():
    root = ROOT / "out_INF_footprint_v7" / "sensitivity" / "analysis_gravity_sensitivity_v7" / "INF"
    gravity = csv(root / "INF_footprint_sensitivity_results.csv")
    summary = js(root / "INF_footprint_sensitivity_analysis_summary.json")
    base_r2 = summary["baseline_performance"]["r2"]
    noise20 = next(r["mean_r2"] for r in summary["robustness_metrics"] if r["noise_level"] == .2)
    if len(gravity) != 16:
        raise ValueError("Expected 16 gravity settings")
    setc(30, 0, 2, "HHI")
    setc(30, 0, 6, "Model R²")
    setc(30, 0, 7, "R² (20% noise)")
    for row, (_, r) in enumerate(gravity.iterrows(), 1):
        vals = (f"{r.alpha:.2f}", f"{r.beta:.1f}", f"{r.concentration:.3f}",
                f"{r.gini:.3f}", pct(100*r.max_share), int(r.n_facilities_used),
                f"{base_r2:.3f}", f"{noise20:.3f}")
        for col, value in enumerate(vals):
            setc(30, row, col, value)
    NOTES.append("S4.1 gravity settings change allocation concentration and Gini. The disease-model R² values are a shared reference/noise check, not a refit for each alpha/beta setting; table headers now say so.")
    weight = csv(ROOT / "out_INF_footprint_v7" / "weight_sensitivity_reoptimized_v7" / "INF_footprint_weight_sensitivity_reoptimized.csv")
    if len(weight) != 21:
        raise ValueError("Expected 21 weight-sensitivity settings")
    for row, (_, r) in enumerate(weight.iterrows(), 1):
        setc(31, row, 2, int(r.n_anchors))
        setc(31, row, 3, f"{r.temp_diversity:.4f}")
        setc(31, row, 4, "No anchor-set change" if r.anchor_set_hash == weight.anchor_set_hash.iloc[0] else "Anchor set changed")
    # Recount delineations independently from the 90% and 95% GeoJSONs.
    for network, first in (("INF", 1), ("NCD", 6)):
        for offset, mode in enumerate(("fewest", "footprint", "distance", "governorate_tau_coverage", "governorate_fewest")):
            count90 = len(js(ROOT / "out" / f"{network}_{mode}_hsas_v7.geojson")["features"])  # noqa: hardcode - reads the canonical delineation masters
            count95 = len(js(ROOT / f"out_{network}_cov95" / f"{network}_{mode}_hsas_v7.geojson")["features"])
            setc(32, first + offset, 0, network)
            setc(32, first + offset, 1, mode.upper())
            setc(32, first + offset, 2, count90)
            setc(32, first + offset, 3, f"{count95} ({count95-count90:+d})")
    h = js(ROOT / "out_INF_footprint_v7" / "sensitivity" / "analysis_climate_heterogeneity_v7" / "INF" / "INF_footprint_heterogeneity_analysis.json")
    for row, key in enumerate(("temperature", "elevation"), 1):
        d = h["variance_decomposition"][key]
        if key == "temperature":
            vals = [f"{d['within_variance']:.3f}", f"{d['between_variance']:.3f}", f"{d['total_variance']:.3f}", f"{d['icc']:.3f}"]
        else:
            vals = [nfmt(d['within_variance']), nfmt(d['between_variance']), nfmt(d['total_variance']), f"{d['icc']:.3f}"]
        for col, value in enumerate(vals, 1):
            setc(34, row, col, value)
    stats = csv(ROOT / "out_INF_footprint_v7" / "sensitivity" / "analysis_climate_heterogeneity_v7" / "INF" / "INF_footprint_within_hsa_statistics.csv")
    if len(stats) != 18 or not stats.elev_source.eq("SRTM").all():
        raise ValueError("S4.5 elevation statistics are not SRTM for all HSAs")
    NOTES.append("S4.5 elevation variance uses real SRTM zonal statistics for all 18 HSAs. Temperature variance remains based on estimated per-allocation-pixel temperature from modeled elevation/latitude; it is not observed SRTM-derived temperature.")


def area_and_comparison():
    coverage = {}
    mean_area = {}
    inhabited = {}
    radius = {}
    residual_i = {}; residual_p = {}
    for network in ("INF", "NCD"):
        root = ROOT / f"out_{network}_footprint_v7"
        stem = f"{network}_footprint"
        methods = csv(root / f"{stem}_spatial_methods_comparison.csv")
        optimized = methods.loc[methods.method == "Optimized HSA"].iloc[0]
        coverage[network] = float(optimized.coverage_pct)
        mean_area[network] = float(optimized.mean_area_km2)
        geo = js(root / f"{stem}_hsas_v7.geojson")["features"]
        projection = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True).transform
        inhabited[network] = float(np.mean([transform(projection, shape(f["geometry"])).area / 1e6 for f in geo]))
        radius[network] = float(np.mean([f["properties"]["service_radius_km"] for f in geo]))
        moran = js(root / "sensitivity" / "analysis_spatial_autocorrelation_v7" / network / f"{stem}_spatial_autocorrelation_results.json")
        residual_i[network] = moran["aggregate_morans"]["inverse_distance"]["I"]
        residual_p[network] = moran["aggregate_morans"]["inverse_distance"]["p_value_normal"]
    # S4.6, INF row of the spatial-unit table.
    unit = csv(ROOT / "out_INF_footprint_v7" / "sensitivity" / "analysis_spatial_comparison_v7" / "INF" / "INF_footprint_spatial_unit_summary.csv")
    row = unit.loc[unit["Spatial Unit"] == "HSA (FOOTPRINT)"].iloc[0]
    setc(35, 1, 0, "Optimized HSAs (N=18)")
    for col, value in enumerate((row.Ridge, row.ElasticNet, row.RandomForest), 1):
        setc(35, 1, col, f"{value:.3f}")
    setc(35, 1, 4, nfmt(mean_area["INF"]))
    setc(35, 1, 5, nfmt(inhabited["INF"]))
    # S5.1 cross-network summary.
    vals = [(18, 18), (pct(coverage["INF"]), pct(coverage["NCD"])),
            (f"{radius['INF']:.1f} km", f"{radius['NCD']:.1f} km"),
            (f"{mean_area['INF']:.1f} km²", f"{mean_area['NCD']:.1f} km²"),
            (f"{inhabited['INF']:.1f} km²", f"{inhabited['NCD']:.1f} km²")]
    for row, (inf, ncd) in enumerate(vals, 1):
        setc(36, row, 1, inf); setc(36, row, 2, ncd)
    baseline = {}; delta = {}
    for network in ("INF", "NCD"):
        d = csv(ROOT / f"out_{network}_footprint_v7" / "modeling" / "results_comprehensive_v7" / f"{network}_footprint_all_model_results.csv")
        test = d[(d.model == "ridge") & (d.split == "test")].set_index("feature_set")["r2"]
        baseline[network] = float(test["ar_temporal"])
        delta[network] = float(test["ar_climate_temporal_hsa"] - test["ar_temporal"])
    for row, values in ((6, (r4(baseline['INF']), r4(baseline['NCD']))),
                        (7, (signed(delta['INF']), signed(delta['NCD']))),
                        (8, (r4(residual_i['INF']), r4(residual_i['NCD']))),
                        (9, (r4(residual_p['INF']), r4(residual_p['NCD'])))):
        setc(36, row, 1, values[0]); setc(36, row, 2, values[1])
    setc(36, 7, 3, "Ridge comparison; direction differs by network")
    setc(36, 8, 3, "Neither inverse-distance Moran statistic is significant")
    NOTES.append("S5.1 baseline and climate increment use comprehensive Ridge AR+temporal versus AR+climate+temporal+HSA, matched within each network. Residual Moran's I is from the separate spatial-diagnostic model, not necessarily the Ridge comparison.")


def connectivity():
    d = js(OUT / "table_rebuild_2026-09-20" / "INF_footprint_connectivity_results.json")
    source(OUT / "table_rebuild_2026-09-20" / "INF_footprint_connectivity_results.json")
    setc(39, 0, 0, "Certainty")
    setc(39, 0, 1, "Test HSA-weeks")
    setc(39, 0, 2, "Base R²")
    setc(39, 0, 3, "+ climate R²")
    setc(39, 0, 4, "ΔR² (pp)")
    setc(39, 0, 5, "Relative Δ")
    for row, r in enumerate(d["rows"], 1):
        setc(39, row, 0, f"{'Higher' if r['group'] == 'higher_certainty' else 'Lower'} ({r['n_hsas']} HSAs)")
        setc(39, row, 1, r['n_test'])
        setc(39, row, 2, r4(r["ar_seasonal_test_r2"]))
        setc(39, row, 3, r4(r["ar_seasonal_climate_test_r2"]))
        setc(39, row, 4, f"{100*r['climate_delta_r2']:+.2f}")
        setc(39, row, 5, f"{100*r['climate_delta_r2']/r['ar_seasonal_test_r2']:+.2f}%")
    NOTES.append("S6.2 group labels mean allocation certainty, not physical connectivity or urban/rural status. The comparison uses 9 final HSAs per group, 90 test HSA-weeks each, weekly mean temperature and total precipitation as climate predictors.")


def effective_text(cell):
    return "".join(x.text or "" for x in cell.xpath('.//w:t[not(ancestor::w:del)]', namespaces=NS))


def original_text(element):
    """Text recovered by rejecting the source document's existing revisions."""
    return "".join(x.text or "" for x in element.xpath(
        './/w:t[not(ancestor::w:ins)] | .//w:delText', namespaces=NS))


def redline_cell(cell, new, revision_id):
    if effective_text(cell) == new:
        return revision_id, False
    old = original_text(cell)
    paras = cell.xpath('./w:p', namespaces=NS)
    first_ppr = copy.deepcopy(paras[0].find(f'{{{W}}}pPr')) if paras and paras[0].find(f'{{{W}}}pPr') is not None else None
    for child in list(cell):
        if child.tag != f'{{{W}}}tcPr':
            cell.remove(child)
    p = etree.SubElement(cell, f'{{{W}}}p')
    if first_ppr is not None:
        p.append(first_ppr)
    stamp = "2026-09-20T00:00:00Z"
    if old:
        dele = etree.SubElement(p, f'{{{W}}}del')
        dele.set(f'{{{W}}}id', str(revision_id)); revision_id += 1
        dele.set(f'{{{W}}}author', 'Ilya Zaslavsky'); dele.set(f'{{{W}}}date', stamp)
        run = etree.SubElement(dele, f'{{{W}}}r')
        txt = etree.SubElement(run, f'{{{W}}}delText'); txt.text = old
        txt.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    ins = etree.SubElement(p, f'{{{W}}}ins')
    ins.set(f'{{{W}}}id', str(revision_id)); revision_id += 1
    ins.set(f'{{{W}}}author', 'Ilya Zaslavsky'); ins.set(f'{{{W}}}date', stamp)
    run = etree.SubElement(ins, f'{{{W}}}r')
    txt = etree.SubElement(run, f'{{{W}}}t'); txt.text = new
    txt.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return revision_id, True


def redline_paragraph(paragraph, new, revision_id):
    if effective_text(paragraph) == new:
        return revision_id, False
    old = original_text(paragraph)
    first_run = paragraph.xpath('.//w:r[w:rPr]', namespaces=NS)
    rpr = copy.deepcopy(first_run[0].find(f'{{{W}}}rPr')) if first_run else None
    for child in list(paragraph):
        if child.tag != f'{{{W}}}pPr':
            paragraph.remove(child)
    stamp = "2026-09-20T00:00:00Z"
    if old:
        dele = etree.SubElement(paragraph, f'{{{W}}}del')
        dele.set(f'{{{W}}}id', str(revision_id)); revision_id += 1
        dele.set(f'{{{W}}}author', 'Ilya Zaslavsky'); dele.set(f'{{{W}}}date', stamp)
        run = etree.SubElement(dele, f'{{{W}}}r')
        if rpr is not None:
            run.append(copy.deepcopy(rpr))
        etree.SubElement(run, f'{{{W}}}delText').text = old
    ins = etree.SubElement(paragraph, f'{{{W}}}ins')
    ins.set(f'{{{W}}}id', str(revision_id)); revision_id += 1
    ins.set(f'{{{W}}}author', 'Ilya Zaslavsky'); ins.set(f'{{{W}}}date', stamp)
    run = etree.SubElement(ins, f'{{{W}}}r')
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    etree.SubElement(run, f'{{{W}}}t').text = new
    return revision_id, True


def write_docx():
    with ZipFile(source(SOURCE)) as zin:
        doc = etree.fromstring(zin.read('word/document.xml'))
        tables = doc.xpath('.//w:tbl', namespaces=NS)
        ids = [int(x) for x in doc.xpath('.//@w:id', namespaces=NS) if x.isdigit()]
        rev = max(ids + [0]) + 1
        changed = 0
        for (ti, ri, ci), value in sorted(EDITS.items()):
            rows = tables[ti].xpath('./w:tr', namespaces=NS)
            cells = rows[ri].xpath('./w:tc', namespaces=NS)
            rev, did = redline_cell(cells[ci], value, rev)
            changed += did
        prose_changed = 0
        paragraphs = doc.xpath('.//w:body/w:p', namespaces=NS)
        for prefix, replacement in PROSE.items():
            matches = [p for p in paragraphs if effective_text(p).startswith(prefix)]
            if len(matches) != 1:
                raise ValueError(f"Expected one prose paragraph beginning {prefix!r}; found {len(matches)}")
            rev, did = redline_paragraph(matches[0], replacement, rev)
            prose_changed += did
        figure_captions = {
            'Figure S3: INF-DISTANCE (21 HSAs)': 'Figure S3: INF-DISTANCE (24 HSAs)',
            'Figure S4: INF-GOVERNORATE_TAU_COVERAGE (28 HSAs)': 'Figure S4: INF-GOVERNORATE_TAU_COVERAGE (36 HSAs)',
            'Figure S8: NCD-DISTANCE (22 HSAs)': 'Figure S8: NCD-DISTANCE (24 HSAs)',
            'Figure S9: NCD-GOVERNORATE_TAU_COVERAGE (27 HSAs)': 'Figure S9: NCD-GOVERNORATE_TAU_COVERAGE (36 HSAs)',
        }
        for old, replacement in figure_captions.items():
            matches = [p for p in paragraphs if effective_text(p) == old]
            if len(matches) != 1:
                raise ValueError(f"Expected one figure caption {old!r}; found {len(matches)}")
            rev, did = redline_paragraph(matches[0], replacement, rev)
            prose_changed += did
        captions = {
            30: ("Table S4.1: Gravity model allocation metrics across parameter grid", None),
            34: ("Table S4.5: Climate variance decomposition",
                 "Table S4.5: Within- and between-HSA temperature and elevation contrasts"),
            39: ("Table S6.2: Climate contribution by healthcare connectivity",
                 "Table S6.2: Climate contribution by assignment certainty"),
        }
        for ti, (expected, replacement) in captions.items():
            paragraph = tables[ti].getprevious()
            blanks = []
            while paragraph is not None and paragraph.tag == f'{{{W}}}p' and not effective_text(paragraph).strip():
                blanks.append(paragraph)
                paragraph = paragraph.getprevious()
            if paragraph is None or paragraph.tag != f'{{{W}}}p' or effective_text(paragraph) != expected:
                raise ValueError(f"Table {ti} caption not found at expected position")
            ppr = paragraph.find(f'{{{W}}}pPr')
            if ppr is None:
                ppr = etree.Element(f'{{{W}}}pPr'); paragraph.insert(0, ppr)
            if ppr.find(f'{{{W}}}keepNext') is None:
                etree.SubElement(ppr, f'{{{W}}}keepNext')
            if ti == 30 and ppr.find(f'{{{W}}}pageBreakBefore') is None:
                etree.SubElement(ppr, f'{{{W}}}pageBreakBefore')
            if replacement:
                rev, did = redline_paragraph(paragraph, replacement, rev)
                changed += did
            for blank in blanks:
                blank.getparent().remove(blank)
            header = tables[ti].xpath('./w:tr', namespaces=NS)[0]
            trpr = header.find(f'{{{W}}}trPr')
            if trpr is None:
                trpr = etree.Element(f'{{{W}}}trPr'); header.insert(0, trpr)
            if trpr.find(f'{{{W}}}cantSplit') is None:
                etree.SubElement(trpr, f'{{{W}}}cantSplit')
        # INF allocation table used to contain 19 anchors; it now has 18.
        inf_rows = tables[4].xpath('./w:tr', namespaces=NS)
        tables[4].remove(inf_rows[-1])
        s63 = [p for p in doc.xpath('.//w:body/w:p', namespaces=NS)
               if effective_text(p) == 'S6.3 Geographic Characteristics of Allocated Populations']
        if len(s63) != 1:
            raise ValueError('S6.3 heading not found')
        ppr = s63[0].find(f'{{{W}}}pPr')
        if ppr is None:
            ppr = etree.Element(f'{{{W}}}pPr'); s63[0].insert(0, ppr)
        if ppr.find(f'{{{W}}}keepNext') is None:
            etree.SubElement(ppr, f'{{{W}}}keepNext')
        s63_body = [p for p in doc.xpath('.//w:body/w:p', namespaces=NS)
                    if effective_text(p).startswith('Most population was assigned to a final HSA.')]
        if len(s63_body) != 1:
            raise ValueError('S6.3 body not found')
        body_ppr = s63_body[0].find(f'{{{W}}}pPr')
        if body_ppr is None:
            body_ppr = etree.Element(f'{{{W}}}pPr'); s63_body[0].insert(0, body_ppr)
        if body_ppr.find(f'{{{W}}}keepLines') is None:
            etree.SubElement(body_ppr, f'{{{W}}}keepLines')
        # Remove only the ten map-only paragraphs in S7. The captions stay as
        # insertion points. Removing their relationships and media shrinks the
        # DOCX, rather than just hiding the drawings in document.xml.
        rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        rels = etree.fromstring(zin.read('word/_rels/document.xml.rels'))
        used_rel_ids = []
        map_paragraphs = []
        for p in doc.xpath('.//w:body/w:p', namespaces=NS):
            if p.xpath('.//*[local-name()="drawing"]') and not effective_text(p).strip():
                prior = p.getprevious()
                while prior is not None and prior.tag == f'{{{W}}}p' and not effective_text(prior).strip():
                    prior = prior.getprevious()
                if prior is not None and effective_text(prior).startswith('Figure S'):
                    map_paragraphs.append(p)
                    used_rel_ids.extend(p.xpath('.//*[local-name()="blip"]/@r:embed', namespaces={'r': r_ns}))
        if len(map_paragraphs) != 10 or len(used_rel_ids) != 20:
            raise ValueError(f"Expected 10 map paragraphs with two image representations each; found {len(map_paragraphs)} paragraphs and {len(used_rel_ids)} image references")
        for p in map_paragraphs:
            p.getparent().remove(p)
        s7_heading = next(p for p in doc.xpath('.//w:body/w:p', namespaces=NS)
                          if effective_text(p) == 'S7. SUPPLEMENTARY FIGURES')
        cursor = s7_heading.getnext()
        while cursor is not None and cursor.tag != f'{{{W}}}sectPr':
            following = cursor.getnext()
            if cursor.tag == f'{{{W}}}p' and not effective_text(cursor).strip() and not cursor.xpath('./w:pPr/w:sectPr', namespaces=NS):
                cursor.getparent().remove(cursor)
            cursor = following
        media_to_remove = set()
        for rid in used_rel_ids:
            matches = rels.xpath('./pr:Relationship[@Id=$rid]', namespaces={'pr': rel_ns}, rid=rid)
            if len(matches) != 1:
                raise ValueError(f"Missing map image relationship {rid}")
            target = matches[0].get('Target')
            if not target.startswith('media/'):
                raise ValueError(f"Unexpected map image target {target}")
            media_to_remove.add('word/' + target)
            rels.remove(matches[0])
        remaining_targets = {'word/' + e.get('Target') for e in rels if (e.get('Target') or '').startswith('media/')}
        media_to_remove -= remaining_targets
        settings = etree.fromstring(zin.read('word/settings.xml'))
        if settings.find(f'{{{W}}}trackRevisions') is None:
            etree.SubElement(settings, f'{{{W}}}trackRevisions')
        with ZipFile(DEST, 'w', ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in media_to_remove:
                    continue
                if item.filename == 'word/document.xml':
                    data = etree.tostring(doc, xml_declaration=True, encoding='UTF-8', standalone=True)
                elif item.filename == 'word/_rels/document.xml.rels':
                    data = etree.tostring(rels, xml_declaration=True, encoding='UTF-8', standalone=True)
                elif item.filename == 'word/settings.xml':
                    data = etree.tostring(settings, xml_declaration=True, encoding='UTF-8', standalone=True)
                else:
                    data = zin.read(item.filename)
                zout.writestr(item, data)
    return changed, prose_changed, len(map_paragraphs), len(media_to_remove)


def main():
    for net, base in (("INF", 0), ("NCD", 15)):
        scenario_tables(net, 2 + base)
        spatial_methods(net, 3 + base)
        allocation(net, 4 + base)
        assignment(net, 5 + base)
        model_tables(net, base)
    diagnostics()
    exclusions()
    sensitivity_tables()
    area_and_comparison()
    connectivity()
    changed, prose_changed, maps_removed, media_removed = write_docx()
    payload = {"snapshot_date": "2026-09-20", "source_document": str(SOURCE),
               "tracked_document": str(DEST), "changed_cells": changed,
               "changed_prose_and_captions": prose_changed,
               "removed_map_images": maps_removed, "removed_media_parts": media_removed,
               "source_files": FILES, "notes": NOTES}
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Tracked document: {DEST}\nChanged cells: {changed}\nChanged prose/captions: {prose_changed}\nMap images removed: {maps_removed}\nManifest: {MANIFEST}")


if __name__ == '__main__':
    main()
