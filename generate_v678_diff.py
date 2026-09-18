"""
Generate an annotated v6/v7/v8 comparison figure from fig2_hsa_maps.png.
Splits the three-panel image and adds change annotations below each panel.
Output: manuscript/figures/fig2_v678_annotated.png
"""

from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

FIGURES = Path("manuscript/figures")
SRC = FIGURES / "fig2_hsa_maps.png"
OUT = FIGURES / "fig2_v678_annotated.png"

img_pil = Image.open(SRC)
img = np.array(img_pil)
H, W = img.shape[:2]

# The three panels are roughly equal thirds.  Trim 1-pixel seams.
p = W // 3
panels_px = [(0, p), (p, 2 * p), (2 * p, W)]

panel_meta = [
    {
        "version":  "v6  —  Greedy Baseline",
        "stats":    "17 anchors  ·  90.6% pop. coverage",
        "changes":  [],
        "note":     "Greedy multi-objective selection only\n"
                    "Southern Jordan partially uncovered",
    },
    {
        "version":  "v7  —  Anchor QC",
        "stats":    "19 anchors  ·  98.0% pop. coverage",
        "changes":  ["2 redundant anchors demoted", "4 underserved facilities promoted"],
        "note":     "Net +2 anchors after QC\n"
                    "+7.4 pp population coverage gain",
    },
    {
        "version":  "v8  —  Satellite Bubbles",
        "stats":    "19 anchors + satellites  ·  98.0% coverage",
        "changes":  ["Secondary polygons around non-anchor facilities",
                     "13 of 19 anchors have at least one satellite"],
        "note":     "Same anchor set as v7\n"
                    "Adds sub-HSA spatial granularity",
    },
]

NAVY   = "#1A375E"
RED    = "#CC3300"
LIGHT  = "#FFF3F3"
BGWHITE = "white"

fig, axes = plt.subplots(1, 3, figsize=(18, 9.5),
                          gridspec_kw={"wspace": 0.06})
fig.patch.set_facecolor(BGWHITE)

for ax, (x0, x1), meta in zip(axes, panels_px, panel_meta):
    sub = img[:, x0:x1, :]
    ax.imshow(sub, aspect="auto")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(
        f"{meta['version']}\n{meta['stats']}",
        fontsize=12.5, fontweight="bold", color=NAVY, pad=7,
        linespacing=1.45,
    )

    if meta["changes"]:
        change_text = "\n".join(f"▲ {c}" for c in meta["changes"])
        ax.text(
            0.5, -0.01, change_text,
            transform=ax.transAxes,
            ha="center", va="top",
            fontsize=10.5, color=RED, linespacing=1.55,
            bbox=dict(boxstyle="round,pad=0.45", facecolor=LIGHT,
                      edgecolor=RED, linewidth=1.4),
        )
    else:
        ax.text(
            0.5, -0.01,
            meta["note"],
            transform=ax.transAxes,
            ha="center", va="top",
            fontsize=10, color="#555555", linespacing=1.45,
            style="italic",
        )

# Shared change-arrow legend below the middle panel
fig.text(
    0.5, 0.01,
    "Change annotations (red) show modifications relative to the previous version.",
    ha="center", va="bottom", fontsize=9.5, color="#777777",
)

plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=BGWHITE)
print(f"Saved → {OUT}")
