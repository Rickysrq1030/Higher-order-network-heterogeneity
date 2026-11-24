"""Render paper Figure C2 with both shared keys at the far right."""
import json
import re
import string
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.ticker import StrMethodFormatter
import numpy as np

from paper_plot_style import (
    DPI, FONT_SIZE_PT, LINE_WIDTH_PT, MARKER_SIZE_PT, DEFAULT_TICK_PAD_PT,
    configure_style, figure_data_digest, _apply_figure_style, align_subplot_labels,
)


from figure_render_checks import (
    _check_layout, _check_cached_semantics, _legend_center_geometry,
    _inset_terminal_ticklabels,
)


def render_publication(root, group, sections, target):
    """Keep the cached numbers, colors and heatmap geometry at native 8 pt."""
    if group != "FigC2":
        raise ValueError(f"Unsupported URH figure: {group}")
    if len(sections) != 2 or [phase for _, phase in sections] != [False, True]:
        raise ValueError(f"Unexpected section order for {group}")
    if any(len(panels) != 3 for panels, _ in sections):
        raise ValueError(f"{group} requires three curve panels and three phase panels")

    configure_style()
    width, height = 160.0, 98.0
    panel_width, panel_height = 38.5, 36.0
    fig = plt.figure(figsize=(width / 25.4, height / 25.4))
    axes, comparisons, placements = [], [], []
    line_handles = None
    shared_legend = None
    phase_image = None
    shared_image_scale = None
    column_parameters = {}
    panel_labels = []

    for row, (panels, is_phase) in enumerate(sections):
        bottom = 55.0 if row == 0 else 12.0
        for column, panel in enumerate(panels):
            cache = panel.with_suffix(".json")
            metadata = json.loads(cache.read_text(encoding="utf-8"))
            if "plot_data" not in metadata:
                raise ValueError(f"Missing scientific arrays in {cache}; regenerate {group}")
            data = metadata["plot_data"]
            # Reclaim repeated labels for three larger, evenly spaced plots.
            left = 13.0 + column * 40.5
            ax = fig.add_axes([left / width, bottom / height,
                               panel_width / width, panel_height / height])
            axes.append(ax)
            for line in data["lines"]:
                ax.plot(line["x"], line["y"], color=line["color"],
                        marker=line["marker"], linestyle=line["linestyle"],
                        label=line["label"], linewidth=LINE_WIDTH_PT,
                        markersize=MARKER_SIZE_PT, markeredgewidth=LINE_WIDTH_PT,
                        markerfacecolor=line["markerfacecolor"],
                        markevery=line["markevery"])
            for image in data["images"]:
                scale = {key: image[key] for key in ("colormap", "clim", "bad_color")}
                if shared_image_scale is not None and scale != shared_image_scale:
                    raise ValueError(f"Phase color scales disagree in {group}")
                shared_image_scale = scale
                cmap = ListedColormap(image["colormap"])
                cmap.set_bad(image["bad_color"])
                phase_image = ax.imshow(
                    np.ma.masked_invalid(np.asarray(image["array"], dtype=float)),
                    extent=image["extent"], origin=image["origin"],
                    interpolation=image["interpolation"], resample=True, aspect="auto",
                    cmap=cmap, vmin=image["clim"][0], vmax=image["clim"][1],
                )
            ax.set_xticks([0, .5, 1, 1.5, 2] if group == "FigC1" else [0, .25, .5, .75, 1])
            ax.set_yticks([0, .2, .4, .6, .8, 1])
            # Phase FigC1 has half-cell margins; do not replace its real extent.
            ax.set_xlim(data["xlim"])
            ax.set_ylim(data["ylim"])
            ax._paper_limits_padded = True
            ax.xaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
            ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
            ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT,
                           labelleft=column == 0, labelbottom=row == 1)
            show_xlabel = is_phase and column == 1
            ax.set_xlabel(data["xlabel"] if show_xlabel else "", labelpad=4)
            ax.set_ylabel(data["ylabel"] if column == 0 else "", labelpad=4)
            if is_phase:
                ax.grid(False)
            else:
                ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=.35)

            parameter = re.search(r"g\s*=\s*([\d.]+)",
                                  data.get("scientific_title", data["title"]))
            if parameter is None:
                raise ValueError(f"Missing group size in {cache}")
            group_size = float(parameter.group(1))
            if row == 0:
                column_parameters[column] = group_size
            elif group_size != column_parameters[column]:
                raise ValueError(f"Curve and phase group sizes differ in column {column + 1}")
            panel_labels.append(fig.text(
                left / width, (bottom + panel_height + 3.4) / height,
                f"({string.ascii_lowercase[row * 3 + column]})",
                ha="left", va="baseline"))

            actual_digest = figure_data_digest(SimpleNamespace(axes=[ax]))
            if actual_digest != metadata["data_sha256"]:
                raise ValueError(f"Scientific arrays changed while redrawing {cache}")
            semantics = _check_cached_semantics(
                ax, data, axes[row * 3].get_ylabel(), display_xlabel=show_xlabel,
                display_ylabel=column == 0, display_xticklabels=row == 1,
                display_yticklabels=column == 0)
            if not semantics["match"]:
                raise ValueError(f"Display semantics changed while redrawing {cache}")
            comparisons.append({"source": cache.relative_to(root).as_posix(),
                                "cached_data_sha256": metadata["data_sha256"],
                                "redrawn_data_sha256": actual_digest,
                                "xlim": list(ax.get_xlim()), "ylim": list(ax.get_ylim()),
                                "display_semantics": semantics})
            placements.append({"source": cache.relative_to(root).as_posix(),
                               "x_mm": left, "y_mm": bottom,
                               "axes_width_mm": panel_width, "axes_height_mm": panel_height,
                               "scale": 1.0, "render_mode": "native_from_cached_artist_data"})
            if not is_phase:
                if shared_legend is not None and metadata["legend"] != shared_legend:
                    raise ValueError(f"Curve keys disagree in {group}")
                if shared_legend is None:
                    line_handles = ax.lines
                    shared_legend = metadata["legend"]

    labels = [rf"${float(entry['label'].split('=')[-1].strip(' $')):g}$"
              for entry in shared_legend]
    legend = fig.legend(line_handles, labels, title=r"$P_l$",
                        loc="center left", bbox_to_anchor=(137 / width, 73 / height),
                        frameon=False, borderaxespad=0, borderpad=.1,
                        handlelength=1.1, handletextpad=.4, labelspacing=.45)
    bar_ax = fig.add_axes([137 / width, 12 / height, 2 / width, panel_height / height])
    bar = fig.colorbar(phase_image, cax=bar_ax, orientation="vertical")
    bar.set_ticks([0, .25, .5, .75, 1])
    bar_ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
    bar_ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT)
    bar.set_label(r"Cooperation rate, $\bar{F}_c$", labelpad=2)
    bar.outline.set_linewidth(LINE_WIDTH_PT)
    _apply_figure_style(fig)
    _inset_terminal_ticklabels(axes)
    align_subplot_labels(fig, axes, panel_labels)
    for column, ax in enumerate(axes[:3]):
        ax.annotate(rf"$g = {column_parameters[column]:g}$",
                    xy=(.5, 1), xycoords="axes fraction",
                    xytext=(0, 3.6), textcoords="offset points",
                    ha="center", va="baseline", fontsize=FONT_SIZE_PT)

    layout = _check_layout(fig, axes, legend, bar_ax, width, height)
    layout.update({"shared_axis_labels": True,
                   "parameter_titles": [column_parameters[column] for column in range(3)],
                   **_legend_center_geometry(fig, axes[:3], legend)})
    (root / f"交付/{group}侧边布局检查.json").write_text(
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    if layout["violations"]:
        fig.savefig(root / f"tmp/{group}_side_keys_layout_failure.png", dpi=180, bbox_inches=None)
        plt.close(fig)
        raise ValueError(f"{group} layout check failed: {layout['violations'][:5]}")
    fig.savefig(target, dpi=DPI, bbox_inches=None, facecolor="white")
    plt.close(fig)
    data_report = {"width_mm": width, "height_mm": height, "rows": 2, "columns": 3,
                   "individual_ylabels": 2, "parameter_titles": len(column_parameters),
                   "bottom_row_xlabels": sum(bool(ax.get_xlabel()) for ax in axes[3:]),
                   "shared_axis_labels": True,
                   "right_colorbar_gap_mm": 4.5,
                   "render_mode": "native_from_cached_artist_data",
                   "scientific_arrays_verified": len(comparisons),
                   "display_semantics_verified": len(comparisons), "panels": comparisons}
    (root / f"交付/{group}侧边布局数据检查.json").write_text(
        json.dumps(data_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target, placements
