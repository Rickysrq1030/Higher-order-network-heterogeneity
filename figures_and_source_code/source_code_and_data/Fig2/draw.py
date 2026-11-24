import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import M_COLORS, LINE_COLORS
from figure_layout import panel_inches

configure_style()

# 只保留alpha=0
TARGET_ALPHA = 0.0

# 浮点数比较容差
FLOAT_TOLERANCE = 1e-8

# 与之前相图一致的深蓝—深红配色
M_STYLES = {
    1: {
        "color": M_COLORS[1],
        "marker": "o",
        "linestyle": "-",
    },
    2: {
        "color": M_COLORS[2],
        "marker": "s",
        "linestyle": "-",
    },
}


def float_equal(value1: float, value2: float):
    """判断两个浮点数是否近似相等。"""
    return abs(value1 - value2) < FLOAT_TOLERANCE


def parse_data(file_path: Path):
    """
    读取数据，并且只返回alpha=0的数据。

    每条数据格式：
    (m, alpha, p, r, Coop_Rate)
    """
    rows = []

    with file_path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()

            # 跳过空行、分隔线和表头
            if (
                not line
                or line.startswith("-")
                or line.lower().startswith("m")
            ):
                continue

            parts = line.split()

            if len(parts) < 5:
                continue

            try:
                m_value = int(float(parts[0]))
                alpha_value = float(parts[1])
                p_value = float(parts[2])
                r_value = float(parts[3])

                # 只保留alpha=0的数据
                if not float_equal(alpha_value, TARGET_ALPHA):
                    continue

                # 将N/A保存为np.nan
                # 绘图时对应位置会出现曲线断点
                if parts[4].upper() == "N/A":
                    coop_rate = np.nan
                else:
                    coop_rate = float(parts[4])

                rows.append(
                    (
                        m_value,
                        alpha_value,
                        p_value,
                        r_value,
                        coop_rate,
                    )
                )

            except ValueError:
                # 跳过无法解析的数据行
                continue

    return rows


def average_duplicate_points(points):
    """
    对相同r坐标的重复合作率数据取平均。

    points格式：
    [(r, Coop_Rate), ...]
    """
    values_by_r = defaultdict(list)

    for r_value, coop_rate in points:
        values_by_r[r_value].append(coop_rate)

    averaged_points = []

    for r_value, coop_values in values_by_r.items():
        coop_array = np.asarray(
            coop_values,
            dtype=float,
        )

        # 去除N/A数据
        valid_values = coop_array[
            ~np.isnan(coop_array)
        ]

        if len(valid_values) == 0:
            mean_coop_rate = np.nan
        else:
            mean_coop_rate = np.mean(valid_values)

        averaged_points.append(
            (r_value, mean_coop_rate)
        )

    # 按r从小到大排列
    averaged_points.sort(
        key=lambda item: item[0]
    )

    return averaged_points


def plot_for_p(rows, p_value: float, output_dir: Path):
    """
    为一个p值绘制一张图片。

    同一张图中不同m对应不同曲线。
    数据已经被限制为alpha=0。
    """
    # 筛选当前p的数据
    current_p_rows = [
        row
        for row in rows
        if float_equal(row[2], p_value)
    ]

    if not current_p_rows:
        print(
            f"[Warning] 没有找到 "
            f"alpha={TARGET_ALPHA:.2f}, "
            f"p={p_value:.2f} 的数据。"
        )
        return None

    # 获取当前p下的全部m值
    m_values = sorted({
        row[0]
        for row in current_p_rows
    })

    fig, ax = plt.subplots(
        figsize=panel_inches("Fig2")
    )

    for m_index, m_value in enumerate(m_values):
        # 提取当前m对应的数据
        selected_points = [
            (row[3], row[4])
            for row in current_p_rows
            if row[0] == m_value
        ]

        if not selected_points:
            continue

        # 对相同r坐标的重复数据取平均
        averaged_points = average_duplicate_points(
            selected_points
        )

        r_values = [
            point[0]
            for point in averaged_points
        ]

        coop_rates = [
            point[1]
            for point in averaged_points
        ]

        # 使用预设颜色
        if m_value in M_STYLES:
            style = M_STYLES[m_value]
        else:
            # 当前 m=3 及以后新增曲线都使用统一线图色系。
            style = {
                "color": M_COLORS.get(m_value, LINE_COLORS[m_index % len(LINE_COLORS)]),
                "marker": "^",
                "linestyle": "-",
            }

        ax.plot(
            r_values,
            coop_rates,
            color=style["color"],
            marker=style["marker"],
            linestyle=style["linestyle"],
            linewidth=LINE_WIDTH_PT,
            markersize=4.5,
            markerfacecolor="white",
            markeredgecolor=style["color"],
            markeredgewidth=LINE_WIDTH_PT,
            label=rf"$m = {m_value}$",
        )

    # 坐标轴范围
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 1)

    # 坐标轴标签
    ax.set_xlabel(
        r"$r$",
        fontsize=8,
    )

    ax.set_ylabel(
        r"Cooperation rate, $\bar{F}_c$",
        fontsize=8,
    )

    # 图片标题
    ax.set_title(
        rf"$P_l={p_value:.2f}$",
        fontsize=8,
    )

    # 设置刻度
    ax.set_xticks(
        np.arange(0, 2.01, 0.5)
    )

    ax.set_yticks(
        np.arange(0, 1.01, 0.2)
    )

    ax.tick_params(
        axis="both",
        labelsize=8,
    )

    # 添加网格
    ax.grid(
        True,
        linestyle="--",
        linewidth=LINE_WIDTH_PT,
        alpha=0.35,
    )

    # 添加图例
    ax.legend(
        title=r"$m$",
        fontsize=8,
        title_fontsize=8,
        loc="best",
        frameon=True,
    )


    # 创建输出目录
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"cooprate_alpha_0_p_{p_value:.2f}.png"
    )

    # 保存图片
    save_figure(
        fig,
        output_path,
        bbox_inches="tight",
    )

    print(f"[Saved] {output_path.resolve()}")

    return fig


def main():
    parser = argparse.ArgumentParser(
        description=(
            "只保留alpha=0的数据，"
            "针对每个p绘制一张Cooperation rate-r线图。"
        )
    )

    parser.add_argument(
        "--input",
        default=str(SCRIPT_DIR / "data" / "processed_coop_data.txt"),
        help="输入数据文件路径。",
    )

    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "figures" / "pggm_alpha_0_line_plots"),
        help="图片输出文件夹。",
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
        help="只保存图片，不显示绘图窗口。",
    )

    args = parser.parse_args()

    input_file = Path(args.input)

    if not input_file.exists():
        print(
            f"[Error] 找不到输入文件："
            f"{input_file}"
        )
        return

    # 读取时已经删除了所有alpha不等于0的数据
    rows = parse_data(input_file)

    if not rows:
        print(
            "[Error] 没有读取到alpha=0的有效数据。"
        )
        return

    print(
        f"[Info] 筛选后剩余 {len(rows)} 行alpha=0的数据。"
    )

    # 获取alpha=0数据中的所有p值
    p_values = sorted({
        row[2]
        for row in rows
    })

    print(
        "[Info] 将绘制以下p值："
        + ", ".join(
            f"{p_value:.2f}"
            for p_value in p_values
        )
    )

    output_dir = Path(
        args.output_dir
    )

    figures = []

    # 每个p绘制一张图
    for p_value in p_values:
        figure = plot_for_p(
            rows=rows,
            p_value=p_value,
            output_dir=output_dir,
        )

        if figure is not None:
            figures.append(figure)

    if args.no_show:
        for figure in figures:
            plt.close(figure)
    else:
        plt.show()


if __name__ == "__main__":
    main()
