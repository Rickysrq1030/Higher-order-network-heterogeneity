import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import PL_COLORS
from figure_layout import panel_inches

configure_style()

# 只绘制以下两个 G 值
TARGET_G_VALUES = [3,4, 5]

# 每张图只绘制以下五个 p 值
TARGET_P_VALUES = [0.00, 0.25, 0.50, 0.75, 1.00]

# 浮点数比较容差
FLOAT_TOLERANCE = 1e-8


def parse_data(file_path: Path):
    """
    读取文本数据。

    返回格式：
    [
        (G, N, alpha, p, r, Coop_Rate),
        ...
    ]
    """
    rows = []

    with file_path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()

            # 跳过空行、横线分隔符和表头
            if (
                not line
                or line.startswith("-")
                or line.lower().startswith("g")
            ):
                continue

            # 按任意空白字符分割
            parts = line.split()

            if len(parts) < 6:
                continue

            try:
                # 数据格式：
                # G, N, alpha, p, r, Coop_Rate
                g_value = int(float(parts[0]))
                n_value = int(float(parts[1]))
                alpha_value = float(parts[2])
                p_value = float(parts[3])
                r_value = float(parts[4])
                coop_rate = float(parts[5])

                rows.append(
                    (
                        g_value,
                        n_value,
                        alpha_value,
                        p_value,
                        r_value,
                        coop_rate,
                    )
                )

            except ValueError:
                # 跳过无法转换成数值的数据行
                continue

    return rows


def is_target_p(p_value: float):
    """
    判断当前 p 是否属于需要绘制的五个 p 值。

    浮点数计算可能存在微小误差，因此不直接使用 p_value in TARGET_P_VALUES。
    """
    return any(
        abs(p_value - target_p) < FLOAT_TOLERANCE
        for target_p in TARGET_P_VALUES
    )


def get_standard_p(p_value: float):
    """
    将接近目标值的 p 转换成标准的目标 p 值。

    例如：
    0.25000000001 会转换成 0.25。
    """
    for target_p in TARGET_P_VALUES:
        if abs(p_value - target_p) < FLOAT_TOLERANCE:
            return target_p

    return None


def average_duplicate_points(points):
    """
    对相同 r 值的重复合作率数据取平均值。

    参数 points 的格式为：
    [(r, Coop_Rate), ...]

    返回格式为：
    [(r, 平均Coop_Rate), ...]
    """
    values_by_r = defaultdict(list)

    for r_value, coop_rate in points:
        values_by_r[r_value].append(coop_rate)

    averaged_points = []

    for r_value, coop_values in values_by_r.items():
        mean_coop_rate = sum(coop_values) / len(coop_values)
        averaged_points.append((r_value, mean_coop_rate))

    # 按横坐标 r 从小到大排序
    averaged_points.sort(key=lambda item: item[0])

    return averaged_points


def plot_for_g_alpha(
    rows,
    g_value: int,
    alpha_value: float,
    output_dir: Path,
):
    """
    为给定的 G 和 alpha 绘制一张线图。

    每张图中只包含：
    p = 0、0.25、0.5、0.75、1.0
    """
    # 保存不同 p 对应的 (r, Coop_Rate)
    data_by_p = defaultdict(list)

    for (
        row_g,
        _,
        row_alpha,
        row_p,
        row_r,
        row_coop_rate,
    ) in rows:

        # 筛选指定的 G
        if row_g != g_value:
            continue

        # 筛选指定的 alpha
        if abs(row_alpha - alpha_value) >= FLOAT_TOLERANCE:
            continue

        # 只保留五个目标 p 值
        if not is_target_p(row_p):
            continue

        # 将 p 修正到标准值
        standard_p = get_standard_p(row_p)

        data_by_p[standard_p].append(
            (row_r, row_coop_rate)
        )

    if not data_by_p:
        print(
            f"[Warning] G={g_value}, alpha={alpha_value:.2f} "
            "没有找到符合条件的数据。"
        )
        return

    # 创建画布
    fig, ax = plt.subplots(figsize=panel_inches("FigC1"))

    # 为五个 p 值指定颜色和标记
    line_styles = {
        0.00: {"color": PL_COLORS[0.00], "marker": "o"},
        0.25: {"color": PL_COLORS[0.25], "marker": "s"},
        0.50: {"color": PL_COLORS[0.50], "marker": "^"},
        0.75: {"color": PL_COLORS[0.75], "marker": "D"},
        1.00: {"color": PL_COLORS[1.00], "marker": "v"},
    }

    # 按指定顺序绘制五条曲线
    for p_value in TARGET_P_VALUES:
        if p_value not in data_by_p:
            print(
                f"[Warning] G={g_value}, alpha={alpha_value:.2f} "
                f"缺少 p={p_value:.2f} 的数据。"
            )
            continue

        # 对重复的 r 数据取平均，然后按 r 排序
        points = average_duplicate_points(data_by_p[p_value])

        r_values = [point[0] for point in points]
        coop_rates = [point[1] for point in points]

        style = line_styles[p_value]

        ax.plot(
            r_values,
            coop_rates,
            color=style["color"],
            marker=style["marker"],
            linewidth=LINE_WIDTH_PT,
            markersize=4.5,
            markerfacecolor="white",
            markeredgewidth=LINE_WIDTH_PT,
            label=rf"$P_l = {p_value:.2f}$",
        )

    # 设置坐标轴范围
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 1)

    # 设置坐标轴标题
    ax.set_xlabel(r"$r$", fontsize=8)
    ax.set_ylabel(r"Cooperation rate, $\bar{F}_c$", fontsize=8)

    # 设置图标题
    ax.set_title(
        rf"$g = {g_value}$",
        fontsize=8,
    )

    # 设置坐标轴刻度
    ax.set_xticks([i / 2 for i in range(5)])
    ax.set_yticks([i / 5 for i in range(6)])

    # 设置刻度文字大小
    ax.tick_params(axis="both", labelsize=8)

    # 添加浅灰色虚线网格
    ax.grid(
        True,
        linestyle="--",
        linewidth=LINE_WIDTH_PT,
        alpha=0.35,
    )

    # 添加图例
    ax.legend(
        title=r"$P_l$",
        fontsize=8,
        title_fontsize=8,
        loc="best",
        frameon=True,
    )

    # 调整边距，避免文字被截断

    # 创建输出文件夹
    output_dir.mkdir(parents=True, exist_ok=True)

    # 文件名不能使用星号，因此使用下划线连接参数
    output_path = (
        output_dir
        / f"cooprate_G_{g_value}_alpha_{alpha_value:.2f}.png"
    )

    # 保存600 dpi PNG和矢量PDF。
    save_figure(
        fig,
        output_path,
        bbox_inches="tight",
    )

    print(f"[Saved] {output_path.resolve()}")

    return fig


def resolve_input_path(input_path: str):
    """
    查找输入文件。

    首先检查用户提供的完整路径；
    如果没有找到，则在当前目录及其子目录中搜索同名文件。
    """
    path = Path(input_path)

    if path.exists():
        return path

    candidates = list(Path(".").rglob(path.name))

    if len(candidates) == 1:
        print(f"[Info] 使用搜索到的文件：{candidates[0]}")
        return candidates[0]

    if len(candidates) > 1:
        raise FileNotFoundError(
            f"找到多个名为 {path.name} 的文件，"
            "请通过 --input 指定完整路径。"
        )

    raise FileNotFoundError(
        f"找不到输入文件：{input_path}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "绘制 G=3 和 G=5 下不同 p 对应的"
            "Cooperation rate-r 曲线。"
        )
    )

    parser.add_argument(
        "--input",
        default=str(SCRIPT_DIR / "data" / "processed_coop_data.txt"),
        help="输入数据文件路径。",
    )

    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "figures" / "line_plots_G3_G5"),
        help="图片输出文件夹。",
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
        help="只保存图片，不弹出绘图窗口。",
    )

    args = parser.parse_args()

    try:
        input_file = resolve_input_path(args.input)
        rows = parse_data(input_file)

    except Exception as error:
        print(f"[Error] {error}")
        return

    if not rows:
        print(f"[Error] 文件中没有读取到有效数据：{input_file}")
        return

    print(f"[Info] 共读取到 {len(rows)} 行有效数据。")

    # 找出 G=3和G=5所对应的全部 alpha 值
    # 当前数据中通常只有 alpha=1，因此最终会输出两张图
    target_g_alpha = sorted(
        {
            (row[0], row[2])
            for row in rows
            if row[0] in TARGET_G_VALUES
        },
        key=lambda item: (item[0], item[1]),
    )

    if not target_g_alpha:
        print("[Error] 数据中没有找到 G=3 或 G=5。")
        return

    output_dir = Path(args.output_dir)

    figures = []

    for g_value, alpha_value in target_g_alpha:
        figure = plot_for_g_alpha(
            rows=rows,
            g_value=g_value,
            alpha_value=alpha_value,
            output_dir=output_dir,
        )

        if figure is not None:
            figures.append(figure)

    if args.no_show:
        # 不显示窗口时主动关闭图形，释放内存
        for figure in figures:
            plt.close(figure)
    else:
        plt.show()


if __name__ == "__main__":
    main()
