"""Sync the public release of this repository.

The public repo carries the runnable pipeline, the synthetic datasets, three
documents, and nothing else. Three rules it must never break:

1. No real patient data. Only SYN*/SYNMOD* diagnosis files ship; the real
   INF_*/NCD_* files stay here.
2. No saved notebook outputs. Executed cells embed absolute paths, run
   directory names and real counts; stripping them is both a privacy measure
   and what keeps the published notebooks honest about never having been run
   against data the reader cannot obtain.
3. No superseded duplicates. One notebook per pipeline step.

Usage:
    python3 build_public_snapshot.py --check    # report only
    python3 build_public_snapshot.py --apply
"""
import argparse
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "jordan-hsa-optimization"

# ---- what ships -------------------------------------------------------------
NOTEBOOKS = [
    "HSA_FINAL.ipynb",                             # step 1, delineation
    "Population_Allocation_Probabilistic_v2.ipynb",# step 2, gravity allocation
    "Generate_Modeling_Dataset.ipynb",             # step 3, weekly panel
    "run_climate_health_modeling.ipynb",           # step 4, weekly models
    "Generate_Daily_Modeling_Dataset.ipynb",       # step 5, daily panel
    "run_climate_models_daily.ipynb",              # step 6, DLNM
    "GEE_local_Climate_Features_by_Facilities.ipynb",
    "GEE_local_HSA_Weekly_Climate_Lagged.ipynb",
    "GEE_local_HSA_Weekly_Climate_Lagged_chunked.ipynb",
    "GEE_local_HSA_Daily_Climate.ipynb",
]

MODULES = [
    "run_pipeline.py", "hsa_optimization.py", "hsa_mapping_working.py",
    "disease_focus.py", "population_allocation.py",
    "prepare_ml_dataset.py", "prepare_daily_modeling_dataset.py",
    "generate_weekly_disease_counts_adjusted.py", "generate_daily_disease_counts.py",
    "generate_diagnosis_counts_v2.py", "generate_hsa_metadata.py",
    "train_ml_models.py", "train_improved_models.py",
    "climate_health_modeling.py", "climate_health_modeling_comprehensive.py",
    "climate_health_modeling_parsimonious.py", "climate_health_modeling_anomalies.py",
    "hsa_objective_analysis.py",
    # sensitivity and verification
    "weight_sensitivity_reoptimize.py", "run_coverage_sensitivity.py",
    "check_no_hardcoding.py", "check_hsa_overlap.py", "check_pipeline_outputs.py",
    "reproduces_stored_delineation.py", "stage_isolated_run.py",
    # assignment-certainty split behind supplement Table S6.2
    "connectivity_reanalysis.py",
]
ANALYSES = sorted(str(p.name) for p in HERE.glob("0[89]_*.py")) + \
           sorted(str(p.name) for p in HERE.glob("1[0-6]_*.py"))

DOCS = ["README.md", "SETUP_INSTRUCTIONS.md", "DATA_FLOW_ANALYSIS.md"]
# .gitignore is NOT copied: the public repo needs its own allowlist-based
# rules, and overwriting it with this repo's version silently removed the
# out/ placeholder exception and the notebook allowlist.
ROOT_EXTRA = ["requirements.txt", "LICENSE"]
PACKAGES = ["dlnm"]

# Synthetic inputs and shared geography only. Real diagnosis files are excluded
# by construction: nothing here matches INF_*/NCD_* without a SYN prefix.
DATA_GLOBS = ["SYN*.csv", "jordan_boundary.gpkg", "jordan_governorates.gpkg",
              "jor_ppp_2020_*.tif", "jordan_islamic_calendar.csv",
              "jmp_2025_jordan_governorate.csv", "hsa_metadata.csv"]
DATA_DIRS = ["adm_boundaries"]

# Anything matching these must never reach the public tree.
FORBIDDEN = re.compile(r"^(INF|NCD)_(patient_visits|facility_coordinates|groups_of_diagnoses)")

# Superseded files to delete from the public tree if present.
RETIRE = [
    "HSA_v6_FINAL.ipynb",                       # v6; the paper reports one algorithm
    "Patient_Allocation_Probabilistic.ipynb",   # superseded by Population_Allocation_Probabilistic_v2
    "GEE_Climate_Features_by_Facilities.ipynb", # superseded by the GEE_local_ variant
    "GEE_HSA_Weekly_Climate_Lagged.ipynb",      # superseded by the GEE_local_ variant
    "compare_delineations.ipynb",               # compares v6/v7/v8; not part of the reported workflow
    "patient_allocation.py",                    # superseded by population_allocation.py
    "network_utils.py",                         # no longer imported anywhere
]


def strip_outputs(nb_path, dest):
    nb = json.loads(Path(nb_path).read_text(encoding="utf-8"))
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
            cell.get("metadata", {}).pop("execution", None)
    nb.get("metadata", {}).pop("widgets", None)
    dest.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    apply = args.apply and not args.check

    planned, missing, retired, refused = [], [], [], []

    for name in NOTEBOOKS:
        src = HERE / name
        if not src.exists():
            missing.append(name); continue
        planned.append(name)
        if apply:
            strip_outputs(src, PUBLIC / name)

    for name in MODULES + ANALYSES + DOCS + ROOT_EXTRA:
        src = HERE / name
        if not src.exists():
            missing.append(name); continue
        planned.append(name)
        if apply:
            shutil.copy2(src, PUBLIC / name)

    for pkg in PACKAGES:
        src = HERE / pkg
        if not src.exists():
            missing.append(pkg + "/"); continue
        planned.append(pkg + "/")
        if apply:
            dst = PUBLIC / pkg
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))

    data_dst = PUBLIC / "data"
    if apply:
        data_dst.mkdir(exist_ok=True)
    for pattern in DATA_GLOBS:
        for src in sorted((HERE / "data").glob(pattern)):
            if FORBIDDEN.match(src.name):
                refused.append(src.name); continue
            planned.append(f"data/{src.name}")
            if apply:
                shutil.copy2(src, data_dst / src.name)
    for d in DATA_DIRS:
        src = HERE / "data" / d
        if src.is_dir():
            planned.append(f"data/{d}/")
            if apply:
                dst = data_dst / d
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst,
                                ignore=shutil.ignore_patterns(".DS_Store"))

    # out/ ships as an empty placeholder: the pipeline writes here.
    if apply:
        (PUBLIC / "out").mkdir(exist_ok=True)  # noqa: hardcode - public repo layout
        (PUBLIC / "out" / ".gitkeep").write_text("", encoding="utf-8")  # noqa: hardcode
    planned.append("out/.gitkeep")  # noqa: hardcode - path in the public repo, not a run dir

    for name in RETIRE:
        p = PUBLIC / name
        if p.exists():
            retired.append(name)
            if apply:
                p.unlink()

    print(f"{'APPLIED' if apply else 'CHECK (no changes written)'}")
    print(f"  files planned for the public tree : {len(planned)}")
    print(f"  superseded files to remove        : {len(retired)}  {retired}")
    print(f"  refused (real patient data)       : {len(refused)}  {refused}")
    if missing:
        print(f"  MISSING from this repo            : {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
