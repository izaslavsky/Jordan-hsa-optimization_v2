"""
Rebuild the three journal figure files for the GeoHealth submission.

Figure 1 and Figure 2 are rendered from the editable PowerPoint deck; Figure 3
is drawn from the delineation currently stored in the run directory, so the map
can never show a different anchor set than the numbers reported beside it.

Usage:
    python3 build_submission_figures.py                 # all three
    python3 build_submission_figures.py --only 3        # just the map panel
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image

from hsa_mapping_working import create_hsa_map

ROOT = Path(__file__).resolve().parent
PAPER = Path(os.environ.get("HSA_PAPER_DIR", ROOT.parent / "HSA_paper"))
SUBMISSION = PAPER / "GeoHealth_R1_ready_submission_2026-08-18"
DECK = PAPER / "Figures_1_2_editable_parameterized_algorithm_v3.pptx"

OUT_DIR = Path(os.environ.get("HSA_OUT_DIR", ROOT / "out"))
if not OUT_DIR.is_absolute():
    OUT_DIR = ROOT / OUT_DIR
DATA = ROOT / "data"

NETWORK = os.environ.get("HSA_FIG3_NETWORK", "INF")
VERSION = os.environ.get("HSA_BOUNDARY_VERSION", "v7")
PANELS = [("fewest", "FEWEST"), ("footprint", "FOOTPRINT"), ("distance", "DISTANCE")]

# Journal pixel sizes at 300 dpi, matching what was accepted for R1.
FIG1_SIZE = (2688, 2000)
FIG2_SIZE = (2400, 2800)
FIG3_WIDTH = 2400

# The published panels crop the eastern desert, where no facility sits, so the
# populated west stays legible at column width. Full country extent is roughly
# lon 34.9-39.3, lat 29.2-33.4.
FIG3_EXTENT = (
    float(os.environ.get("HSA_FIG3_LON_MIN", 34.85)),
    float(os.environ.get("HSA_FIG3_LON_MAX", 37.20)),
    float(os.environ.get("HSA_FIG3_LAT_MIN", 29.10)),
    float(os.environ.get("HSA_FIG3_LAT_MAX", 33.50)),
)

# Slide 1 is the workflow schematic (Figure 1); slide 3 is the algorithm
# pseudocode (Figure 2). Slide 2 is the superseded algorithm panel.
FIG1_SLIDE = 1
FIG2_SLIDE = 3


def render_deck(tmp: Path) -> dict:
    """Render the deck to PNGs via LibreOffice, returning slide number -> path."""
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if not Path(soffice).exists():
        raise FileNotFoundError(
            "LibreOffice is needed to render the figure deck; install it or "
            "export slides 1 and 3 to PNG by hand."
        )
    pdf_dir = tmp / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(DECK)],
        check=True, capture_output=True,
    )
    pdf = next(pdf_dir.glob("*.pdf"))
    png_root = tmp / "slide"
    subprocess.run(
        ["pdftoppm", "-r", "300", "-png", str(pdf), str(png_root)],
        check=True, capture_output=True,
    )
    return {int(p.stem.split("-")[-1]): p for p in tmp.glob("slide-*.png")}


def export_slide(src: Path, size: tuple, dest: Path, box: tuple = None,
                 grayscale: bool = True) -> None:
    """Write one slide render as a journal TIFF.

    `box` crops in slide fractions (left, top, right, bottom) before resizing.
    Figures 1 and 2 were submitted as grayscale, so that is the default here;
    changing it would make the revision's figures differ from the accepted ones
    in a way unrelated to the revision.
    """
    im = Image.open(src).convert("RGB")
    if box:
        w, h = im.size
        im = im.crop((round(box[0] * w), round(box[1] * h),
                      round(box[2] * w), round(box[3] * h)))
    im = im.resize(size, Image.Resampling.LANCZOS)
    if grayscale:
        im = im.convert("L").convert("RGB")
    im.save(dest, format="TIFF", compression="tiff_lzw", dpi=(300, 300))
    print(f"wrote {dest.name}  {size[0]}x{size[1]}"
          + ("  grayscale" if grayscale else "  colour"))


def algorithm_crop_box() -> tuple:
    """Crop fractions that frame the algorithm panel on its landscape slide.

    Derived from the shape's own position so the figure keeps its proportions
    if the panel is moved or resized, rather than from pixel constants measured
    against one particular render.
    """
    from pptx import Presentation
    from pptx.util import Emu
    deck = Presentation(str(DECK))
    slide = deck.slides[FIG2_SLIDE - 1]
    slide_w = Emu(deck.slide_width).inches
    slide_h = Emu(deck.slide_height).inches
    shape = max(slide.shapes, key=lambda sh: (sh.width or 0) * (sh.height or 0))
    centre_x = (Emu(shape.left).inches + Emu(shape.width).inches / 2) / slide_w

    top, bottom = 25 / 960, 925 / 960          # margins the accepted figure kept
    crop_h_in = (bottom - top) * slide_h
    crop_w_in = crop_h_in * FIG2_SIZE[0] / FIG2_SIZE[1]
    half = (crop_w_in / slide_w) / 2
    return (centre_x - half, top, centre_x + half, bottom)


def clamp_labels(ax) -> int:
    """Pull anchor labels back inside the panel.

    adjust_text optimises label placement without knowing about the panel
    border, so on a cropped extent it can park a long facility name half
    outside the axes. Shift any such label back by the overhang.
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    frame = ax.get_window_extent(renderer)
    inverse = ax.transData.inverted()
    moved = 0
    for text in ax.texts:
        box = text.get_window_extent(renderer)
        dx = dy = 0.0
        if box.x0 < frame.x0:
            dx = frame.x0 - box.x0 + 3
        elif box.x1 > frame.x1:
            dx = frame.x1 - box.x1 - 3
        if box.y0 < frame.y0:
            dy = frame.y0 - box.y0 + 3
        elif box.y1 > frame.y1:
            dy = frame.y1 - box.y1 - 3
        if not dx and not dy:
            continue
        origin = inverse.transform((box.x0, box.y0))
        shifted = inverse.transform((box.x0 + dx, box.y0 + dy))
        x, y = text.get_position()
        text.set_position((x + shifted[0] - origin[0], y + shifted[1] - origin[1]))
        moved += 1
    return moved


def anchors_from(geojson: Path) -> tuple:
    gdf = gpd.read_file(geojson)
    pts = gpd.GeoDataFrame(
        gdf.drop(columns="geometry"),
        geometry=gpd.points_from_xy(gdf["lon"], gdf["lat"]),
        crs="EPSG:4326",
    )
    return pts, gdf


def build_figure3(dest: Path) -> None:
    country = gpd.read_file(DATA / "jordan_boundary.gpkg")
    governorates = gpd.read_file(DATA / "jordan_governorates.gpkg")
    pop_raster = DATA / "jor_ppp_2020_constrained.tif"

    coords = DATA / f"SYNMOD{NETWORK}_facility_coordinates.csv"
    if not coords.exists():
        coords = DATA / f"{NETWORK}_facility_coordinates.csv"
    import pandas as pd
    fac = pd.read_csv(coords)
    fac.columns = [c.strip().lstrip("﻿") for c in fac.columns]
    lon_col = next(c for c in fac.columns if c.lower() in ("longitude", "lon"))
    lat_col = next(c for c in fac.columns if c.lower() in ("latitude", "lat"))
    all_facilities = gpd.GeoDataFrame(
        fac, geometry=gpd.points_from_xy(fac[lon_col], fac[lat_col]), crs="EPSG:4326"
    )

    fig, axes = plt.subplots(1, 3, figsize=(18, 11), facecolor="white")
    counts = []
    for ax, (mode, label) in zip(axes, PANELS):
        geojson = OUT_DIR / f"{NETWORK}_{mode}_hsas_{VERSION}.geojson"
        if not geojson.exists():
            raise FileNotFoundError(
                f"{geojson} is missing; run the delineation before building Figure 3."
            )
        pts, polys = anchors_from(geojson)
        counts.append((label, len(pts)))
        create_hsa_map(
            mode_name=mode, mode_title=f"{label} HSAs",
            facilities_hsa=pts, all_facilities=all_facilities,
            country_boundary=country, governorates=governorates,
            pop_raster_path=pop_raster, output_path=None,
            network=NETWORK, hsa_polygons=polys,
            ax=ax, show_axes=False, show_legend=False, show_title=False,
        )
        lon_min, lon_max, lat_min, lat_max = FIG3_EXTENT
        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(lat_min, lat_max)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(f"({'abc'[PANELS.index((mode, label))]}) {label}  -  {len(pts)} HSAs",
                      fontsize=13, fontweight="bold", labelpad=8)
        nudged = clamp_labels(ax)
        if nudged:
            print(f"  {label}: pulled {nudged} label(s) back inside the panel")

    legend_elements = [
        mpatches.Patch(facecolor="#00AA00", alpha=0.25, edgecolor="black", linewidth=0.5,
                       label="HSA populated area (clipped to WorldPop)"),
        mpatches.Patch(facecolor="none", edgecolor="#FF0000", linewidth=1.8, linestyle="dashed",
                       label="Full service radius (reference)"),
        mpatches.Circle((0, 0), 0.1, facecolor="#FF0000", edgecolor="white", linewidth=0.8,
                        label="HSA anchor facility"),
        mpatches.Circle((0, 0), 0.1, facecolor="#0000FF", alpha=0.5, label="All facilities"),
        mpatches.Patch(facecolor="none", edgecolor="black", linewidth=2, label="Country boundary"),
        mpatches.Patch(facecolor="none", edgecolor="gray", linewidth=0.8, label="Governorate boundary"),
        mpatches.Patch(facecolor="gray", alpha=0.5, label="Population density"),
    ]
    # A figure-level legend below the panels cannot collide with an anchor
    # label, which a per-panel legend did whenever adjust_text pushed a name
    # into the same corner.
    fig.legend(handles=legend_elements, loc="lower center", ncol=4, fontsize=10,
               frameon=True, framealpha=1.0, edgecolor="black", facecolor="white",
               bbox_to_anchor=(0.5, 0.005))
    fig.subplots_adjust(wspace=0.02, left=0.01, right=0.99, top=0.99, bottom=0.11)

    # Render to a temporary PNG so no intermediate lands in the submission folder.
    with tempfile.TemporaryDirectory() as td:
        tmp_png = Path(td) / "figure3.png"
        fig.savefig(tmp_png, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        im = Image.open(tmp_png).convert("RGB")
        height = round(im.height * FIG3_WIDTH / im.width)
        im = im.resize((FIG3_WIDTH, height), Image.Resampling.LANCZOS)
        im.save(dest, format="TIFF", compression="tiff_lzw", dpi=(300, 300))
    print(f"wrote {dest.name}  {FIG3_WIDTH}x{height}  panels: "
          + ", ".join(f"{l}={n}" for l, n in counts))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["1", "2", "3"], action="append",
                    help="build only the listed figures (repeatable)")
    ap.add_argument("--out", default=str(SUBMISSION), help="submission directory")
    ap.add_argument("--slides-dir", help=("directory holding slide renders exported by hand "
                                          "(slide-1.png and slide-3.png); skips LibreOffice"))
    args = ap.parse_args()
    wanted = set(args.only or ["1", "2", "3"])
    dest_dir = Path(args.out)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if wanted & {"1", "2"}:
        if args.slides_dir:
            src = Path(args.slides_dir)
            slides = {}
            for n in (FIG1_SLIDE, FIG2_SLIDE):
                hits = sorted(src.glob(f"slide-{n}.*")) or sorted(src.glob(f"*slide*{n}*"))
                if not hits:
                    raise FileNotFoundError(
                        f"No render for slide {n} in {src}; expected slide-{n}.png"
                    )
                slides[n] = hits[0]
            if "1" in wanted:
                export_slide(slides[FIG1_SLIDE], FIG1_SIZE,
                             dest_dir / "2026GH001924_Figure_1.tif")
            if "2" in wanted:
                export_slide(slides[FIG2_SLIDE], FIG2_SIZE,
                             dest_dir / "2026GH001924_Figure_2.tif",
                             box=algorithm_crop_box())
        else:
            with tempfile.TemporaryDirectory() as td:
                slides = render_deck(Path(td))
                if "1" in wanted:
                    export_slide(slides[FIG1_SLIDE], FIG1_SIZE,
                                 dest_dir / "2026GH001924_Figure_1.tif")
                if "2" in wanted:
                    export_slide(slides[FIG2_SLIDE], FIG2_SIZE,
                                 dest_dir / "2026GH001924_Figure_2.tif",
                                 box=algorithm_crop_box())
    if "3" in wanted:
        build_figure3(dest_dir / "2026GH001924_Figure_3.tif")


if __name__ == "__main__":
    sys.exit(main())
