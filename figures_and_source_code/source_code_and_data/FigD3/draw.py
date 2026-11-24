# -*- coding: utf-8 -*-
"""
按不同 p 绘制 Cooperation rate-b 线图。

输入数据格式：
    G  alpha  b  p  Coop_Rate

绘图规则：
    - 每个 p 值对应一张图；
    - 横坐标为 b，纵坐标为合作率；
    - 每张图只绘制 alpha = 0、0.25、0.5 三条曲线。
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import ETA_COLORS
from figure_layout import panel_inches, full_inches

configure_style()
TARGET_ALPHA_VALUES = [0.00, 0.25, 0.50]
FLOAT_TOLERANCE = 1e-8


def parse_data(file_path: Path):
    """读取数据并返回 (G, alpha, b, p, Coop_Rate) 元组列表。"""
    rows = []

    with file_path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()

            # 跳过空行、横线分隔符和表头
            if not line or line.startswith("-") or line.lower().startswith("g"):
                continue

            parts = line.split()
            if len(parts) < 5:
                continue

            try:
                g_value = int(float(parts[0]))
                alpha_value = float(parts[1])
                b_value = float(parts[2])
                p_value = float(parts[3])
                coop_rate = float(parts[4])
            except ValueError:
                # 自动跳过 N/A 等无效值
                continue

            rows.append((g_value, alpha_value, b_value, p_value, coop_rate))

    return rows


def standard_alpha(alpha_value: float):
    """将接近目标 alpha 的值映射为标准值，否则返回 None。"""
    for target in TARGET_ALPHA_VALUES:
        if abs(alpha_value - target) < FLOAT_TOLERANCE:
            return target
    return None


def average_duplicate_points(points):
    """对相同 b 参数点的重复合作率取平均，并按 b 排序。"""
    values_by_b = defaultdict(list)
    for b_value, coop_rate in points:
        values_by_b[b_value].append(coop_rate)

    return sorted(
        (
            (b_value, sum(values) / len(values))
            for b_value, values in values_by_b.items()
        ),
        key=lambda item: item[0],
    )


def plot_for_g_p(rows, g_value: int, p_value: float, output_dir: Path):
    """为固定的 (G, p) 绘制三条不同 alpha 的合作率曲线。"""
    data_by_alpha = defaultdict(list)

    for row_g, row_alpha, row_b, row_p, row_coop_rate in rows:
        if row_g != g_value or abs(row_p - p_value) >= FLOAT_TOLERANCE:
            continue

        alpha_value = standard_alpha(row_alpha)
        if alpha_value is None:
            continue

        data_by_alpha[alpha_value].append((row_b, row_coop_rate))

    if not data_by_alpha:
        print(f"[Warning] G={g_value}, p={p_value:.2f} 没有符合条件的数据。")
        return None

    fig, ax = plt.subplots(figsize=panel_inches("FigD3"))

    # 延续 draw.py 的线宽、空心标记和区分明显的配色风格
    line_styles = {
        0.00: {"color": ETA_COLORS[0.00], "marker": "o"},
        0.25: {"color": ETA_COLORS[0.25], "marker": "s"},
        0.50: {"color": ETA_COLORS[0.50], "marker": "^"},
    }

    for alpha_value in TARGET_ALPHA_VALUES:
        if alpha_value not in data_by_alpha:
            print(
                f"[Warning] G={g_value}, p={p_value:.2f} "
                f"缺少 alpha={alpha_value:.2f} 的数据。"
            )
            continue

        points = average_duplicate_points(data_by_alpha[alpha_value])
        b_values = [point[0] for point in points]
        coop_rates = [point[1] for point in points]
        style = line_styles[alpha_value]

        ax.plot(
            b_values,
            coop_rates,
            color=style["color"],
            marker=style["marker"],
            linewidth=LINE_WIDTH_PT,
            markersize=4.5,
            markerfacecolor="white",
            markeredgewidth=LINE_WIDTH_PT,
            label=rf"$\eta = {alpha_value:.2f}$",
        )

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel(r"$\delta$")
    ax.set_ylabel(r"Cooperation rate, $\bar{F}_c$")
    ax.set_title(rf"$g = {g_value},\ P_l = {p_value:.2f}$")

    ax.set_xticks([i / 4 for i in range(5)])
    ax.set_yticks([i / 4 for i in range(5)])
    ax.tick_params(axis="both")

    ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=0.35)
    ax.legend(
        title=r"$\eta$",
        loc="best",
        frameon=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    p_filename = f"{p_value:.2f}".replace(".", "p")
    output_path = output_dir / f"cooprate_G_{g_value}_p_{p_filename}.png"
    save_figure(fig, output_path, bbox_inches="tight")
    print(f"[Saved] {output_path.resolve()}")

    plt.close(fig)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="按 p 分图，绘制不同 alpha 下的 Cooperation rate-b 曲线。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DATA_DIR / "processed_coop_data.txt",
        help="输入数据文件路径。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR / "figures" / "line_plots_by_p",
        help="结果图片输出文件夹。",
    )
    args = parser.parse_args()

    input_file = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not input_file.is_file():
        raise FileNotFoundError(f"找不到输入文件：{input_file}")

    rows = parse_data(input_file)
    if not rows:
        raise ValueError(f"文件中没有读取到有效数据：{input_file}")

    # 数据中每个 (G, p) 对应一张线图
    g_p_values = sorted({(row[0], row[3]) for row in rows})
    saved_files = []

    for g_value, p_value in g_p_values:
        output_path = plot_for_g_p(rows, g_value, p_value, output_dir)
        if output_path is not None:
            saved_files.append(output_path)

    print(f"全部完成，共生成 {len(saved_files)} 张线图。")


if __name__ == "__main__":
    main()
