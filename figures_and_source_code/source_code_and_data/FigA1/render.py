"""Assemble paper Figure A1 from the two comparison strips in this folder."""
from pathlib import Path
import json
import re
import string

from matplotlib import font_manager
from pypdf import PdfReader, PdfWriter, PageObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from paper_plot_style import FONT_SIZE_PT, SUBPLOT_LABEL_GAP_MM, subplot_label_anchor_centers


def _overlap(first, second):
    return (max(first[0], second[0]) < min(first[2], second[2])
            and max(first[1], second[1]) < min(first[3], second[3]))


def render_publication(root, group, sections, target):
    """Preserve A1's native strip geometry and 5 mm gap between plot rows."""
    from build_publication_figures import MM, register_font, drawing_page, add_at

    if group != "FigA1":
        raise ValueError(f"Unsupported figure: {group}")
    root = Path(root)
    register_font()
    italic_font = "TimesNewRomanItalic"
    if italic_font not in pdfmetrics.getRegisteredFontNames():
        properties = font_manager.FontProperties(family="Times New Roman", style="italic")
        pdfmetrics.registerFont(TTFont(italic_font,
                                      font_manager.findfont(properties, fallback_to_default=False)))
    sources = [root / "附录图/FigA1/figures" / name
               for name in ("compare_alpha_distribution.pdf", "compare_m_distribution.pdf")]
    strip_heights = [float(PdfReader(source).pages[0].mediabox.height) / MM for source in sources]
    audit = {Path(item["stem"]).resolve(): item for item in
             (json.loads(line) for line in (root / "交付/绘图样式审计.jsonl").read_text(encoding="utf-8").splitlines())}
    row_panels = [audit[source.with_suffix("").resolve()]["axes"] for source in sources]
    plot_height_mm, row_gap_mm = 32.0, 5.0
    # Overlap the strips' blank margins to keep only 5 mm between the plots.
    strip_y = [max(panel["axes_top_mm"] for panel in row_panels[1]) + row_gap_mm
               - min(panel["axes_top_mm"] - plot_height_mm for panel in row_panels[0]), 0]
    height = max(y + strip_height for y, strip_height in zip(strip_y, strip_heights))
    page = PageObject.create_blank_page(width=160 * MM, height=height * MM)
    # Draw the upper strip last so the lower strip's white page background
    # cannot cover the upper plots when their blank margins overlap.
    for i in (1, 0):
        add_at(page, sources[i], 0, strip_y[i])

    plot_bounds = [
        [[panel["axes_left_mm"], strip_y[row] + panel["axes_top_mm"] - plot_height_mm,
          panel["axes_left_mm"] + 44, strip_y[row] + panel["axes_top_mm"]]
         for panel in panels]
        for row, panels in enumerate(row_panels)]
    tags, titles = [], []

    def draw_centered(doc, parts, center, baseline):
        width = sum(pdfmetrics.stringWidth(text, font, FONT_SIZE_PT) for font, text in parts)
        y0 = min(pdfmetrics.getDescent(font, FONT_SIZE_PT) for font, _ in parts)
        y1 = max(pdfmetrics.getAscent(font, FONT_SIZE_PT) for font, _ in parts)
        x = center * MM - width / 2
        mark = doc.beginText(x, baseline)
        for font, text in parts:
            mark.setFont(font, FONT_SIZE_PT)
            mark.textOut(text)
        doc.drawText(mark)
        return [coord / MM for coord in (x, baseline + y0, x + width, baseline + y1)]

    def draw_labels(doc):
        roman_font = "TimesNewRoman"
        descent_pt = pdfmetrics.getDescent(roman_font, FONT_SIZE_PT)
        for row, panels in enumerate(row_panels):
            centers = subplot_label_anchor_centers(plot_bounds[row])
            for column, panel in enumerate(panels):
                left, _, right, top = plot_bounds[row][column]
                tag = string.ascii_lowercase[row * 3 + column]
                tags.append(draw_centered(doc, [(roman_font, f"({tag})")], centers[column],
                                          (top + SUBPLOT_LABEL_GAP_MM) * MM - descent_pt))
                title = panel.get("scientific_title", "")
                match = re.fullmatch(r"η = (.+), m = (.+)", title)
                if match is None:
                    raise ValueError(f"Missing parameters for FigA1({tag}); regenerate the strips")
                eta, m = match.groups()
                parts = [(italic_font, "η"), (roman_font, f" = {eta}, "),
                         (italic_font, "m"), (roman_font, f" = {m}")]
                bounds = draw_centered(doc, parts, (left + right) / 2, top * MM + 3.6)
                titles.append({"panel": tag, "text": title, "bounds_mm": bounds})

    page.merge_page(drawing_page(160 * MM, height * MM, draw_labels))
    violations = []
    for index, title in enumerate(titles):
        bounds = title["bounds_mm"]
        if not (0 <= bounds[0] < bounds[2] <= 160 and 0 <= bounds[1] < bounds[3] <= height):
            violations.append(f"Title outside canvas: {title['panel']}")
        if any(_overlap(bounds, other) for other in [*tags, *plot_bounds[0], *plot_bounds[1]]):
            violations.append(f"Title overlaps a subplot label or plot: {title['panel']}")
        if any(_overlap(bounds, other["bounds_mm"]) for other in titles[index + 1:]):
            violations.append(f"Titles overlap: {title['panel']}")
    report_path = root / "交付/FigA1参数标题检查.json"
    report_path.write_text(json.dumps({"font_size_pt": FONT_SIZE_PT,
                                      "parameter_titles": titles, "violations": violations},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    if violations:
        raise ValueError(f"FigA1 layout check failed: {violations}")
    target = Path(target) if target else root / "交付/论文插图/FigA1_publication.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_page(page)
    writer.write(target)
    return target, [{"source": p.relative_to(root).as_posix(), "scale": 1.0} for p in sources]
