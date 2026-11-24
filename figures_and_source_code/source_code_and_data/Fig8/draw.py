"""MPD ORH：每个 p 一张图，五种 dist 曲线，横轴 b、纵轴 final_avg_fc。

默认从随图归档的全群体合作率 CSV 绘制。也可显式指定历史 Excel。
"""

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import DIST_COLORS
from figure_layout import panel_inches, full_inches
from paper_mpd_boxplots import load_orh_mpd_global

configure_style()
DEFAULT_INPUT = SCRIPT_DIR / "data" / "fig1_global.csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "figures" / "mpd_line_plots_by_p"

# 图例名称、概率向量、顺序、颜色和标记均沿用原 PGG 绘图脚本。
# 概率向量仅作图例说明，不参与数据计算。
DIST_STYLES = {
    "strongly_convex": {
        "name": "SCv",
        "vector": "{0, 0, 1, 0, 0}",
        "color": DIST_COLORS["strongly_convex"], "marker": "o",
    },
    "convex": {
        "name": r"Convex ($\beta = 1.2$)",
        "vector": "{0.007, 0.322, 0.342, 0.322, 0.007}",
        "color": DIST_COLORS["convex"], "marker": "s",
    },
    "flat": {
        "name": r"Flat ($\beta = 1$)",
        "vector": "{0.2, 0.2, 0.2, 0.2, 0.2}",
        "color": DIST_COLORS["flat"], "marker": "^",
    },
    "concave": {
        "name": r"Concave ($\beta = 0.9$)",
        "vector": "{0.410, 0.061, 0.059, 0.061, 0.410}",
        "color": DIST_COLORS["concave"], "marker": "D",
    },
    "strongly_concave": {
        "name": "SCc",
        "vector": "{0.5, 0, 0, 0, 0.5}",
        "color": DIST_COLORS["strongly_concave"], "marker": "v",
    },
}


def normalize_dist(value):
    """兼容 dist 的数值、数值字符串和名称。"""
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in DIST_STYLES:
        return text
    try:
        number = float(text)
    except (ValueError, TypeError):
        raise ValueError(f"无法识别 dist={value!r}") from None
    for target, name in ((1.2, "convex"), (1.0, "flat"), (0.9, "concave")):
        if abs(number - target) < 1e-8:
            return name
    raise ValueError(f"无法识别 dist={value!r}")


def parse_data(file_path, sheet_name=None):
    """从发布包或显式指定的历史 Excel 返回 (dist, p, b, rate)。"""
    if file_path.suffix.lower() == ".csv":
        if sheet_name is not None:
            raise ValueError("--sheet 仅用于 Excel 输入")
        distributions = {f"D{index}": name for index, name in enumerate(DIST_STYLES, 1)}
        return [(distributions[row["dist_code"]], row["p"], row["b"], row["final_avg_fc"])
                for row in load_orh_mpd_global(file_path)]
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        if sheet_name is not None and sheet_name not in workbook.sheetnames:
            raise ValueError(f"不存在工作表 {sheet_name!r}，可选：{workbook.sheetnames}")
        sheet = workbook.worksheets[0] if sheet_name is None else workbook[sheet_name]
        records = sheet.iter_rows(values_only=True)
        header = next(records, None)
        if header is None:
            raise ValueError("工作表为空。")
        names = [str(value).strip() if value is not None else "" for value in header]
        required = ("dist", "p", "b", "final_avg_fc")
        for name in required:
            if names.count(name) != 1:
                raise ValueError(f"列 {name!r} 必须存在且只能出现一次。")
        indices = {name: names.index(name) for name in required}
        rows = []
        for row_number, record in enumerate(records, start=2):
            if all(value is None for value in record):
                continue
            try:
                p, b = (float(record[indices[name]]) for name in ("p", "b"))
                if not all(math.isfinite(value) for value in (p, b)):
                    raise ValueError("p、b 必须是有限数值")
                dist = normalize_dist(record[indices["dist"]])
                raw_rate = record[indices["final_avg_fc"]]
                if raw_rate is None or str(raw_rate).strip().upper() in ("", "N/A", "NA", "NAN"):
                    rate = math.nan
                else:
                    rate = float(raw_rate)
                    if not math.isfinite(rate) or not 0 <= rate <= 1:
                        raise ValueError("final_avg_fc 必须在 0～1 之间，或为空值/N/A")
                rows.append((dist, round(p, 12), round(b, 12), rate))
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError(f"工作表 {sheet.title!r} 第 {row_number} 行：{error}") from error
        print(f"[Info] 工作表：{sheet.title}；读取 {len(rows)} 行数据。")
        return rows
    finally:
        workbook.close()


def average_duplicate_points(points):
    """沿用原脚本：同一 p、dist、b 的重复值取均值，全缺失时保留 NaN。"""
    values_by_b = defaultdict(list)
    for b, rate in points:
        values_by_b[b].append(rate)
    averaged = []
    for b, rates in values_by_b.items():
        valid = [rate for rate in rates if math.isfinite(rate)]
        averaged.append((b, sum(valid) / len(valid) if valid else math.nan))
    return sorted(averaged)


def group_data(rows):
    groups = defaultdict(lambda: defaultdict(list))
    for dist, p, b, rate in rows:
        groups[p][dist].append((b, rate))
    return groups


def filename_number(value):
    return format(value, ".12f").rstrip("0").rstrip(".") or "0"


def plot_for_p(data_by_dist, p, b_limits, output_dir):
    """固定 p，将五种 dist 按 b 递增画在同一张图中。"""
    import matplotlib.pyplot as plt

    missing = [name for name in DIST_STYLES if name not in data_by_dist]
    if missing:
        print(f"[Warning] p={p:g} 缺少分布：{', '.join(missing)}")
    fig, ax = plt.subplots(figsize=panel_inches("Fig8"))
    for dist, style in DIST_STYLES.items():
        if dist not in data_by_dist:
            continue
        raw_points = data_by_dist[dist]
        points = average_duplicate_points(raw_points)
        if len(raw_points) != len(points):
            print(f"[Info] p={p:g}, {style['name']}：重复 b 已取均值。")
        ax.plot(
            [point[0] for point in points], [point[1] for point in points],
            color=style["color"], marker=style["marker"], linewidth=LINE_WIDTH_PT,
            markersize=4.5, markerfacecolor="white", markeredgewidth=LINE_WIDTH_PT,
            label=style["name"], clip_on=False,
        )
    left, right = b_limits
    if left == right:
        padding = max(abs(left) * 0.05, 0.01)
        left, right = left - padding, right + padding
    ax.set_xlim(left, right)
    ax.set_ylim(0, 1)
    ax.set_xlabel(r"$\delta$")
    ax.set_ylabel(r"Cooperation rate, $\bar{F}_c$")
    ax.set_title(rf"$P_l = {p:g}$")
    ax.set_xticks([left + (right - left) * i / 4 for i in range(5)])
    ax.set_yticks([i / 5 for i in range(6)])
    ax.tick_params(axis="both")
    ax.set_axisbelow(True)
    ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=0.35)
    ax.legend(loc="best", frameon=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"mpd_cooprate_p_{filename_number(p)}.png"
    save_figure(fig, output_path, bbox_inches="tight")
    print(f"[Saved] {output_path.resolve()}")
    return fig


def main():
    parser = argparse.ArgumentParser(
        description="MPD ORH：按 p 分图，比较五种 dist 的 final_avg_fc 随 b 的变化。"
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="发布包 CSV 或历史 Excel 路径。")
    parser.add_argument("--sheet", default=None, help="Excel 工作表名称，默认第一张表。")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="图片输出目录。")
    parser.add_argument("--no-show", action="store_true", help="只保存图片，不显示窗口。")
    args = parser.parse_args()
    import matplotlib
    if args.no_show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        rows = parse_data(Path(args.input), args.sheet)
        if not rows:
            raise ValueError("没有可绘制的数据。")
        groups = group_data(rows)
        b_values = [row[2] for row in rows]
        limits = (min(b_values), max(b_values))
        print(f"[Info] 将生成 {len(groups)} 张图，按 p 分组，每张比较五种分布。")
        for p, data_by_dist in sorted(groups.items()):
            figure = plot_for_p(data_by_dist, p, limits, Path(args.output_dir))
            if args.no_show:
                plt.close(figure)
        if not args.no_show:
            plt.show()
    except (OSError, ValueError) as error:
        print(f"[Error] {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
