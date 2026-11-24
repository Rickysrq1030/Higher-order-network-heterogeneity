"""Render Figure 2 with unchanged global curves and supplied type boxplots."""
import json
import re
import string
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from paper_plot_style import (
    DPI, LINE_WIDTH_PT, MARKER_SIZE_PT, DEFAULT_TICK_PAD_PT,
    configure_style, figure_data_digest, _apply_figure_style, align_subplot_labels,
)
from figure_render_checks import (
    _check_cached_semantics, _check_line_grid_layout, _inset_terminal_ticklabels,
)
from paper_boxplots import load_box_data, draw_box_panel, add_box_legend



def render_publication(root, group, sections, target):
    if group != "Fig2" or len(sections) != 1 or sections[0][1]:
        raise ValueError(f"Unsupported line grid: {group}")
    panels = sections[0][0]
    if len(panels) != 5:
        raise ValueError(f"Unexpected panel count: {group}")
    configure_style()
    width, height = 160.0, 92.5
    plot_width, plot_height = 24.4, 30.0
    fig = plt.figure(figsize=(width/25.4, height/25.4))
    axes, tags, placements, checks, p_values = [], [], [], [], []
    legend_handles, entries = None, None
    for index, panel in enumerate(panels):
        row, column = 0, index
        left = 14.0 + 25.9*column
        bottom = 56.5
        show_x = True
        show_xlabel = column == 2
        show_y = column == 0
        metadata = json.loads(panel.with_suffix(".json").read_text(encoding="utf-8"))
        data = metadata["plot_data"]
        match = re.search(r"P_l\s*=\s*([\d.]+)", data["scientific_title"])
        if match is None:
            raise ValueError(f"Missing link-player proportion in {panel}")
        p_values.append(float(match.group(1)))
        if data["images"]:
            raise ValueError("Line grids must contain only cached line arrays")
        ax = fig.add_axes([left/width, bottom/height, plot_width/width, plot_height/height])
        axes.append(ax)
        for line in data["lines"]:
            ax.plot(line["x"], line["y"], color=line["color"], marker=line["marker"],
                    linestyle=line["linestyle"], label=line["label"],
                    linewidth=LINE_WIDTH_PT, markersize=MARKER_SIZE_PT,
                    markeredgewidth=LINE_WIDTH_PT, markerfacecolor=line["markerfacecolor"],
                    markevery=line["markevery"])
        # Preserve the original locator convention without expanding real bounds.
        ax.set_xticks([0,.5,1,1.5,2])
        ax.set_yticks([0,.25,.5,.75,1])
        ax.set_xlim(data["xlim"])
        ax.set_ylim(data["ylim"])
        ax._paper_limits_padded = True
        ax.xaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT, labelbottom=show_x, labelleft=show_y)
        ax.set_xlabel(data["xlabel"] if show_xlabel else "", labelpad=1.5)
        ax.set_ylabel(data["ylabel"] if show_y else "", labelpad=1.5)
        ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=.35)
        tag = string.ascii_lowercase[index]
        tags.append(fig.text(left/width, (bottom+plot_height+2.0)/height, f"({tag})", ha="left"))
        digest = figure_data_digest(SimpleNamespace(axes=[ax]))
        semantics = _check_cached_semantics(
            ax, data, data["ylabel"], display_xlabel=show_xlabel, display_ylabel=show_y,
            display_xticklabels=show_x, display_yticklabels=show_y)
        if digest != metadata["data_sha256"] or not semantics["match"]:
            raise ValueError(f"Cached scientific data or shared-axis semantics changed: {panel}")
        checks.append({"panel": tag, "cached_data_sha256": metadata["data_sha256"],
                       "redrawn_data_sha256": digest, "display_semantics": semantics})
        placements.append({"source": panel.with_suffix(".json").relative_to(root).as_posix(),
                           "panel": tag, "row": row, "column": column,
                           "x_mm": left, "y_mm": bottom, "axes_width_mm": plot_width,
                           "axes_height_mm": plot_height, "scale": 1.0,
                           "xlabel_visible": show_xlabel, "xticklabels_visible": True, "ylabel_visible": show_y,
                           "render_mode": "native_from_cached_artist_data"})
        if legend_handles is None:
            legend_handles, entries = ax.lines, metadata["legend"]
        elif metadata["legend"] != entries:
            raise ValueError(f"Inconsistent curve key in {group}")
    title = r"$m$"
    labels = [rf"${float(re.search(r'=\s*([\d.]+)',e['label']).group(1)):g}$"
              for e in entries]
    legend = fig.legend(legend_handles, labels, title=title, loc="center",
                        bbox_to_anchor=(150/width,71.5/height),
                        frameon=False, borderaxespad=0, borderpad=.1,
                        handlelength=1.1, handletextpad=.4, labelspacing=.45)
    box_data, box_stats, box_audit = load_box_data(root/"正文图/Fig2/data", "m")
    box_checks = []
    for column, p in enumerate(p_values[:5]):
        left, bottom = 14.0 + 25.9*column, 14.0
        ax = fig.add_axes([left/width, bottom/height, plot_width/width, plot_height/height])
        axes.append(ax)
        box_check = draw_box_panel(ax, p, box_data, box_stats)
        box_check["artist_data_sha256_before_style"] = figure_data_digest(SimpleNamespace(axes=[ax]))
        box_check["box_vertices_before_style"] = [patch.get_path().vertices.tolist() for patch in ax.patches]
        box_checks.append(box_check)
        ax.tick_params(pad=DEFAULT_TICK_PAD_PT, labelleft=column == 0)
        ax.set_ylabel(axes[0].get_ylabel() if column == 0 else "", labelpad=1.5)
        ax.set_xlabel(r"Growth parameter, $m$" if column == 2 else "", labelpad=1.5)
        tag = string.ascii_lowercase[5+column]
        tags.append(fig.text(left/width, (bottom+plot_height+2)/height, f"({tag})", ha="left"))
        placements.append({"source": "正文图/Fig2/data/box_plot_data.csv",
                           "statistics_source": "正文图/Fig2/data/box_statistics.csv",
                           "panel": tag, "row": 1, "column": column,
                           "x_mm": left, "y_mm": bottom, "axes_width_mm": plot_width,
                           "axes_height_mm": plot_height, "scale": 1.0,
                           "xlabel_visible": column == 2, "xticklabels_visible": True, "ylabel_visible": column == 0,
                           "render_mode": "native_from_supplied_box_statistics_and_observations"})
    box_legend = add_box_legend(fig, (150/width,29/height))
    _apply_figure_style(fig)
    for ax, box_check in zip(axes[5:], box_checks):
        digest = figure_data_digest(SimpleNamespace(axes=[ax]))
        vertices = [patch.get_path().vertices.tolist() for patch in ax.patches]
        if digest != box_check["artist_data_sha256_before_style"] or vertices != box_check["box_vertices_before_style"]:
            raise ValueError("Figure 2 shared styling changed supplied box/scatter/mean values")
        box_check.update(artist_data_sha256_after_style=digest, artists_match_after_shared_style=True)
    # Add the requested display titles after the shared style removes legacy
    # parameter titles. P_l follows the manuscript's notation table.
    panel_p_values = p_values * 2
    for ax, p in zip(axes, panel_p_values, strict=True):
        ax.set_title(rf"$P_l={p:g}$", fontsize=8, pad=3)
    # Category ticks sit inside the box axes and must stay centered.
    _inset_terminal_ticklabels(axes[:5])
    align_subplot_labels(fig, axes, tags)
    layout = _check_line_grid_layout(fig, axes, legend, width, height)
    renderer = fig.canvas.get_renderer()
    layout["parameter_titles"] = [
        {"panel": string.ascii_lowercase[index], "P_l": p, "text": ax.get_title(),
         "bounds_mm": (ax.title.get_window_extent(renderer).extents * 25.4 / fig.dpi).tolist()}
        for index, (ax, p) in enumerate(zip(axes, panel_p_values, strict=True))]
    bounds = layout["legend_bounds_mm"]
    layout.update(rows=2, columns=5, scientific_axes=10, legend_title=title,
                  row_roles=["global_cooperation_curves", "within_type_cooperation_boxes"],
                  plotting_center_y_mm=71.5,
                  legend_center_y_mm=(bounds[1]+bounds[3])/2,
                  major_ticks=[{"panel": string.ascii_lowercase[index],
                                "x": ax.get_xticks().tolist(), "y": ax.get_yticks().tolist()}
                               for index, ax in enumerate(axes)])
    layout["legend_center_error_mm"] = abs(layout["legend_center_y_mm"]-layout["plotting_center_y_mm"])
    box_bounds = (box_legend.get_window_extent(renderer).extents*25.4/fig.dpi).tolist()
    keys = box_legend.legend_handles
    layout["box_legend_keys"] = [
        {"label": label, "shape": "circle", "color": handle.get_color(),
         "marker": handle.get_marker(), "markersize_pt": handle.get_markersize()}
        for label, handle in zip(("Node", "Link"), keys[:2])]
    layout["box_legend_markers_match"] = (
        all(key["marker"] == "o" for key in layout["box_legend_keys"])
        and len({key["markersize_pt"] for key in layout["box_legend_keys"]}) == 1)
    if not layout["box_legend_markers_match"]:
        layout["violations"].append("Node and Link legend keys must use equal-sized circles")
    layout["box_legend_mean_marker"] = keys[2].get_marker()
    layout["row_gap_mm"] = 12.5
    layout["box_legend_bounds_mm"] = box_bounds
    layout["box_legend_center_error_mm"] = abs((box_bounds[1]+box_bounds[3])/2-29.0)
    if not (0 <= box_bounds[0] < box_bounds[2] <= width and 0 <= box_bounds[1] < box_bounds[3] <= height):
        layout["violations"].append("Box legend exceeds the figure canvas")
    if layout["box_legend_center_error_mm"] > 1e-8:
        layout["violations"].append("Box legend is not centered on its plotting row")
    if layout["legend_center_error_mm"] > 1e-8:
        layout["violations"].append("Side legend is not centered on the plotting area")
    if layout["font_sizes_pt"] != [8.0] or layout["font_families"] != ["Times New Roman"]:
        layout["violations"].append("Figure text must use 8 pt Times New Roman")
    (root/f"交付/{group}共享轴布局检查.json").write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding="utf-8")
    if layout["violations"]:
        fig.savefig(root/f"tmp/{group}_shared_axis_failure.png",dpi=180)
        raise ValueError(f"{group} layout failed: {layout['violations'][:5]}")
    fig.savefig(target,dpi=DPI,bbox_inches=None,facecolor="white")
    plt.close(fig)
    (root/f"交付/{group}共享轴数据检查.json").write_text(json.dumps(
        {"panels": checks, "box_panels": box_checks, "box_data": box_audit,
         "original_curve_arrays_unchanged": True, "all_match": True},
        ensure_ascii=False,indent=2),encoding="utf-8")
    return target, placements
