"""Render ORH-MPD curves with their supplied within-type boxplot row."""
import json
import re
import string
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from paper_plot_palette import DISTRIBUTION_LABELS
from paper_mpd_boxplots import load_mpd_box_data, draw_mpd_box_panel, add_box_legend
from paper_plot_style import (
    DPI, LINE_WIDTH_PT, MARKER_SIZE_PT, DEFAULT_TICK_PAD_PT,
    configure_style, figure_data_digest, _apply_figure_style, align_subplot_labels,
)
from figure_render_checks import (
    _check_cached_semantics, _check_line_grid_layout, _inset_terminal_ticklabels,
)


def render_publication(root, group, sections, target):
    if group != "Fig8" or len(sections) != 1 or sections[0][1]:
        raise ValueError(f"Unsupported ORH-MPD line grid: {group}")
    panels = sections[0][0]
    if len(panels) != 5:
        raise ValueError("Figure 8 requires five measured curve panels")
    configure_style()
    width, height = 160.0, 97.5
    plot_width, plot_height = 24.4, 30.0
    fig = plt.figure(figsize=(width/25.4, height/25.4))
    axes, tags, placements, checks, p_values = [], [], [], [], []
    legend_handles, entries = None, None

    for column, panel in enumerate(panels):
        left, bottom = 14.0 + 25.9*column, 56.5
        show_xlabel, show_y = column == 2, column == 0
        metadata = json.loads(panel.with_suffix(".json").read_text(encoding="utf-8"))
        data = metadata["plot_data"]
        match = re.search(r"P_l\s*=\s*([\d.]+)", data["scientific_title"])
        if match is None or data["images"] or len(data["lines"]) != 5:
            raise ValueError(f"Invalid Figure 8 scientific curve cache: {panel}")
        p_values.append(float(match.group(1)))
        ax = fig.add_axes([left/width, bottom/height, plot_width/width, plot_height/height])
        axes.append(ax)
        for line in data["lines"]:
            ax.plot(line["x"], line["y"], color=line["color"], marker=line["marker"],
                    linestyle=line["linestyle"], label=line["label"],
                    linewidth=LINE_WIDTH_PT, markersize=MARKER_SIZE_PT,
                    markeredgewidth=LINE_WIDTH_PT, markerfacecolor=line["markerfacecolor"],
                    markevery=line["markevery"])
        ax.set_xticks([0, .25, .5, .75, 1])
        ax.set_yticks([0, .2, .4, .6, .8, 1])
        ax.set_xlim(data["xlim"])
        ax.set_ylim(data["ylim"])
        ax._paper_limits_padded = True
        ax.xaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT, labelbottom=True, labelleft=show_y)
        ax.set_xlabel(data["xlabel"] if show_xlabel else "", labelpad=1.5)
        ax.set_ylabel(data["ylabel"] if show_y else "", labelpad=1.5)
        ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=.35)
        tag = string.ascii_lowercase[column]
        tags.append(fig.text(left/width, (bottom+plot_height+2)/height, f"({tag})", ha="left"))
        digest = figure_data_digest(SimpleNamespace(axes=[ax]))
        semantics = _check_cached_semantics(
            ax, data, data["ylabel"], display_xlabel=show_xlabel, display_ylabel=show_y,
            display_xticklabels=True, display_yticklabels=show_y)
        if digest != metadata["data_sha256"] or not semantics["match"]:
            raise ValueError(f"Cached Figure 8 curve values or display semantics changed: {panel}")
        checks.append({"panel": tag, "cached_data_sha256": metadata["data_sha256"],
                       "redrawn_data_sha256": digest, "display_semantics": semantics})
        placements.append({"source": panel.with_suffix(".json").relative_to(root).as_posix(),
                           "panel": tag, "row": 0, "column": column,
                           "x_mm": left, "y_mm": bottom, "axes_width_mm": plot_width,
                           "axes_height_mm": plot_height, "scale": 1.0,
                           "xlabel_visible": show_xlabel, "xticklabels_visible": True,
                           "ylabel_visible": show_y, "render_mode": "native_from_cached_artist_data"})
        if legend_handles is None:
            legend_handles, entries = ax.lines, metadata["legend"]
        elif metadata["legend"] != entries:
            raise ValueError("Inconsistent Figure 8 distribution key")
    if p_values != [0, .25, .5, .75, 1]:
        raise ValueError(f"Figure 8 columns must follow the paper P_l order: {p_values}")

    numbered_labels = [f"D{index}: {label}" for index, label in enumerate(DISTRIBUTION_LABELS, 1)]
    legend = fig.legend(legend_handles, numbered_labels, ncols=5, loc="center",
                        bbox_to_anchor=(.5,94.5/height), frameon=False,
                        handlelength=1.25, handletextpad=.35, columnspacing=1.0)

    box_data, box_stats, box_audit = load_mpd_box_data(root/"正文图/Fig8/data", "dist")
    category_labels = {int(row["category_rank"]): row["dist_label"] for row in box_data}
    if category_labels != dict(enumerate(DISTRIBUTION_LABELS, 1)):
        raise ValueError("Figure 8 source box categories do not match the curve distribution order")
    box_checks = []
    for column, p in enumerate(p_values):
        left, bottom = 14.0 + 25.9*column, 14.0
        ax = fig.add_axes([left/width, bottom/height, plot_width/width, plot_height/height])
        axes.append(ax)
        box_check = draw_mpd_box_panel(ax, p, box_data, box_stats)
        box_check["artist_data_sha256_before_style"] = figure_data_digest(SimpleNamespace(axes=[ax]))
        box_check["box_vertices_before_style"] = [patch.get_path().vertices.tolist() for patch in ax.patches]
        box_checks.append(box_check)
        ax.set_xticks([1,2,3,4,5], [f"D{rank}" for rank in range(1,6)])
        ax.tick_params(pad=DEFAULT_TICK_PAD_PT, labelleft=column == 0, labelbottom=True)
        ax.set_ylabel(axes[0].get_ylabel() if column == 0 else "", labelpad=1.5)
        ax.set_xlabel("Hyperedge order distribution" if column == 2 else "", labelpad=1.5)
        tag = string.ascii_lowercase[5+column]
        tags.append(fig.text(left/width, (bottom+plot_height+2)/height, f"({tag})", ha="left"))
        placements.append({"source": "正文图/Fig8/data/fig1_a1_points.csv",
                           "statistics_source": "正文图/Fig8/data/fig1_a1_boxes.csv",
                           "panel": tag, "row": 1, "column": column,
                           "x_mm": left, "y_mm": bottom, "axes_width_mm": plot_width,
                           "axes_height_mm": plot_height, "scale": 1.0,
                           "xlabel_visible": column == 2, "xticklabels_visible": True,
                           "ylabel_visible": column == 0,
                           "render_mode": "native_from_supplied_box_statistics_and_observations"})
    box_legend = add_box_legend(fig, (150/width,29/height))
    _apply_figure_style(fig)
    for ax, box_check in zip(axes[5:], box_checks):
        digest = figure_data_digest(SimpleNamespace(axes=[ax]))
        vertices = [patch.get_path().vertices.tolist() for patch in ax.patches]
        if digest != box_check["artist_data_sha256_before_style"] or vertices != box_check["box_vertices_before_style"]:
            raise ValueError("Figure 8 shared styling changed supplied box/scatter/mean values")
        box_check.update(artist_data_sha256_after_style=digest, artists_match_after_shared_style=True)
    panel_p_values = p_values * 2
    for ax, p in zip(axes, panel_p_values, strict=True):
        ax.set_title(rf"$P_l={p:g}$", fontsize=8, pad=3)
    _inset_terminal_ticklabels(axes[:5])
    align_subplot_labels(fig, axes, tags)
    layout = _check_line_grid_layout(fig, axes, legend, width, height)
    renderer = fig.canvas.get_renderer()
    layout["parameter_titles"] = [
        {"panel": string.ascii_lowercase[index], "P_l": p, "text": ax.get_title(),
         "bounds_mm": (ax.title.get_window_extent(renderer).extents*25.4/fig.dpi).tolist()}
        for index, (ax, p) in enumerate(zip(axes, panel_p_values, strict=True))]
    bounds = layout["legend_bounds_mm"]
    key_bounds = (box_legend.get_window_extent(renderer).extents*25.4/fig.dpi).tolist()
    layout["box_legend_keys"] = [
        {"label": label, "shape": "circle", "color": handle.get_color(),
         "marker": handle.get_marker(), "markersize_pt": handle.get_markersize()}
        for label, handle in zip(("Node", "Link"), box_legend.legend_handles[:2])]
    layout["box_legend_markers_match"] = (
        all(key["marker"] == "o" for key in layout["box_legend_keys"])
        and len({key["markersize_pt"] for key in layout["box_legend_keys"]}) == 1)
    if not layout["box_legend_markers_match"]:
        layout["violations"].append("Node and Link legend keys must use equal-sized circles")
    layout["box_legend_mean_marker"] = box_legend.legend_handles[2].get_marker()
    layout.update(rows=2, columns=5, scientific_axes=10, shared_axis_labels=True,
                  legend_position="top", legend_labels=numbered_labels,
                  distribution_mapping=[{"code":f"D{rank}","label":label}
                                        for rank,label in enumerate(DISTRIBUTION_LABELS,1)],
                  row_roles=["global_cooperation_curves","within_type_cooperation_boxes"],
                  row_gap_mm=12.5, box_legend_bounds_mm=key_bounds,
                  box_legend_center_error_mm=abs((key_bounds[1]+key_bounds[3])/2-29),
                  major_ticks=[{"panel":string.ascii_lowercase[index],
                                "x":ax.get_xticks().tolist(),"y":ax.get_yticks().tolist()}
                               for index,ax in enumerate(axes)])
    layout["legend_center_error_mm"] = abs((bounds[0]+bounds[2])/2-width/2)
    highest_plot_text = max(item["bounds_mm"][3] for item in layout["parameter_titles"])
    if layout["legend_center_error_mm"]>1e-8 or bounds[1]<=highest_plot_text:
        layout["violations"].append("Distribution legend must be centered above the plot titles")
    if not (0<=key_bounds[0]<key_bounds[2]<=width and 0<=key_bounds[1]<key_bounds[3]<=height):
        layout["violations"].append("Player legend exceeds the Figure 8 canvas")
    if layout["box_legend_center_error_mm"]>1e-8:
        layout["violations"].append("Player legend is not centered on the boxplot row")
    if layout["font_sizes_pt"]!=[8.0] or layout["font_families"]!=["Times New Roman"]:
        layout["violations"].append("Figure 8 text must use 8 pt Times New Roman")
    (root/"交付/Fig8共享轴布局检查.json").write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding="utf-8")
    if layout["violations"]:
        fig.savefig(root/"tmp/Fig8_shared_axis_failure.png",dpi=180)
        plt.close(fig)
        raise ValueError(f"Figure 8 layout failed: {layout['violations'][:5]}")
    if sum(item["box_count"] for item in box_checks)!=40 or sum(item["scatter_count"] for item in box_checks)!=1640:
        raise ValueError("Figure 8 requires exactly 40 boxes and 1640 supplied observations")
    fig.savefig(target,dpi=DPI,bbox_inches=None,facecolor="white")
    plt.close(fig)
    report={"panels":checks,"box_panels":box_checks,"box_data":box_audit,
            "original_curve_arrays_unchanged":True,"boxes_verified":40,"box_observations_verified":1640,
            "distribution_mapping":layout["distribution_mapping"],"all_match":True}
    (root/"交付/Fig8共享轴数据检查.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return target,placements
