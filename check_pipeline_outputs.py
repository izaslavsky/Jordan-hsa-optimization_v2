#!/usr/bin/env python3
"""
Verify that one network/mode/version's files are where the pipeline expects
them, complete, and unmixed with any other run's.

Three failures have shown up repeatedly, and all three are silent:

  * a climate download directory holding two modes' exports, because the path
    is keyed by network and version but not by mode;
  * files left behind by a superseded delineation, which look valid and keep
    the anchor count plausible;
  * an isolated run reading or writing the shared directory anyway, because an
    --out-dir did not propagate.

Each one produces the same signature: the right number of files, the wrong
membership. Counting is not enough, so every check below compares against the
delineation's own anchor list.

Usage:
    python check_pipeline_outputs.py --network INF --mode footprint
    python check_pipeline_outputs.py --network INF --mode fewest --out-dir out_inf_fewest_v7
    python check_pipeline_outputs.py --all          # every combination present
"""
import argparse
import re
import sys
from pathlib import Path

WEEKLY_SUFFIXES = ["precip_lags", "tempdew_wind_lags", "evapERA5_lags",
                   "soilmoistERA5_lags", "water_balance", "elevation_by_week"]

# Which combinations the manuscript and supplement actually consume. Climate is
# only retrieved for these, so for anything else an empty or foreign climate
# directory is expected rather than wrong, and reporting it as a failure just
# buries the findings that matter.
#   weekly -> S2.5.1-S2.5.7 and S4.4-S4.6 (INF-footprint), S2.5.8 (INF-fewest),
#             S3.5.* and S5.* (NCD-footprint)
#   daily  -> S2.5.9 DLNM only; there is no NCD DLNM
NEEDS_WEEKLY = {("INF", "footprint"), ("INF", "fewest"), ("NCD", "footprint")}
NEEDS_DAILY  = {("INF", "footprint")}

# Where each combination's run lives. The climate download path is keyed by
# network and version but not by mode, so two modes of one network cannot share
# an output directory; INF-fewest is kept in its own. Checking a combination
# against the wrong directory reports another mode's climate as foreign, which
# is true but useless, so --all uses this map.
HOME_DIR = {("INF", "fewest"): "out_inf_fewest_v7"}


def home_of(network, mode):
    return HOME_DIR.get((network, mode), "out")

OK, WARN, FAIL = "ok", "warn", "FAIL"


def norm(name):
    """Anchor name as it appears in an exported filename."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_")


class Report:
    def __init__(self):
        self.rows = []
        self.failed = 0
        self.warned = 0

    def add(self, status, check, detail=""):
        self.rows.append((status, check, detail))
        if status == FAIL:
            self.failed += 1
        elif status == WARN:
            self.warned += 1

    def render(self):
        for status, check, detail in self.rows:
            mark = {OK: "  [ok]  ", WARN: "  [warn]", FAIL: "  [FAIL]"}[status]
            print(f"{mark} {check}")
            if detail:
                for line in str(detail).splitlines():
                    print(f"          {line}")


def anchors_of(geojson):
    import geopandas as gpd
    gdf = gpd.read_file(geojson)
    col = "FacilityName" if "FacilityName" in gdf.columns else "HealthFacility"
    return {norm(n) for n in gdf[col].astype(str)}


def check_climate_dir(rep, label, directory, pattern, expected, network, suffixes=None):
    """Compare a climate directory's anchors against the delineation."""
    if not directory.exists():
        rep.add(WARN, f"{label}: not retrieved yet", str(directory))
        return
    found = {}
    for p in directory.glob(pattern.format(net=network)):
        stem = p.name
        stem = re.sub(rf"^{network}_HSA_", "", stem)
        for suf in (suffixes or ["daily"]):
            stem = re.sub(rf"_{suf}\.csv$", "", stem)
        found.setdefault(norm(stem), []).append(p.name)

    if not found:
        rep.add(WARN, f"{label}: required but not retrieved yet", str(directory))
        return

    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    if extra:
        rep.add(FAIL, f"{label}: {len(extra)} anchor(s) not in this delineation",
                "\n".join(extra) + f"\n-> {directory}")
    if missing:
        rep.add(FAIL, f"{label}: {len(missing)} delineation anchor(s) have no files",
                "\n".join(missing))
    if not extra and not missing:
        rep.add(OK, f"{label}: {len(found)} anchors, matches the delineation exactly")

    # completeness of the per-anchor variable set
    if suffixes:
        short = {a: len(v) for a, v in found.items() if len(v) != len(suffixes)}
        if short:
            rep.add(FAIL, f"{label}: {len(short)} anchor(s) missing variable files",
                    "\n".join(f"{a}: {n}/{len(suffixes)} files" for a, n in sorted(short.items())))
        elif found:
            rep.add(OK, f"{label}: every anchor has all {len(suffixes)} variable files")

    # a foreign network sharing the directory is fine, but say so
    others = {p.name.split("_HSA_")[0] for p in directory.glob("*_HSA_*.csv")} - {network}
    if others:
        rep.add(OK, f"{label}: also holds {', '.join(sorted(others))} files "
                    f"(separate filename prefix, not mixed)")


def check_combo(network, mode, version, out_dir, rep):
    out = Path(out_dir)
    geojson = out / f"{network}_{mode}_hsas_{version}.geojson"

    print(f"\n{'='*74}\n{network} / {mode} / {version}   out-dir: {out}\n{'='*74}")

    if not geojson.exists():
        rep.add(FAIL, "delineation missing", str(geojson))
        return
    expected = anchors_of(geojson)
    rep.add(OK, f"delineation: {geojson.name} ({len(expected)} anchors)")

    # 1. delineation-stage siblings
    for suffix, required in [("anchor_upgrade_audit", False),
                             ("major_orphan_anchor_audit", False),
                             ("final_overlap_removal", False),
                             ("residual_overlap", False)]:
        f = out / f"{network}_{mode}_{suffix}_{version}.csv"
        if f.exists():
            if suffix == "residual_overlap":
                n = sum(1 for _ in f.open()) - 1
                rep.add(OK if n == 0 else FAIL,
                        f"residual overlap audit: {n} violation(s)")
        elif required:
            rep.add(FAIL, f"missing {f.name}")

    # 2. climate, only where the paper consumes it
    combo = (network, mode)
    if combo in NEEDS_WEEKLY:
        check_climate_dir(rep, "weekly climate",
                          out / f"DRIVE_CLIMATE_BY_HSA_DOWNLOAD_{version.upper()}" / "FINAL_HSA_CLIMATE",
                          "{net}_HSA_*.csv", expected, network, WEEKLY_SUFFIXES)
    else:
        rep.add(OK, "weekly climate: not required for this mode")
    if combo in NEEDS_DAILY:
        check_climate_dir(rep, "daily climate",
                          out / f"DRIVE_CLIMATE_BY_HSA_DOWNLOAD_DAILY_{version.upper()}",
                          "{net}_HSA_*_daily.csv", expected, network)
    else:
        rep.add(OK, "daily climate: not required for this mode")

    # 3. allocation + modeling artefacts
    for label, rel in [
        ("allocation populations", f"{network}_{mode}_hsa_populations_probabilistic_{version}.csv"),
        ("facility assignments",   f"{network}_{mode}_facility_hsa_assignments_{version}.csv"),
        ("weekly modeling dataset", f"modeling/{network}_{mode}_modeling_dataset_{version}.csv"),
        ("daily modeling dataset",  f"modeling/{network}_{mode}_daily_modeling_dataset_{version}.csv"),
    ]:
        f = out / rel
        if "daily modeling" in label and combo not in NEEDS_DAILY:
            continue
        if "weekly modeling" in label and combo not in NEEDS_WEEKLY:
            continue
        rep.add(OK if f.exists() else WARN,
                f"{label}: {'present' if f.exists() else 'not built yet'}", rel)

    # 4. modeling dataset must agree with the delineation
    md = out / f"modeling/{network}_{mode}_modeling_dataset_{version}.csv"
    if md.exists():
        import pandas as pd
        df = pd.read_csv(md, usecols=lambda c: c in ("hsa_id",))
        if "hsa_id" in df.columns:
            got = {norm(x) for x in df["hsa_id"].unique()}
            bad = sorted(got - expected)
            gone = sorted(expected - got)
            if bad or gone:
                rep.add(FAIL, "weekly modeling dataset disagrees with the delineation",
                        (f"not in delineation: {bad}\n" if bad else "") +
                        (f"absent from dataset: {gone}" if gone else ""))
            else:
                rep.add(OK, f"weekly modeling dataset: {len(got)} anchors, consistent")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default="INF")
    ap.add_argument("--mode", default="footprint")
    ap.add_argument("--version", default="v7")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--all", action="store_true",
                    help="check every network/mode whose delineation exists")
    a = ap.parse_args()

    rep = Report()
    if a.all:
        combos = set()
        for out_dir in ["out", "out_inf_fewest_v7"]:
            for g in sorted(Path(out_dir).glob(f"*_hsas_{a.version}.geojson")):
                m = re.match(rf"(INF|NCD)_(.+)_hsas_{a.version}\.geojson", g.name)
                if m:
                    combos.add((m.group(1), m.group(2)))
        for net, mode in sorted(combos):
            check_combo(net, mode, a.version, home_of(net, mode), rep)
    else:
        check_combo(a.network, a.mode, a.version, a.out_dir, rep)

    print(f"\n{'='*74}")
    rep.render()
    print(f"{'='*74}")
    print(f"check_pipeline_outputs: {rep.failed} failure(s), {rep.warned} not-yet-built")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
