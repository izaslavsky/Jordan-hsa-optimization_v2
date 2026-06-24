#!/usr/bin/env python3
"""
Generate modeling-oriented synthetic patient-visit files for the Jordan HSA workflow.

This script is intentionally aggregation-first. It does not copy or jitter real
patient records. It uses aggregate HSA-week count structure to generate new
synthetic HSA-week outcomes, then expands those counts into visit-level rows
using smoothed facility and diagnosis distributions from the existing synthetic
datasets.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path("/Users/ilya/WORK_PROJECTS/gc3wefh")
DEFAULT_INF = ROOT / "jordan-hsa-optimization_INF_FOOTPRINT"
DEFAULT_NCD = ROOT / "jordan-hsa-optimization_NCD_FOOTPRINT"

OUT_COLUMNS = [
    "patientid",
    "gender",
    "ageatdiagnosis",
    "governorate",
    "diagnosisid",
    "diagnosis",
    "general_category",
    "datetimediagnosisentered",
    "healthfacility",
    "healthfacilitytype",
]


@dataclass(frozen=True)
class Config:
    label: str
    repo: Path
    source_synthetic_visits: Path
    source_facilities: Path
    source_assignments: Path
    weekly_target: Path
    weekly_secondary: Path
    output_name: str
    target_col: str
    secondary_col: str
    target_category: str
    seed: int
    target_scale: float
    min_weekly_count: int


def norm_name(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def parse_date(value: str) -> date:
    s = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            pass
    return datetime.fromisoformat(s).date()


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def read_csv_dicts(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def load_weekly_counts(path: Path, count_col: str) -> dict[str, list[tuple[date, float]]]:
    by_hsa: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in read_csv_dicts(path):
        week = parse_date(row.get("week_start_iso") or row.get("week_start"))
        by_hsa[norm_name(row["hsa_id"])].append((week, float(row[count_col] or 0)))
    for hsa in by_hsa:
        by_hsa[hsa].sort(key=lambda x: x[0])
    return dict(by_hsa)


def load_facilities(path: Path) -> dict[str, dict[str, str]]:
    facilities = {}
    for row in read_csv_dicts(path):
        name = norm_name(row["healthfacility"])
        facilities[name] = {
            "healthfacility": name,
            "healthfacilitytype": row.get("healthfacilitytype", "Unknown") or "Unknown",
            "governorate": row.get("governorate", "Unknown") or "Unknown",
        }
    return facilities


def load_assignments(path: Path) -> dict[str, str]:
    assignment = {}
    for row in read_csv_dicts(path):
        if str(row.get("excluded", "")).lower() in {"true", "1", "yes"}:
            continue
        assignment[norm_name(row["facility_id"])] = norm_name(row["primary_hsa"])
    return assignment


def weighted_choice(items: list[tuple[str, float]], rng: random.Random) -> str:
    total = sum(max(0.0, w) for _, w in items)
    if total <= 0:
        return items[0][0]
    r = rng.random() * total
    acc = 0.0
    for item, weight in items:
        acc += max(0.0, weight)
        if acc >= r:
            return item
    return items[-1][0]


def smooth_distribution(
    counter: Counter[str],
    universe: list[str],
    alpha: float = 1.0,
    power: float = 1.0,
) -> list[tuple[str, float]]:
    return [(item, (counter.get(item, 0) ** power) + alpha) for item in universe]


def build_distributions(
    synthetic_visits: Path,
    facilities: dict[str, dict[str, str]],
    assignment: dict[str, str],
    target_category: str,
):
    facility_by_hsa_counts: dict[str, Counter[str]] = defaultdict(Counter)
    category_counts: Counter[str] = Counter()
    diagnosis_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    diagnosisid_by_diagnosis: dict[str, Counter[str]] = defaultdict(Counter)
    genders: Counter[str] = Counter()
    ages_by_category: dict[str, Counter[int]] = defaultdict(Counter)

    for row in read_csv_dicts(synthetic_visits):
        facility = norm_name(row.get("healthfacility", ""))
        hsa = assignment.get(facility)
        if hsa:
            facility_by_hsa_counts[hsa][facility] += 1

        category = row.get("general_category") or row.get("General_Category") or ""
        diagnosis = row.get("diagnosis") or category or "Synthetic diagnosis"
        diagnosisid = row.get("diagnosisid") or "SYN"
        category_counts[category] += 1
        diagnosis_by_category[category][diagnosis] += 1
        diagnosisid_by_diagnosis[diagnosis][diagnosisid] += 1
        genders[row.get("gender") or "Unknown"] += 1
        try:
            age = int(float(row.get("ageatdiagnosis") or 0))
            ages_by_category[category][max(0, min(100, age))] += 1
        except ValueError:
            pass

    all_facilities = sorted(facilities)
    hsa_facility_dist = {}
    for hsa in sorted(set(assignment.values())):
        hsa_facilities = sorted(f for f, assigned_hsa in assignment.items() if assigned_hsa == hsa and f in facilities)
        if not hsa_facilities:
            hsa_facilities = all_facilities
        # Flatten facility probabilities to avoid recreating facility-specific volume spikes.
        hsa_facility_dist[hsa] = smooth_distribution(
            facility_by_hsa_counts[hsa],
            hsa_facilities,
            alpha=5.0,
            power=0.55,
        )

    categories = sorted(c for c in category_counts if c)
    target_diagnoses = smooth_distribution(diagnosis_by_category[target_category], sorted(diagnosis_by_category[target_category]), alpha=1.0)
    non_target_categories = [c for c in categories if c != target_category]
    non_target_category_dist = smooth_distribution(category_counts, non_target_categories, alpha=5.0)
    gender_dist = smooth_distribution(genders, sorted(genders), alpha=1.0)

    return {
        "hsa_facility_dist": hsa_facility_dist,
        "target_diagnoses": target_diagnoses,
        "non_target_category_dist": non_target_category_dist,
        "diagnosis_by_category": diagnosis_by_category,
        "diagnosisid_by_diagnosis": diagnosisid_by_diagnosis,
        "gender_dist": gender_dist,
        "ages_by_category": ages_by_category,
    }


def autocorr_lag1(series_by_hsa: dict[str, list[tuple[date, float]]]) -> float:
    xs, ys = [], []
    for series in series_by_hsa.values():
        vals = [v for _, v in series]
        if len(vals) < 3:
            continue
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) or 1.0
        z = [(v - mean) / sd for v in vals]
        xs.extend(z[:-1])
        ys.extend(z[1:])
    if not xs:
        return 0.6
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return max(0.25, min(0.92, num / den if den else 0.6))


def seasonal_profile(series_by_hsa: dict[str, list[tuple[date, float]]]) -> dict[int, float]:
    ratios: dict[int, list[float]] = defaultdict(list)
    for series in series_by_hsa.values():
        vals = [v for _, v in series]
        mean = sum(vals) / len(vals) if vals else 0
        if mean <= 0:
            continue
        for week, value in series:
            ratios[int(week.strftime("%V"))].append(value / mean)
    raw = {w: (sum(v) / len(v) if v else 1.0) for w, v in ratios.items()}
    profile = {}
    for w in range(1, 54):
        vals = [raw.get(((w + off - 1) % 53) + 1, 1.0) for off in (-1, 0, 1)]
        smoothed = sum(vals) / len(vals)
        profile[w] = max(0.35, min(2.5, 1.0 + 0.75 * (smoothed - 1.0)))
    avg = sum(profile.values()) / len(profile)
    return {w: v / avg for w, v in profile.items()}


def synthesize_weekly_counts(
    target: dict[str, list[tuple[date, float]]],
    secondary: dict[str, list[tuple[date, float]]],
    cfg: Config,
    rng: random.Random,
):
    phi = autocorr_lag1(target)
    profile = seasonal_profile(target)
    synthetic_target = {}
    synthetic_secondary = {}
    all_target_total = sum(v for series in target.values() for _, v in series)
    all_secondary_total = sum(v for series in secondary.values() for _, v in series)
    global_secondary_ratio = max(1.05, all_secondary_total / max(1.0, all_target_total))

    for hsa, series in target.items():
        vals = [v for _, v in series]
        mean = (sum(vals) / len(vals)) * cfg.target_scale if vals else 0.0
        # Avoid exact HSA means by adding modest multiplicative variation.
        mean *= rng.uniform(0.88, 1.12)
        prev = max(cfg.min_weekly_count, int(round(mean)))
        hsa_out = []
        hsa_sec = []
        sec_series = dict(secondary.get(hsa, []))
        hsa_secondary_ratio = (sum(sec_series.values()) / max(1.0, sum(vals))) if vals else global_secondary_ratio
        hsa_secondary_ratio = max(1.02, min(4.5, 0.75 * hsa_secondary_ratio + 0.25 * global_secondary_ratio))

        for week, _ in series:
            woy = int(week.strftime("%V"))
            seasonal = profile.get(woy, 1.0)
            lam = max(0.1, mean * seasonal)
            expected = max(0.1, lam + phi * 0.75 * (prev - lam))
            # Overdispersed Gaussian approximation; enough for synthetic workflow demonstration.
            sd = math.sqrt(expected + 0.28 * expected * expected)
            count = int(round(max(0.0, rng.gauss(expected, sd))))
            if mean >= cfg.min_weekly_count and count == 0 and rng.random() < 0.7:
                count = cfg.min_weekly_count
            prev = count
            hsa_out.append((week, count))

            ratio_noise = rng.lognormvariate(0.0, 0.08)
            secondary_count = max(count, int(round(count * hsa_secondary_ratio * ratio_noise)))
            hsa_sec.append((week, secondary_count))

        synthetic_target[hsa] = hsa_out
        synthetic_secondary[hsa] = hsa_sec

    return synthetic_target, synthetic_secondary, {"lag1_autocorr_source": phi, "target_scale": cfg.target_scale}


def choose_age(category: str, distributions, rng: random.Random) -> int:
    ages = distributions["ages_by_category"].get(category)
    if ages:
        return int(weighted_choice([(str(k), v) for k, v in ages.items()], rng))
    return rng.randint(5, 85)


def diagnosis_for_category(category: str, distributions, rng: random.Random) -> tuple[str, str]:
    if category and category in distributions["diagnosis_by_category"]:
        diagnoses = smooth_distribution(
            distributions["diagnosis_by_category"][category],
            sorted(distributions["diagnosis_by_category"][category]),
            alpha=1.0,
        )
        diagnosis = weighted_choice(diagnoses, rng)
    else:
        diagnosis = f"Synthetic {category or 'diagnosis'}"
    ids = distributions["diagnosisid_by_diagnosis"].get(diagnosis)
    diagnosisid = weighted_choice([(k, v) for k, v in ids.items()], rng) if ids else f"SYN-{abs(hash(diagnosis)) % 100000:05d}"
    return diagnosis, diagnosisid


def write_visits(
    cfg: Config,
    facilities: dict[str, dict[str, str]],
    distributions,
    synthetic_target,
    synthetic_secondary,
    output_dir: Path,
):
    rng = random.Random(cfg.seed + 1000)
    output_path = output_dir / cfg.output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    n_rows = 0
    target_rows = 0

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        patient_seq = 1
        for hsa in sorted(synthetic_target):
            facility_dist = distributions["hsa_facility_dist"].get(hsa)
            if not facility_dist:
                facility_dist = [(hsa, 1.0)] if hsa in facilities else [(next(iter(facilities)), 1.0)]
            secondary_map = dict(synthetic_secondary[hsa])
            for week, target_count in synthetic_target[hsa]:
                total_count = max(target_count, secondary_map.get(week, target_count))
                non_target_count = max(0, total_count - target_count)
                for is_target, n in ((True, target_count), (False, non_target_count)):
                    for _ in range(n):
                        category = cfg.target_category if is_target else weighted_choice(distributions["non_target_category_dist"], rng)
                        if is_target:
                            diagnosis = weighted_choice(distributions["target_diagnoses"], rng)
                            ids = distributions["diagnosisid_by_diagnosis"].get(diagnosis)
                            diagnosisid = weighted_choice([(k, v) for k, v in ids.items()], rng) if ids else f"SYN-{cfg.label}-TARGET"
                        else:
                            diagnosis, diagnosisid = diagnosis_for_category(category, distributions, rng)
                        facility = weighted_choice(facility_dist, rng)
                        fmeta = facilities.get(facility, {"governorate": "Unknown", "healthfacilitytype": "Unknown"})
                        days_available = 6
                        if week >= date(2024, 1, 29):
                            days_available = 2
                        visit_date = week + timedelta(days=rng.randint(0, days_available))
                        writer.writerow({
                            "patientid": f"SYNMOD{cfg.label}-{patient_seq:09d}",
                            "gender": weighted_choice(distributions["gender_dist"], rng),
                            "ageatdiagnosis": choose_age(category, distributions, rng),
                            "governorate": fmeta["governorate"],
                            "diagnosisid": diagnosisid,
                            "diagnosis": diagnosis,
                            "general_category": category,
                            "datetimediagnosisentered": visit_date.isoformat(),
                            "healthfacility": facility,
                            "healthfacilitytype": fmeta["healthfacilitytype"],
                        })
                        patient_seq += 1
                        n_rows += 1
                        target_rows += 1 if is_target else 0
    return output_path, {"rows": n_rows, "target_rows": target_rows}


def summarize_weekly(series: dict[str, list[tuple[date, int]]]) -> dict[str, float]:
    vals = [v for rows in series.values() for _, v in rows]
    return {
        "hsa_count": len(series),
        "hsa_week_rows": len(vals),
        "total": sum(vals),
        "mean": sum(vals) / len(vals) if vals else 0,
        "max": max(vals) if vals else 0,
        "nonzero_fraction": sum(1 for v in vals if v > 0) / len(vals) if vals else 0,
    }


def generate(cfg: Config, output_dir: Path):
    rng = random.Random(cfg.seed)
    facilities = load_facilities(cfg.source_facilities)
    assignments = load_assignments(cfg.source_assignments)
    distributions = build_distributions(cfg.source_synthetic_visits, facilities, assignments, cfg.target_category)
    target = load_weekly_counts(cfg.weekly_target, cfg.target_col)
    secondary = load_weekly_counts(cfg.weekly_secondary, cfg.secondary_col)
    synthetic_target, synthetic_secondary, params = synthesize_weekly_counts(target, secondary, cfg, rng)
    out_path, row_summary = write_visits(cfg, facilities, distributions, synthetic_target, synthetic_secondary, output_dir)
    return {
        "label": cfg.label,
        "output": str(out_path),
        "source_weekly_target": str(cfg.weekly_target),
        "source_synthetic_visits": str(cfg.source_synthetic_visits),
        "privacy_design": [
            "No real patient rows or patient IDs are copied.",
            "Synthetic visits are generated from smoothed aggregate HSA-week behavior.",
            "Facility and diagnosis sampling uses smoothed distributions from existing synthetic files.",
            "HSA-week counts are perturbed and scaled; they do not reproduce exact observed count histories.",
        ],
        "generation_parameters": params,
        "weekly_target_summary": summarize_weekly(synthetic_target),
        "weekly_secondary_summary": summarize_weekly(synthetic_secondary),
        "visit_row_summary": row_summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_INF / "data")
    parser.add_argument("--seed", type=int, default=20260418)
    parser.add_argument("--target-scale", type=float, default=0.75)
    parser.add_argument("--boundary-version", default=os.environ.get("BOUNDARY_VERSION", os.environ.get("PIPELINE_VERSION", "v7")),
                        help="HSA boundary version (v6, v7, v8). Must match the run that produced allocation/weekly files.")
    args = parser.parse_args()
    bv = args.boundary_version

    configs = [
        Config(
            label="INF",
            repo=DEFAULT_INF,
            source_synthetic_visits=DEFAULT_INF / "data" / "SYNINF_patient_visits.csv",
            source_facilities=DEFAULT_INF / "data" / "INF_facility_coordinates.csv",
            source_assignments=DEFAULT_INF / "out" / f"INF_footprint_facility_hsa_assignments_{bv}.csv",
            weekly_target=DEFAULT_INF / "out" / f"INF_footprint_weekly_diarrheal_adjusted_{bv}.csv",
            weekly_secondary=DEFAULT_INF / "out" / f"INF_footprint_weekly_infectious_adjusted_{bv}.csv",
            output_name="SYNMODINF_patient_visits.csv",
            target_col="diarrheal_count_adjusted",
            secondary_col="infectious_count_adjusted",
            target_category="Diarrheal Diseases",
            seed=args.seed + 11,
            target_scale=args.target_scale,
            min_weekly_count=1,
        ),
        Config(
            label="NCD",
            repo=DEFAULT_NCD,
            source_synthetic_visits=DEFAULT_INF / "data" / "SYNNCD_patient_visits.csv",
            source_facilities=DEFAULT_NCD / "data" / "NCD_facility_coordinates.csv",
            source_assignments=DEFAULT_NCD / "out" / f"NCD_footprint_facility_hsa_assignments_{bv}.csv",
            weekly_target=DEFAULT_NCD / "out" / f"NCD_footprint_weekly_hypertension_adjusted_{bv}.csv",
            weekly_secondary=DEFAULT_NCD / "out" / f"NCD_footprint_weekly_ncd_adjusted_{bv}.csv",
            output_name="SYNMODNCD_patient_visits.csv",
            target_col="hypertension_count_adjusted",
            secondary_col="ncd_count_adjusted",
            target_category="Hypertension",
            seed=args.seed + 29,
            target_scale=args.target_scale,
            min_weekly_count=2,
        ),
    ]

    reports = [generate(cfg, args.output_dir) for cfg in configs]
    report_path = args.output_dir / "SYNMOD_generation_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)
    print(json.dumps(reports, indent=2))
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()
