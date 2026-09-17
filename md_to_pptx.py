"""
Convert a workshop slides markdown file to a PPTX presentation.

Parses the format:
    ### Slide N.M — Title
    Layout: ...
    Visual: ...
    [bullets, table rows, plain paragraphs]
    Notes: [presenter notes — may span multiple lines until next ---, ###, or ##]

Usage:
    python md_to_pptx.py <input.md> [output.pptx]
"""

import re
import sys
import os
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# ── Image paths ──────────────────────────────────────────────────────────────
_REPO     = Path(__file__).parent
FIGURES   = _REPO / "manuscript" / "figures"
CONCEPTS  = _REPO / "manuscript" / "slide_graphics"
ALGO_IMGS = Path("/tmp/algo_imgs")
OUT_MAPS  = Path(os.environ.get("HSA_OUT_DIR",
                                os.environ.get("PIPELINE_OUT_DIR", _REPO / "out")))  # noqa: hardcode - env fallback

# Map slide title → (image_path, placement)
# 'full'  = fills content area; if slide has bullets they go left, image right
# 'right' = same split behaviour but makes the intent explicit
# 'wide'  = image takes full content area even when bullets are present
IMAGE_MAP: dict[str, tuple[Path, str]] = {
    # ── Pipeline overview ────────────────────────────────────────────────────
    "Six Steps, One Script":              (FIGURES  / "fig1_pipeline.png",                "wide"),
    "Recap: Where We Are in the Pipeline":(FIGURES  / "fig1_pipeline.png",                "right"),
    "Summary and Segue":                  (FIGURES  / "fig1_pipeline.png",                "right"),

    # ── Data integration ─────────────────────────────────────────────────────
    "The Problem We Are Solving":         (OUT_MAPS / "INF_footprint_map_v7.png",         "right"),
    "Four Data Layers, Four Different Geometries":
                                          (CONCEPTS / "concept_data_layers.png",          "wide"),
    "Voronoi Tessellation: The Distance-Based Baseline":
                                          (CONCEPTS / "voronoi_catchment.png",            "right"),
    "Why Not Use Existing Methods?":      (CONCEPTS / "concept_hsa_alternatives.png",     "full"),
    "Why Administrative Units Fail":      (CONCEPTS / "jordan_governorates_map.png",      "right"),
    "What Makes a Good Spatial Unit for Climate-Health Analysis":
                                          (CONCEPTS / "concept_data_layers.png",          "right"),
    "The Resolution Mismatch in Practice":
                                          (CONCEPTS / "concept_data_layers.png",          "right"),
    "The LMIC Design Constraint":         (OUT_MAPS / "INF_footprint_map_v7.png",         "right"),

    # ── Pipeline + reproducibility ──────────────────────────────────────────
    "What Users Control":                 (CONCEPTS / "concept_composite_formula.png",   "right"),
    "Reproducibility Infrastructure":     (FIGURES  / "fig1_pipeline.png",               "right"),
    "Alternative Spatial Units":          (FIGURES  / "fig5_weekly_models.png",          "right"),

    # ── Intro slides ─────────────────────────────────────────────────────────
    "What to Expect From Today":          (FIGURES  / "fig1_pipeline.png",               "right"),
    "The Reporting Gap":                  (OUT_MAPS / "INF_footprint_map_v7.png",        "right"),
    "The Synthetic Data Note":            (FIGURES  / "fig1_pipeline.png",               "right"),
    "Between-Session Q&A":                (FIGURES  / "fig1_pipeline.png",               "right"),

    # ── GEE slides ───────────────────────────────────────────────────────────
    "Why Google Earth Engine":            (FIGURES  / "fig1_pipeline.png",               "right"),
    "Three Stages: What Runs When":       (FIGURES  / "fig1_pipeline.png",               "right"),
    "Area-Weighted Spatial Means":        (CONCEPTS / "concept_data_layers.png",         "right"),
    "Stage B Output: Weekly Polygon Climate":
                                          (FIGURES  / "fig1_pipeline.png",               "right"),
    "Stage C Output: Daily Polygon Climate":
                                          (FIGURES  / "fig1_pipeline.png",               "right"),
    "The GEE Phase Dependency":           (FIGURES  / "fig1_pipeline.png",               "right"),
    "Climate Products Used":              (CONCEPTS / "concept_data_layers.png",         "right"),
    "Local vs. Cloud GEE Notebooks":      (FIGURES  / "fig1_pipeline.png",               "right"),
    "Live Demo: GEE_local_Climate_Features_by_Facilities.ipynb":
                                          (CONCEPTS / "concept_data_layers.png",         "right"),
    "Live Demo: HSA_FINAL.ipynb":         (CONCEPTS / "panel_v8.png",                   "right"),

    # ── Optimization modes ───────────────────────────────────────────────────
    "The Five Optimization Modes":        (ALGO_IMGS / "slide4_rId2.png",                "full"),

    # ── HSA algorithm versions ───────────────────────────────────────────────
    "Why Greedy Optimization":            (CONCEPTS / "concept_composite_formula.png",   "wide"),
    "The Composite Score Formula":        (CONCEPTS / "concept_composite_formula.png",   "wide"),
    "Service Radius Calibration":         (CONCEPTS / "concept_service_radius.png",      "wide"),
    "The Selection Loop":                 (CONCEPTS / "concept_selection_loop.png",      "wide"),
    "v6 Result for Jordan":               (CONCEPTS / "panel_v6.png",                    "right"),
    "v7 Anchor Quality Control":          (CONCEPTS / "panel_v7.png",                    "right"),
    "v8 Satellite Bubbles":               (CONCEPTS / "panel_v8.png",                    "right"),
    "v6, v7, v8: Side-by-Side Comparison":(OUT_MAPS / "INF_footprint_boundary_comparison.png", "full"),

    # ── Gravity model ────────────────────────────────────────────────────────
    "Why Not Just Count Population Inside the Polygon":
                                          (CONCEPTS / "concept_pop_allocation_2step.png", "wide"),
    "Gravity Model: Three Cases":         (CONCEPTS / "concept_gravity_model.png",        "right"),
    "Gravity Model Parameters":           (CONCEPTS / "concept_gravity_model.png",        "right"),
    "Allocation Results for Jordan v7":   (OUT_MAPS / "INF_footprint_map_v7.png",         "right"),
    "Sanitation Coverage: The Effect Modifier":
                                          (FIGURES  / "fig3_population_sanitation.png",  "right"),

    # ── Panel data and modeling ──────────────────────────────────────────────
    "The Panel Data Structure":           (CONCEPTS / "concept_panel_data.png",          "wide"),
    "Allocating Disease Counts to HSAs":  (CONCEPTS / "concept_pop_allocation_2step.png", "wide"),
    "Feature Construction":               (CONCEPTS / "concept_panel_data.png",          "right"),
    "The Modeling Hierarchy":             (FIGURES  / "fig5_weekly_models.png",          "right"),
    "Variance Decomposition":             (FIGURES  / "fig5_weekly_models.png",          "right"),
    "The Spatial Unit Result":            (FIGURES  / "fig5_weekly_models.png",          "right"),
    "Machine Learning Results":           (FIGURES  / "fig5_weekly_models.png",          "right"),

    # ── DLNM setup ───────────────────────────────────────────────────────────
    "Beyond Single-Lag Associations: The DLNM Motivation":
                                          (CONCEPTS / "concept_cross_basis.png",         "wide"),
    "Lag Construction":                   (CONCEPTS / "concept_cross_basis.png",         "right"),
    "The Sanitation Interaction Hypothesis":
                                          (FIGURES  / "fig3_population_sanitation.png",  "right"),
    "The Daily Baseline Model Design":    (CONCEPTS / "concept_panel_data.png",          "right"),

    # ── DLNM results ─────────────────────────────────────────────────────────
    "Track A vs. Track B: Two Different Questions":
                                          (FIGURES  / "fig5_weekly_models.png",          "right"),
    "The Cross-Basis Concept":            (CONCEPTS / "concept_cross_basis.png",         "wide"),
    "Reading a 3D DLNM Surface":          (FIGURES  / "fig4_dlnm_3d.png",                "right"),
    "Expected Results Preview":           (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "Live Demo: run_climate_health_modeling.ipynb":
                                          (FIGURES  / "fig5_weekly_models.png",          "right"),
    "Precipitation × Sanitation: The Key Result":
                                          (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "What Weekly Results Tell Us About Daily DLNM":
                                          (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "DTR: Four Epidemiological Pathways": (CONCEPTS / "concept_dtr_mechanisms.png",      "full"),
    "Temperature: The Direct Pathway":    (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "Track A and Track B Are Compatible": (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "Residual Diagnostics":               (FIGURES  / "fig5_weekly_models.png",          "right"),
    "Live Demo: run_climate_models_daily.ipynb":
                                          (FIGURES  / "fig6_daily_dlnm.png",             "right"),
    "Track B: The Forecasting Setup and Result":
                                          (FIGURES  / "fig6_daily_dlnm.png",             "right"),

    # ── Sensitivity analysis ─────────────────────────────────────────────────
    "Overview of Sensitivity Analysis Suite":
                                          (CONCEPTS / "concept_composite_formula.png",  "right"),
    "Gravity Parameter Sensitivity":      (CONCEPTS / "concept_gravity_model.png",       "right"),
    "Alternative Spatial Unit Comparison":(FIGURES  / "fig5_weekly_models.png",          "right"),
    "Multi-Objective Weight Perturbation":(CONCEPTS / "concept_composite_formula.png",  "right"),
    "Adapting the Sensitivity Suite to a New Country":
                                          (OUT_MAPS / "INF_footprint_map_v7.png",        "right"),

    # ── HEFTE ────────────────────────────────────────────────────────────────
    "Six Linked Views":                   (CONCEPTS / "hefte_four_views.png",            "full"),
    "Pipeline Outputs → HEFTE":           (FIGURES  / "fig7_hefte.png",                  "right"),
    "What HEFTE Is":                      (FIGURES  / "fig7_hefte.png",                  "wide"),
    "Live Demo Walkthrough":              (FIGURES  / "fig7_hefte.png",                  "right"),

    # ── Conclusions ──────────────────────────────────────────────────────────
    "Key Conclusions":                    (FIGURES  / "fig2_hsa_maps.png",               "right"),
    "What This Enables":                  (FIGURES  / "fig7_hefte.png",                  "right"),
    "Open Questions":                     (FIGURES  / "fig2_hsa_maps.png",               "right"),
}

# ── Colour palette ──────────────────────────────────────────────────────────
C_TITLE      = RGBColor(0x1A, 0x37, 0x5E)   # dark navy
C_ACCENT     = RGBColor(0x2E, 0x86, 0xC1)   # mid blue
C_BODY       = RGBColor(0x1C, 0x1C, 0x1C)   # near-black
C_MUTED      = RGBColor(0x55, 0x55, 0x55)   # grey for visual cue
C_TABLE_HDR  = RGBColor(0x2E, 0x86, 0xC1)
C_TABLE_ROW1 = RGBColor(0xEB, 0xF5, 0xFB)
C_TABLE_ROW2 = RGBColor(0xF8, 0xF9, 0xF9)
C_WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
C_CODE_BG    = RGBColor(0xF2, 0xF3, 0xF4)

# ── Slide dimensions (widescreen 16:9, exact standard EMU values) ────────────
SLIDE_W = Emu(12192000)   # 40/3 inches  (PowerPoint standard)
SLIDE_H = Emu(6858000)    # 7.5 inches

# ── Font sizes ───────────────────────────────────────────────────────────────
FS_TITLE    = Pt(28)
FS_SUBTITLE = Pt(14)
FS_BODY     = Pt(16)
FS_SMALL    = Pt(13)
FS_TABLE    = Pt(12)
FS_VISUAL   = Pt(11)

# ── Layout margin ────────────────────────────────────────────────────────────
M = Inches(0.55)   # left/right margin
TOP_BAND = Inches(1.15)   # height of the title band


# ─────────────────────────────────────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────────────────────────────────────

def parse_slides(md_text: str) -> list[dict]:
    """
    Return a list of slide dicts:
        title, layout, visual, content_lines, notes, section, webinar
    """
    slides = []
    current_webinar = ""
    current_section = ""

    # Split on slide-level separators
    # A slide starts at a "### Slide" heading
    slide_re = re.compile(r'^### Slide\s+[\d.]+\s+[—–-]+\s+(.+)$', re.MULTILINE)

    # Track webinar and section headers
    webinar_re  = re.compile(r'^# (WEBINAR \d+.*)', re.MULTILINE)
    section_re  = re.compile(r'^## (PART \d+.*?)(?:\s*\(.*?\))?\s*$', re.MULTILINE)

    # Find all positions of slide headers + metadata headers
    events = []
    for m in webinar_re.finditer(md_text):
        events.append(('webinar', m.start(), m.group(1).strip()))
    for m in section_re.finditer(md_text):
        events.append(('section', m.start(), m.group(1).strip()))
    for m in slide_re.finditer(md_text):
        events.append(('slide', m.start(), m.group(1).strip(), m.end()))
    events.sort(key=lambda e: e[1])

    # Walk events to build slide records
    slide_starts = [(i, e) for i, e in enumerate(events) if e[0] == 'slide']

    for idx, (ev_idx, event) in enumerate(slide_starts):
        title    = event[2]
        body_start = event[3]  # character position right after the ### line

        # Determine end of this slide's body
        if idx + 1 < len(slide_starts):
            body_end = slide_starts[idx + 1][1][1]  # start of next slide event
        else:
            body_end = len(md_text)

        body = md_text[body_start:body_end]

        # Find the most recent webinar/section before this slide
        wbn = ""
        sec = ""
        for e in events[:ev_idx + 1]:
            if e[0] == 'webinar':
                wbn = e[2]
            elif e[0] == 'section':
                sec = e[2]

        slide = _parse_slide_body(title, body)
        slide['webinar']  = wbn
        slide['section']  = sec
        slides.append(slide)

    return slides


def _parse_slide_body(title: str, body: str) -> dict:
    lines = body.split('\n')

    layout  = ""
    visual  = ""
    notes   = ""
    content_lines = []

    # State machine
    in_notes = False
    notes_lines = []

    for line in lines:
        stripped = line.rstrip()

        # Skip horizontal rules that mark slide boundaries
        if stripped in ('---', '----'):
            continue

        # Layout line (only at the very start)
        if not layout and stripped.lower().startswith('layout:'):
            layout = stripped[len('layout:'):].strip()
            continue

        # Visual line
        if not visual and stripped.lower().startswith('visual:'):
            visual = stripped[len('visual:'):].strip()
            continue

        # Notes line — everything from here to end of block
        if stripped.lower().startswith('notes:'):
            in_notes = True
            rest = stripped[len('notes:'):].strip()
            if rest:
                notes_lines.append(rest)
            continue

        if in_notes:
            notes_lines.append(stripped)
        else:
            content_lines.append(stripped)

    notes = ' '.join(notes_lines).strip()
    # Trim trailing blank lines from content
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    return {
        'title':         title,
        'layout':        layout,
        'visual':        visual,
        'content_lines': content_lines,
        'notes':         notes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT CLASSIFIERS
# ─────────────────────────────────────────────────────────────────────────────

def is_table_row(line: str) -> bool:
    return line.strip().startswith('|') and '|' in line[1:]

def is_separator_row(line: str) -> bool:
    return bool(re.match(r'^\|[-| :]+\|$', line.strip()))

def parse_table(content_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) from markdown table lines."""
    table_lines = [l for l in content_lines if is_table_row(l) and not is_separator_row(l)]
    if not table_lines:
        return [], []
    def split_row(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]
    headers = split_row(table_lines[0])
    rows    = [split_row(l) for l in table_lines[1:]]
    return headers, rows

def is_bullet(line: str) -> bool:
    return line.strip().startswith('•') or line.strip().startswith('-')

def clean_markdown_bold(text: str) -> str:
    """Strip **bold** markers for plain-text rendering in PPTX."""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text)

def clean_inline(text: str) -> str:
    """Remove markdown bold, code backticks, and link syntax for display."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # bold
    text = re.sub(r'`(.+?)`', r'\1', text)           # inline code
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)  # links
    return text

def extract_bullets(content_lines: list[str]) -> list[str]:
    bullets = []
    for line in content_lines:
        s = line.strip()
        if is_bullet(s):
            text = s.lstrip('•').lstrip('-').strip()
            bullets.append(clean_inline(text))
        elif s and not is_table_row(s):
            bullets.append(clean_inline(s))
    return [b for b in bullets if b]


# ─────────────────────────────────────────────────────────────────────────────
# PPTX HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def blank_slide(prs: Presentation) -> object:
    """Add a blank slide (no placeholders) and return it."""
    blank_layout = prs.slide_layouts[6]  # Blank
    return prs.slides.add_slide(blank_layout)


def add_title_band(slide, title: str, section: str = "", webinar: str = "") -> None:
    """Draw the dark title band across the top."""
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.text import PP_ALIGN

    # Background rectangle
    bg = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Emu(0), Emu(0), SLIDE_W, TOP_BAND
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = C_TITLE
    bg.line.fill.background()

    # Title text box inside the band
    txb = slide.shapes.add_textbox(M, Inches(0.12), SLIDE_W - 2 * M, TOP_BAND - Inches(0.12))
    tf  = txb.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = clean_inline(title)
    run.font.size  = FS_TITLE
    run.font.bold  = True
    run.font.color.rgb = C_WHITE

    # Webinar / section label (small, right-aligned)
    if section or webinar:
        label = f"{webinar}  ·  {section}" if (webinar and section) else (webinar or section)
        ltxb = slide.shapes.add_textbox(
            M, Inches(0.83), SLIDE_W - 2 * M, Inches(0.30)
        )
        ltf = ltxb.text_frame
        lp  = ltf.paragraphs[0]
        lp.alignment = PP_ALIGN.RIGHT
        lr = lp.add_run()
        lr.text = label
        lr.font.size = Pt(9)
        lr.font.color.rgb = RGBColor(0xA9, 0xCC, 0xE3)


def add_visual_cue(slide, visual: str) -> None:
    """Add the visual description as a small grey italic note at the bottom."""
    if not visual or visual.lower() in ('none', 'none — clean text only', 'none — conversational slide'):
        return
    txb = slide.shapes.add_textbox(
        M,
        SLIDE_H - Inches(0.38),
        SLIDE_W - 2 * M,
        Inches(0.34)
    )
    tf = txb.text_frame
    p  = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = f"[Visual: {visual[:160]}{'…' if len(visual) > 160 else ''}]"
    run.font.size   = Pt(8)
    run.font.italic = True
    run.font.color.rgb = C_MUTED


def add_image_shape(slide, img_path: Path,
                    left, top, max_width, max_height) -> None:
    """Add an image maintaining aspect ratio within the given bounding box.

    Uses PIL to pre-calculate the final size so add_picture is called exactly
    once with explicit dimensions — avoids the two-pass remove/re-add that
    can corrupt the PPTX XML.
    """
    from PIL import Image as _PIL
    try:
        with _PIL.open(str(img_path)) as im:
            iw, ih = im.size
    except Exception:
        # Fallback: add with width constraint and hope it fits
        slide.shapes.add_picture(str(img_path), left, top, max_width)
        return

    img_aspect   = iw / ih
    box_aspect   = max_width / max_height

    if img_aspect >= box_aspect:
        # Image is wider relative to box — constrain by width
        final_w = int(max_width)
        final_h = int(max_width / img_aspect)
    else:
        # Image is taller — constrain by height
        final_h = int(max_height)
        final_w = int(max_height * img_aspect)

    # Centre within the allocated area
    actual_left = int(left + (max_width  - final_w) // 2)
    actual_top  = int(top  + (max_height - final_h) // 2)

    slide.shapes.add_picture(str(img_path), actual_left, actual_top,
                             final_w, final_h)


def add_bullets_box(slide, bullets: list[str],
                    top=None, height=None, font_size=None,
                    left=None, width=None) -> None:
    """Add a bullet list in the main content area."""
    t   = top   if top   is not None else (TOP_BAND + Inches(0.2))
    h   = height if height is not None else (SLIDE_H - t - Inches(0.45))
    fs  = font_size or FS_BODY
    l   = left  if left  is not None else M
    w   = width if width is not None else (SLIDE_W - 2 * M)
    txb = slide.shapes.add_textbox(l, t, w, h)
    tf  = txb.text_frame
    tf.word_wrap = True

    first = True
    for bullet in bullets:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_before = Pt(4)
        run = p.add_run()

        # Detect sub-bullets (two spaces indent in source)
        is_sub = bullet.startswith('  ')
        bullet  = bullet.strip()

        p.level = 1 if is_sub else 0
        run.text = f"• {bullet}" if not is_sub else f"  – {bullet}"
        run.font.size      = fs if not is_sub else Pt(fs.pt - 2)
        run.font.color.rgb = C_BODY


def add_table_shape(slide, headers: list[str], rows: list[list[str]],
                    top=None, height=None) -> None:
    """Render a markdown table as a proper PPTX table."""
    from pptx.util import Pt
    t = top or (TOP_BAND + Inches(0.25))
    h = height if height is not None else (SLIDE_H - t - Inches(0.45))

    ncols  = len(headers)
    nrows  = len(rows) + 1          # +1 for header row
    col_w  = (SLIDE_W - 2 * M) / ncols

    tbl = slide.shapes.add_table(
        nrows, ncols,
        M, t,
        SLIDE_W - 2 * M, h
    ).table

    # Set uniform column widths
    for ci in range(ncols):
        tbl.columns[ci].width = int(col_w)

    def set_cell(row, col, text, bold=False, bg=None, font_size=None):
        cell = tbl.cell(row, col)
        cell.text = clean_inline(text)
        tf = cell.text_frame
        for para in tf.paragraphs:
            for run in para.runs:
                run.font.size  = font_size or FS_TABLE
                run.font.bold  = bold
                run.font.color.rgb = C_WHITE if bold else C_BODY
        if bg:
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg

    # Header row
    for ci, hdr in enumerate(headers):
        set_cell(0, ci, hdr, bold=True, bg=C_TABLE_HDR)

    # Data rows
    for ri, row in enumerate(rows):
        bg = C_TABLE_ROW1 if ri % 2 == 0 else C_TABLE_ROW2
        for ci in range(ncols):
            val = row[ci] if ci < len(row) else ""
            set_cell(ri + 1, ci, val, bg=bg)


def set_notes(slide, notes_text: str) -> None:
    """Write presenter notes into the slide notes pane."""
    if not notes_text:
        return
    notes_slide = slide.notes_slide
    tf = notes_slide.notes_text_frame
    tf.text = notes_text


# ─────────────────────────────────────────────────────────────────────────────
# SECTION TITLE SLIDE
# ─────────────────────────────────────────────────────────────────────────────

def add_section_slide(prs: Presentation, webinar: str, section: str) -> None:
    slide = blank_slide(prs)

    # Full-width accent strip
    bg = slide.shapes.add_shape(1, Emu(0), Emu(0), SLIDE_W, SLIDE_H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = C_TITLE
    bg.line.fill.background()

    # Webinar label
    w_txb = slide.shapes.add_textbox(Inches(1), Inches(2.0), SLIDE_W - Inches(2), Inches(0.6))
    w_tf  = w_txb.text_frame
    wp    = w_tf.paragraphs[0]
    wp.alignment = PP_ALIGN.CENTER
    wr = wp.add_run()
    wr.text = webinar
    wr.font.size  = Pt(18)
    wr.font.color.rgb = RGBColor(0xA9, 0xCC, 0xE3)

    # Section title
    s_txb = slide.shapes.add_textbox(Inches(1), Inches(2.7), SLIDE_W - Inches(2), Inches(1.4))
    s_tf  = s_txb.text_frame
    s_tf.word_wrap = True
    sp    = s_tf.paragraphs[0]
    sp.alignment = PP_ALIGN.CENTER
    sr = sp.add_run()
    sr.text = section
    sr.font.size  = Pt(32)
    sr.font.bold  = True
    sr.font.color.rgb = C_WHITE


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_slide(prs: Presentation, slide_data: dict) -> None:
    slide   = blank_slide(prs)
    title   = slide_data['title']
    visual  = slide_data['visual']
    lines   = slide_data['content_lines']
    notes   = slide_data['notes']
    section = slide_data.get('section', '')
    webinar = slide_data.get('webinar', '')

    add_title_band(slide, title, section, webinar)

    # ── Content geometry ────────────────────────────────────────────────────
    CONTENT_TOP = TOP_BAND + Inches(0.2)
    CONTENT_H   = SLIDE_H - CONTENT_TOP - Inches(0.45)
    CONTENT_W   = SLIDE_W - 2 * M

    has_table   = any(is_table_row(l) for l in lines if not is_separator_row(l))
    bullets_all = extract_bullets(
        [l for l in lines if not is_table_row(l) and not is_separator_row(l) and l.strip()]
    )

    # ── Resolve image ────────────────────────────────────────────────────────
    img_entry   = IMAGE_MAP.get(title)
    img_path    = None
    img_place   = "full"

    if img_entry:
        candidate, img_place = img_entry
        if candidate.exists():
            img_path = candidate

    # ── Content area constants ────────────────────────────────────────────────
    GAP          = Inches(0.18)
    BULLET_W     = Inches(5.0)              # left column, normal split
    BULLET_W_WIDE = Inches(3.6)             # left column, wide-image split
    IMG_W        = CONTENT_W - BULLET_W - GAP
    IMG_W_WIDE   = CONTENT_W - BULLET_W_WIDE - GAP

    # ── Layout with image ────────────────────────────────────────────────────
    if img_path:
        is_wide = (img_place == "wide")

        if has_table:
            # Image fills upper 45 %; table below with explicit height constraint.
            IMG_H    = int(CONTENT_H * 0.45)
            TBL_TOP  = int(CONTENT_TOP + IMG_H + Inches(0.08))

            add_image_shape(slide, img_path,
                            M, CONTENT_TOP, CONTENT_W, IMG_H)

            if bullets_all:
                add_bullets_box(slide, bullets_all,
                                top=TBL_TOP, height=Inches(0.50),
                                font_size=FS_SMALL)
                TBL_TOP = int(TBL_TOP + Inches(0.55))

            tbl_h = int(SLIDE_H - TBL_TOP - Inches(0.45))
            headers, rows = parse_table(lines)
            if headers:
                add_table_shape(slide, headers, rows, top=TBL_TOP, height=tbl_h)

        elif bullets_all:
            # Split layout: bullets left, image right.
            # 'wide' gives the image a larger right column.
            bw = BULLET_W_WIDE if is_wide else BULLET_W
            iw = IMG_W_WIDE    if is_wide else IMG_W
            fs = FS_SMALL      if is_wide else FS_SMALL

            add_bullets_box(slide, bullets_all,
                            top=CONTENT_TOP, height=CONTENT_H,
                            font_size=fs, left=M, width=bw)
            add_image_shape(slide, img_path,
                            left=M + bw + GAP, top=CONTENT_TOP,
                            max_width=iw, max_height=CONTENT_H)

        else:
            # No bullets — image fills the full content area.
            add_image_shape(slide, img_path,
                            M, CONTENT_TOP, CONTENT_W, CONTENT_H)

    # ── Layout without image ──────────────────────────────────────────────────
    else:
        if has_table:
            pre_table   = [l for l in lines
                           if not is_table_row(l) and not is_separator_row(l) and l.strip()]
            bullets_pre = extract_bullets(pre_table)

            if bullets_pre:
                add_bullets_box(slide, bullets_pre,
                                top=CONTENT_TOP,
                                height=Inches(0.85),
                                font_size=FS_SMALL)
                table_top = int(CONTENT_TOP + Inches(0.9))
            else:
                table_top = CONTENT_TOP

            tbl_h = int(SLIDE_H - table_top - Inches(0.45))
            headers, rows = parse_table(lines)
            if headers:
                add_table_shape(slide, headers, rows, top=table_top, height=tbl_h)

        else:
            bullets = extract_bullets(lines)
            if bullets:
                # Adaptive font: fewer bullets → larger text to fill the slide
                n = len(bullets)
                if n <= 3:
                    fs = Pt(22)
                elif n <= 5:
                    fs = Pt(19)
                else:
                    fs = FS_BODY
                add_bullets_box(slide, bullets, font_size=fs)

    # Only show the textual visual cue when no real image was embedded.
    if not img_path:
        add_visual_cue(slide, visual)
    set_notes(slide, notes)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def _fix_notes_master(pptx_path: Path) -> None:
    """Insert missing <p:notesMasterIdLst> into presentation.xml.

    python-pptx adds the notesMaster to the rels file but omits the
    <p:notesMasterIdLst> element in presentation.xml body, causing
    PowerPoint to flag the file as needing repair.
    """
    import zipfile, shutil, io

    with zipfile.ZipFile(pptx_path, 'r') as zin:
        # Find notesMaster rId from presentation rels
        rels_raw = zin.read('ppt/_rels/presentation.xml.rels')
        import xml.etree.ElementTree as _ET
        rels = _ET.fromstring(rels_raw)
        notes_rId = None
        for rel in rels:
            if 'notesMaster' in rel.get('Type', ''):
                notes_rId = rel.get('Id')
                break
        if not notes_rId:
            return  # no notesMaster, nothing to fix

        prs_raw = zin.read('ppt/presentation.xml').decode('utf-8')
        if 'notesMasterIdLst' in prs_raw:
            return  # already present

        # Insert after </p:sldMasterIdLst> and before <p:sldIdLst>
        insert_xml = (
            f'<p:notesMasterIdLst xmlns:p="http://schemas.openxmlformats.org/'
            f'presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships">'
            f'<p:notesMasterId r:id="{notes_rId}"/></p:notesMasterIdLst>'
        )
        prs_fixed = prs_raw.replace(
            '</p:sldMasterIdLst><p:sldIdLst>',
            f'</p:sldMasterIdLst>{insert_xml}<p:sldIdLst>'
        )
        if prs_fixed == prs_raw:
            return  # pattern not found — leave as-is

        # Rewrite the ZIP in a temp buffer
        buf = io.BytesIO()
        with zipfile.ZipFile(pptx_path, 'r') as zin2, \
             zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin2.infolist():
                if item.filename == 'ppt/presentation.xml':
                    zout.writestr(item, prs_fixed.encode('utf-8'))
                else:
                    zout.writestr(item, zin2.read(item.filename))

    pptx_path.write_bytes(buf.getvalue())


def build_pptx(md_path: Path, out_path: Path) -> None:
    md_text = md_path.read_text(encoding='utf-8')
    slides  = parse_slides(md_text)

    prs = Presentation()
    prs.slide_width  = SLIDE_W
    prs.slide_height = SLIDE_H

    # Track section breaks to insert divider slides
    last_section = None
    last_webinar = None

    for sd in slides:
        section_changed = (sd['section'] != last_section or sd['webinar'] != last_webinar)
        if section_changed and (sd['section'] or sd['webinar']):
            add_section_slide(prs, sd['webinar'], sd['section'])
            last_section = sd['section']
            last_webinar = sd['webinar']

        render_slide(prs, sd)

    prs.save(str(out_path))
    _fix_notes_master(out_path)
    print(f"Saved {len(slides)} slides → {out_path}")
    print(f"Section dividers inserted: {sum(1 for sd in slides if sd['section'])}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python md_to_pptx.py <input.md> [output.pptx]")
        sys.exit(1)

    md_path  = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else md_path.with_suffix('.pptx')

    if not md_path.exists():
        print(f"Error: {md_path} not found")
        sys.exit(1)

    build_pptx(md_path, out_path)
