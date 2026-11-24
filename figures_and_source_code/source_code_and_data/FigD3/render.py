"""Restore paper Figure D3 from one complete, measured MPD data table.

The upper row shows three measured eta slices, as in the reference paper.
The middle row retains every observation of the 21 by 41 measured grid.
The lower row shows the supplied type-cooperation boxes across 41 delta values.
"""
import hashlib
import json
from pathlib import Path
import re
import string
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.ticker import StrMethodFormatter
import numpy as np

from paper_plot_palette import ETA_COLORS
from paper_mpd_boxplots import load_mpd_box_data, draw_mpd_box_panel, add_box_legend
from paper_plot_style import (
    DPI, LINE_WIDTH_PT, MARKER_SIZE_PT, DEFAULT_TICK_PAD_PT, configure_style,
    figure_data_digest, _apply_figure_style, align_subplot_labels,
)
from figure_render_checks import (
    _check_layout, _check_cached_semantics, _legend_center_geometry, _inset_terminal_ticklabels,
)


PL_VALUES = (0.0, .25, .5, .75, 1.0)
CURVE_ETA = (0.0, .25, .5)
ETA_MARKERS = {0.0: "o", .25: "s", .5: "^"}
TABLE_COLUMNS = ("G", "alpha", "p", "b", "Coop_Rate")


def _read_complete_processed(path):
    """Read exact coordinate/value records and reject every incomplete grid."""
    valid_lines = [(number, line.split()) for number, line in
                   enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
                   if line.strip() and not re.fullmatch(r"-+", line.strip())]
    if not valid_lines:
        raise ValueError(f"Empty Figure D3 processed table: {path}")
    header = valid_lines[0][1]
    if len(header) != len(TABLE_COLUMNS) or set(header) != set(TABLE_COLUMNS):
        raise ValueError(f"Figure D3 table must contain exactly {TABLE_COLUMNS}: {path}")
    lookup = {}
    for number, parts in valid_lines[1:]:
        if len(parts) != len(header):
            raise ValueError(f"Malformed Figure D3 table record at {path}:{number}")
        row = dict(zip(header, map(float, parts)))
        if not np.isfinite(list(row.values())).all():
            raise ValueError(f"Non-finite Figure D3 observation at {path}:{number}")
        if row["G"] != 4 or not 0 <= row["Coop_Rate"] <= 1:
            raise ValueError(f"Invalid Figure D3 observation at {path}:{number}")
        key = (row["p"], row["alpha"], row["b"])
        if key in lookup:
            raise ValueError(f"Duplicate Figure D3 coordinate {key} at {path}:{number}")
        lookup[key] = row["Coop_Rate"]
    delta_values = np.arange(41, dtype=float) / 40
    eta_values = np.arange(21, dtype=float) / 20
    expected = {(p, float(eta), float(r)) for p in PL_VALUES
                for eta in eta_values for r in delta_values}
    if set(lookup) != expected:
        missing = len(expected - set(lookup))
        extra = len(set(lookup) - expected)
        raise ValueError(f"Figure D3 requires 4305 unique observations; missing={missing}, extra={extra}")
    matrices = {p: np.asarray([[lookup[(p, float(eta), float(r))] for r in delta_values]
                              for eta in eta_values], dtype=float)
                for p in PL_VALUES}
    return delta_values, eta_values, lookup, matrices


def _cached_phases(root, sections, matrices):
    sections = [section for section in sections if section[1]]
    if len(sections) != 1 or sections[0][1] is not True or len(sections[0][0]) != 5:
        raise ValueError("FigD3 requires exactly five cached complete phase panels")
    phases = {}
    shared_scale = None
    expected_extent = [0., 1., 0., 1.]
    for panel in sections[0][0]:
        cache = panel.with_suffix(".json")
        metadata = json.loads(cache.read_text(encoding="utf-8"))
        if "plot_data" not in metadata:
            raise ValueError(f"Missing cached Figure D3 arrays: {cache}; regenerate FigD3")
        data = metadata["plot_data"]
        if data["lines"] or len(data["images"]) != 1:
            raise ValueError(f"Figure D3 phase cache must have one image and no curves: {cache}")
        scientific_title = data.get("scientific_title", data["title"])
        group = re.search(r"g\s*=\s*([\d.]+)", scientific_title)
        parameter = re.search(r"P_l\s*=\s*([\d.]+)", scientific_title)
        if group is None or parameter is None or float(group.group(1)) != 4:
            raise ValueError(f"Cannot identify Figure D3 scientific parameters in {cache}")
        p = float(parameter.group(1))
        if p not in PL_VALUES or p in phases:
            raise ValueError(f"Invalid or duplicate Figure D3 phase parameter {p}: {cache}")
        image = data["images"][0]
        actual = np.asarray(image["array"], dtype=float)
        if actual.shape != (21, 41) or not np.array_equal(actual, matrices[p]):
            raise ValueError(f"Cached Figure D3 phase does not exactly match the processed table: {cache}")
        if (not np.allclose(image["extent"], expected_extent, rtol=0, atol=1e-12)
                or image["origin"] != "lower" or image["interpolation"] != "bicubic"
                or image["clim"] != [0., 1.]):
            raise ValueError(f"Invalid Figure D3 phase geometry or color range: {cache}")
        reference_colors = [list(plt.get_cmap("RdBu_r")(i / 255)) for i in range(256)]
        if image["colormap"] != reference_colors:
            raise ValueError(f"Figure D3 phase must retain its measured RdBu_r color mapping: {cache}")
        scale = {key: image[key] for key in ("colormap", "clim", "bad_color")}
        if shared_scale is not None and scale != shared_scale:
            raise ValueError("Figure D3 phase panels have inconsistent shared color scales")
        shared_scale = scale
        phases[p] = (cache, metadata)
    return phases


def _cached_curves(root, sections, lookup, delta_values):
    sections = [section for section in sections if not section[1]]
    if len(sections) != 1 or len(sections[0][0]) != 5:
        raise ValueError("Figure D3 requires five cached measured curve panels")
    curves = {}
    for panel in sections[0][0]:
        cache = panel.with_suffix(".json")
        metadata = json.loads(cache.read_text(encoding="utf-8"))
        data = metadata["plot_data"]
        title = data.get("scientific_title", data["title"])
        parameter = re.search(r"P_l\s*=\s*([\d.]+)", title)
        group_size = re.search(r"g\s*=\s*([\d.]+)", title)
        if parameter is None or group_size is None or float(group_size.group(1)) != 4:
            raise ValueError(f"Invalid curve parameters: {cache}")
        p = float(parameter.group(1))
        if p not in PL_VALUES or p in curves or data["images"] or len(data["lines"]) != 3:
            raise ValueError(f"Invalid or duplicate Figure D3 curve cache: {cache}")
        seen = set()
        for line in data["lines"]:
            eta = float(re.search(r"=\s*([\d.]+)", line["label"]).group(1))
            if eta not in CURVE_ETA or eta in seen:
                raise ValueError(f"Unexpected Figure D3 eta curve: {cache}")
            seen.add(eta)
            values = [lookup[(p, eta, float(r))] for r in delta_values]
            if not np.array_equal(line["x"], delta_values) or not np.array_equal(line["y"], values):
                raise ValueError(f"Cached curve differs from the complete MPD table: {cache}")
        curves[p] = (cache, metadata)
    return curves


def render_publication(root, group, sections, target):
    """Draw curves, retained measured phases, then type-cooperation boxes."""
    if group != "FigD3":
        raise ValueError(f"Unsupported figure: {group}")
    root, target = Path(root), Path(target)
    table_path = Path(__file__).resolve().parent / "data/processed_coop_data.txt"
    delta_values, eta_values, lookup, matrices = _read_complete_processed(table_path)
    phases = _cached_phases(root, sections, matrices)
    curves = _cached_curves(root, sections, lookup, delta_values)
    box_data, box_stats, box_audit = load_mpd_box_data(table_path.parent, "alpha")
    source_manifest = table_path.parent / "box_source.json"
    if source_manifest.is_file():
        provenance = json.loads(source_manifest.read_text(encoding="utf-8"))
        supplied = {Path(item["local_file"]).name: item["sha256"] for item in provenance["files"]}
        for item in box_audit["inputs"]:
            if supplied.get(Path(item["path"]).name) != item["sha256"]:
                raise ValueError("Figure D3 box CSV differs from its source archive manifest")
        box_audit["provenance"] = provenance
    configure_style()
    width, height = 160.0, 137.0
    panel_width, panel_height = 24.4, 30.0
    fig = plt.figure(figsize=(width / 25.4, height / 25.4))
    axes, comparisons, placements, label_artists = [], [], [], []
    curve_pointwise, phase_pointwise = [], []
    box_checks, box_patch_snapshots = [], {}
    line_handles, phase_image = None, None
    row_names = ("curves", "phases", "boxes")
    # Share each row's delta or eta label while retaining every tick number.
    for row, bottom in enumerate((100.0, 57.0, 14.0)):
        for column, p in enumerate(PL_VALUES):
            cache, metadata = phases[p]
            data = metadata["plot_data"]
            left = 14.0 + column * 25.9
            ax = fig.add_axes([left / width, bottom / height,
                               panel_width / width, panel_height / height])
            axes.append(ax)
            if row == 0:
                curve_cache, curve_metadata = curves[p]
                curve_data = curve_metadata["plot_data"]
                for cached_line in curve_data["lines"]:
                    line, = ax.plot(cached_line["x"], cached_line["y"], color=cached_line["color"],
                                    marker=cached_line["marker"], linestyle=cached_line["linestyle"],
                                    label=cached_line["label"], linewidth=LINE_WIDTH_PT,
                                    markersize=MARKER_SIZE_PT, markeredgewidth=LINE_WIDTH_PT,
                                    markerfacecolor=cached_line["markerfacecolor"], markevery=cached_line["markevery"])
                    eta = float(re.search(r"=\s*([\d.]+)",cached_line["label"]).group(1))
                    for r, actual in zip(line.get_xdata(), line.get_ydata()):
                        raw = lookup[(p, eta, float(r))]
                        curve_pointwise.append({"P_l": p, "eta": eta, "delta": float(r),
                                                "processed_value": raw, "curve_value": float(actual),
                                                "match": bool(raw == actual)})
                if line_handles is None:
                    line_handles = list(ax.lines)
                ax.set_xlim(curve_data["xlim"])
                ax.set_ylim(curve_data["ylim"])
                ax._paper_limits_padded = True
                ax.set_ylabel(curve_data["ylabel"] if column == 0 else "")
                ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=.35)
            elif row == 2:
                box_check = draw_mpd_box_panel(ax, p, box_data, box_stats)
                box_check["artist_data_sha256_before_style"] = figure_data_digest(SimpleNamespace(axes=[ax]))
                box_checks.append(box_check)
                box_patch_snapshots[column] = [patch.get_path().vertices.copy() for patch in ax.patches]
                ax.set_ylabel(axes[0].get_ylabel() if column == 0 else "")
                ax.set_xlabel(r"Random attachment probability, $\eta$" if column == 2 else "")
            else:
                image = data["images"][0]
                colormap = ListedColormap(image["colormap"])
                colormap.set_bad(image["bad_color"])
                phase_image = ax.imshow(
                    np.asarray(image["array"], dtype=float), extent=image["extent"],
                    origin=image["origin"], interpolation=image["interpolation"], resample=True,
                    aspect="auto", cmap=colormap, vmin=image["clim"][0], vmax=image["clim"][1],
                )
                ax.set_xlim(data["xlim"])
                ax.set_ylim(data["ylim"])
                phase_ylabel = data["ylabel"].replace("Random-attachment", "Random attachment")
                ax.set_ylabel(phase_ylabel if column == 0 else "")
                ax.grid(False)
                for ei, eta in enumerate(eta_values):
                    for ri, r in enumerate(delta_values):
                        raw = lookup[(p, float(eta), float(r))]
                        actual = float(phase_image.get_array()[ei, ri])
                        phase_pointwise.append({"P_l": p, "eta": float(eta), "delta": float(r),
                                                "processed_value": raw, "image_value": actual,
                                                "match": raw == actual})
            if row != 2:
                ax.set_xticks([0, .25, .5, .75, 1])
                ax.xaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
            ax.set_yticks([0, .25, .5, .75, 1])
            # Tick placement must not widen measured half-cell extents.
            if row == 1:
                ax.set_xlim(data["xlim"])
                ax.set_ylim(data["ylim"])
            ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
            ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT,
                           labelleft=column == 0, labelbottom=True)
            if row != 2:
                ax.set_xlabel(r"Dilemma intensity, $\delta$" if column == 2 else "", labelpad=1)
            else:
                ax.xaxis.labelpad = 1
            ax.yaxis.labelpad = 2
            label_artists.append(fig.text(
                left / width, (bottom + panel_height + 3.4) / height,
                f"({string.ascii_lowercase[row * 5 + column]})", ha="left", va="baseline"))
            actual_digest = figure_data_digest(SimpleNamespace(axes=[ax]))
            item = {"row": row_names[row], "P_l": p,
                    "redrawn_data_sha256": actual_digest,
                    "processed_point_count": 123 if row == 0 else (0 if row == 2 else 861),
                    "all_processed_points_match": True}
            if row == 0:
                if actual_digest != curve_metadata["data_sha256"]:
                    raise ValueError(f"Measured curve arrays changed: {curve_cache}")
                semantics = _check_cached_semantics(
                    ax, curve_data, axes[0].get_ylabel(), display_xlabel=column == 2,
                    display_ylabel=column == 0, display_xticklabels=True, display_yticklabels=column == 0)
                if not semantics["match"]:
                    raise ValueError(f"Figure D3 curve display semantics changed: {curve_cache}")
                item.update(cached_curve_data_sha256=curve_metadata["data_sha256"], display_semantics=semantics)
            if row == 2:
                item.update(box_observations=box_check["scatter_count"],
                            box_count=box_check["box_count"], all_box_artists_match=box_check["all_match"])
            if row == 1:
                if actual_digest != metadata["data_sha256"]:
                    raise ValueError(f"Scientific arrays changed while redrawing {cache}")
                semantics = _check_cached_semantics(
                    ax, {**data, "ylabel": phase_ylabel}, axes[5].get_ylabel(), display_xlabel=column == 2,
                    display_ylabel=column == 0, display_xticklabels=True,
                    display_yticklabels=column == 0)
                if not semantics["match"]:
                    raise ValueError(f"Figure D3 heatmap display semantics changed: {cache}")
                item.update({"cached_data_sha256": metadata["data_sha256"],
                             "display_semantics": semantics,
                             "ylabel_display_substitution": {"source": data["ylabel"], "display": phase_ylabel}})
            comparisons.append(item)
            source = curve_cache if row == 0 else (table_path.parent / "box_plot_data.csv" if row == 2 else cache)
            placements.append({"source": source.relative_to(root).as_posix(),
                               "P_l": p, "row": item["row"], "x_mm": left, "y_mm": bottom,
                               "axes_width_mm": panel_width, "axes_height_mm": panel_height,
                               "scale": 1.0, "xlabel_visible": column == 2, "xticklabels_visible": True,
                               "render_mode": "native_from_complete_processed_data"})
    if (len(curve_pointwise) != 615 or len(phase_pointwise) != 4305
            or not all(point["match"] for point in (*curve_pointwise, *phase_pointwise))):
        plt.close(fig)
        raise ValueError("Figure D3 curve or phase observations differ from the processed table")

    # Align the visible legend handles with the colorbar, accounting for the
    # invisible legend padding while preserving its vertical center and spacing.
    key_left_mm = 146.0
    legend_borderpad = .1
    legend_anchor_mm = key_left_mm - legend_borderpad * 8 * 25.4 / 72
    legend = fig.legend(line_handles, [rf"${eta:g}$" for eta in CURVE_ETA], title=r"$\eta$",
                        loc="center left", bbox_to_anchor=(legend_anchor_mm / width, 115 / height),
                        frameon=False, borderaxespad=0, borderpad=legend_borderpad, handlelength=1.1,
                        handletextpad=.4, labelspacing=.45)
    box_legend = add_box_legend(fig, (150 / width, 29 / height))
    bar_ax = fig.add_axes([key_left_mm / width, 57 / height, 2 / width, panel_height / height])
    bar = fig.colorbar(phase_image, cax=bar_ax, orientation="vertical")
    bar.set_ticks([0, .25, .5, .75, 1])
    bar_ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
    bar_ax.tick_params(length=2, pad=DEFAULT_TICK_PAD_PT)
    bar.set_label(r"Cooperation rate, $\bar{F}_c$", labelpad=2)
    bar.outline.set_linewidth(LINE_WIDTH_PT)
    _apply_figure_style(fig)
    # Mark each panel with the P_l value for its column.
    for index, ax in enumerate(axes):
        ax.set_title(rf"$P_l={PL_VALUES[index % 5]:g}$", fontsize=8, pad=3)
    for column, box_check in enumerate(box_checks):
        box_ax = axes[10 + column]
        digest = figure_data_digest(SimpleNamespace(axes=[box_ax]))
        patch_paths = [patch.get_path().vertices for patch in box_ax.patches]
        patches_match = (len(patch_paths) == len(box_patch_snapshots[column])
                         and all(np.array_equal(before, after) for before, after in
                                 zip(box_patch_snapshots[column], patch_paths)))
        if digest != box_check["artist_data_sha256_before_style"] or not patches_match:
            raise ValueError("Figure D3 shared styling changed supplied box/scatter/mean values")
        box_check.update(artist_data_sha256_after_style=digest,
                         box_vertices_unchanged_after_style=patches_match,
                         artists_match_after_shared_style=True)
    # Category ticks are interior bin centers, not numeric-axis endpoints.
    _inset_terminal_ticklabels(axes[:10])
    align_subplot_labels(fig, axes, label_artists)
    layout = _check_layout(fig, axes, legend, bar_ax, width, height)
    title_renderer = fig.canvas.get_renderer()
    layout["parameter_titles"] = [
        {"panel": string.ascii_lowercase[index], "P_l": PL_VALUES[index % 5],
         "text": ax.get_title(),
         "bounds_mm": (ax.title.get_window_extent(title_renderer).extents * 25.4 / fig.dpi).tolist()}
        for index, ax in enumerate(axes)]
    layout.update({"paper_figure": "Figure D3", "rows": 3, "columns": 5, "scientific_axes": 15,
                   "shared_axis_labels": True,
                   **_legend_center_geometry(fig, axes[:5], legend),
                   "major_ticks": [{"panel": string.ascii_lowercase[index],
                                    "x": ax.get_xticks().tolist(), "y": ax.get_yticks().tolist()}
                                   for index, ax in enumerate(axes)]})
    renderer = fig.canvas.get_renderer()
    box_key_bounds = box_legend.get_window_extent(renderer).frozen()
    box_center = (box_key_bounds.y0 + box_key_bounds.y1) / 2 * 25.4 / fig.dpi
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
    layout["row_gaps_mm"] = [13.0, 13.0]
    layout.update(box_legend_bounds_mm=(box_key_bounds.extents * 25.4 / fig.dpi).tolist(),
                  box_legend_center_y_mm=box_center, box_plot_center_y_mm=29.0,
                  box_legend_center_error_mm=abs(box_center - 29.0),
                  row_order=list(row_names))
    if (box_key_bounds.x0 < -.25 or box_key_bounds.y0 < -.25
            or box_key_bounds.x1 > fig.bbox.width + .25 or box_key_bounds.y1 > fig.bbox.height + .25):
        layout["violations"].append("Box legend outside canvas")
    for index, ax in enumerate(axes):
        plot_bounds = ax.get_window_extent(renderer)
        if (min(box_key_bounds.x1, plot_bounds.x1) - max(box_key_bounds.x0, plot_bounds.x0) > .2
                and min(box_key_bounds.y1, plot_bounds.y1) - max(box_key_bounds.y0, plot_bounds.y0) > .2):
            layout["violations"].append(f"Box legend overlaps plotting area {index + 1}")
    if layout["box_legend_center_error_mm"] > 1e-8:
        layout["violations"].append("Box legend is not centered on the box plotting row")
    handle = legend.get_lines()[0]
    handle_left_mm = float(handle.get_transform().transform(handle.get_xydata())[:, 0].min() * 25.4 / fig.dpi)
    colorbar_left_mm = float(bar_ax.get_window_extent(renderer).x0 * 25.4 / fig.dpi)
    layout.update(legend_handle_left_mm=handle_left_mm, colorbar_left_mm=colorbar_left_mm,
                  side_key_left_alignment_error_mm=abs(handle_left_mm-colorbar_left_mm))
    if layout["side_key_left_alignment_error_mm"] > 1e-8:
        layout["violations"].append("Legend handles and colorbar must share their left edge")
    if layout["font_sizes_pt"] != [8.0] or layout["font_families"] != ["Times New Roman"]:
        layout["violations"].append("Figure D3 text must use 8 pt Times New Roman")
    (root / "交付/FigD3完整布局检查.json").write_text(
        json.dumps(layout, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if layout["violations"]:
        fig.savefig(root / "tmp/FigD3_complete_layout_failure.png", dpi=180, bbox_inches=None)
        plt.close(fig)
        raise ValueError(f"Figure D3 layout check failed: {layout['violations'][:5]}")
    fig.savefig(target, dpi=DPI, bbox_inches=None, facecolor="white")
    plt.close(fig)
    report = {"paper_figure": "Figure D3", "width_mm": width, "height_mm": height,
              "rows": 3, "columns": 5, "scientific_axes": 15,
              "row_order": list(row_names),
              "shared_axis_labels": True, "individual_ylabels": 3,
              "bottom_row_xlabels": 1, "middle_row_xlabels": 1, "top_row_xlabels": 1,
              "render_mode": "native_from_complete_processed_data",
              "processed_file": table_path.relative_to(root).as_posix(),
              "processed_file_sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
              "processed_observations": len(lookup), "phase_points_verified": len(phase_pointwise),
              "curve_points_verified": len(curve_pointwise), "curve_eta": list(CURVE_ETA),
              "phase_eta": eta_values.tolist(), "delta_values": delta_values.tolist(),
              "scientific_arrays_verified": len(comparisons), "cached_phase_digests_verified": 5, "cached_curve_digests_verified": 5,
              "missing_points": 0, "duplicate_points": 0, "interpolated_points": 0,
              "display_interpolation": "bicubic", "display_resample": True,
              "render_dpi": DPI, "source_values_modified": False,
              "all_points_match": True, "panels": comparisons,
              "curve_pointwise_matches": curve_pointwise, "phase_pointwise_matches": phase_pointwise,
              "box_observations_verified": sum(item["scatter_count"] for item in box_checks),
              "boxes_verified": sum(item["box_count"] for item in box_checks),
              "box_data_audit": box_audit, "box_artist_checks": box_checks}
    (root / "交付/FigD3完整布局数据检查.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (root / "交付/FigD3箱线图数据检查.json").write_text(
        json.dumps({**box_audit, "paper_figure": "Figure D3", "artist_checks": box_checks,
                    "all_artists_match": True}, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return target, placements
