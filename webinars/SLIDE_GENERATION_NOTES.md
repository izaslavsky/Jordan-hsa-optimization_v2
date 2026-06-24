# Slide Generation Notes

## Recommended Tool: Gamma.app

**URL:** https://gamma.app

Gamma takes structured text or markdown as input and generates polished presentation slides with professional design. It is the most direct path from this markdown to a finished slide deck.

### How to import these slides into Gamma:

1. Go to gamma.app and sign in.
2. Click **New** → **Import** → **Paste markdown**.
3. Paste the contents of the `.md` file (one webinar at a time).
4. Gamma maps `##` headings to slide titles and body text to slide content.
5. Choose a theme. The default "Minimal" or "Slate" themes work well for academic content.
6. Edit individual slides to adjust layout, add speaker notes, or embed images.

### Gamma formatting conventions used in these files:

- `#` = presentation title (one per file)
- `##` = new slide title
- `---` = slide separator (Gamma honors these, but `##` alone is usually sufficient)
- Tables render as formatted tables on slides
- Code blocks render in monospace font

### Alternative tools:

- **Slidesgo AI** (slidesgo.com) — takes a text prompt and generates a complete deck; less control but faster
- **Beautiful.ai** — AI-assisted layout with smart templates; requires manual slide creation but produces polished results
- **MagicSlides** (magicslides.app) — Google Slides add-on; converts markdown to slides directly inside Google Slides
- **Tome** (tome.app) — AI-native presentation tool; good for narrative-heavy decks

### Speaker notes:

Each slide in these markdown files has enough bullet content for 2–3 minutes of speaking. In Gamma, add speaker notes by clicking the notes field at the bottom of each slide. The slide body should be concise talking points; speaker notes carry the full narrative.

### Image placeholders:

Where slides reference figures (maps, algorithm diagrams, RR plots), insert the corresponding outputs from `out/`:

| Slide reference | File |
|----------------|------|
| v6/v7/v8 boundary maps | `out/INF_footprint_boundary_comparison.png` |
| v7 additions map | `out/INF_footprint_v6_v7_diff.png` |
| IoU stability chart | `out/INF_footprint_iou_v6_v7.png` |
| DLNM cumulative RR | `out/dlnm/cumulative_rr_precip.png` |
| Algorithm figure | `../HSA_paper/algorithm_graphics_v5.png` |

---

## Webinar Structure Summary

| Webinar | File | Duration | Slides |
|---------|------|----------|--------|
| 1: HSA Theory | `webinar1_hsa_theory_slides.md` | 90 min | ~28 slides |
| 2: Pipeline Demo | `webinar2_pipeline_demo_slides.md` | 90 min | ~26 slides |
| 3: Climate-Health | `webinar3_climate_health_slides.md` | 90 min | ~27 slides |

Suggested timing: 2–3 min per content slide + 10–15 min Q&A + 15–20 min live demo (Webinar 2).
