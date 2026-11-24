import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from openpyxl import load_workbook

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import M_COLORS, LINE_COLORS
from figure_layout import panel_inches

configure_style()

# 只保留alpha=0
TARGET_ALPHA = 0.0

# 每张图固定比较这三个 m；m=3 沿用原代码的自动配色和三角标记。
TARGET_M_VALUES = [1, 2, 3]

# 依赖安装：python -m pip install matplotlib numpy openpyxl
DEFAULT_INPUT = str(SCRIPT_DIR / "data" / "MPD_SRH_global_results.xlsx")

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


def parse_data(file_path: Path, sheet_name=None):
    """按列名读取 Excel，返回 (m, alpha, p, b, final_avg_fc)。

    必需列：m、p、b、final_avg_fc；第一行为表头。
    如果存在 alpha，沿用原代码只保留 alpha=0；缺少时按固定 alpha=0 处理。
    合作率空值或 N/A 保留为 NaN，使相应位置出现曲线断点。
    """
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0] if sheet_name is None else workbook[sheet_name]
        records = sheet.iter_rows(values_only=True)
        header = next(records, None)
        if header is None:
            raise ValueError("工作表为空。")
        names = [str(value).strip() if value is not None else "" for value in header]
        required_columns = ("m", "p", "b", "final_avg_fc")
        missing = [name for name in required_columns if name not in names]
        if missing:
            raise ValueError(f"缺少必要列：{', '.join(missing)}")
        for name in required_columns + ("alpha",):
            if names.count(name) > 1:
                raise ValueError(f"存在重复列名：{name}")
        indices = {name: names.index(name) for name in required_columns}
        alpha_index = names.index("alpha") if "alpha" in names else None

        rows = []
        skipped = 0
        filtered = 0
        for row_number, record in enumerate(records, start=2):
            if all(value is None for value in record):
                continue
            try:
                m_number = float(record[indices["m"]])
                alpha_value = (
                    float(record[alpha_index]) if alpha_index is not None else TARGET_ALPHA
                )
                p_value = float(record[indices["p"]])
                b_value = float(record[indices["b"]])
                if not all(np.isfinite(value) for value in (
                    m_number, alpha_value, p_value, b_value
                )):
                    raise ValueError("参数中含 NaN 或无穷值")
                if not m_number.is_integer():
                    raise ValueError("m 必须为整数")
                m_value = int(m_number)
                if not float_equal(alpha_value, TARGET_ALPHA) or m_value not in TARGET_M_VALUES:
                    filtered += 1
                    continue

                raw_rate = record[indices["final_avg_fc"]]
                if raw_rate is None or str(raw_rate).strip().upper() in ("", "N/A", "NA", "NAN"):
                    coop_rate = np.nan
                else:
                    coop_rate = float(raw_rate)
                    if np.isinf(coop_rate):
                        raise ValueError("合作率不能为无穷值")
                rows.append((m_value, alpha_value, p_value, b_value, coop_rate))
            except (TypeError, ValueError, OverflowError) as error:
                skipped += 1
                if skipped <= 5:
                    print(f"[Warning] 跳过第 {row_number} 行：{error}")

        print(f"[Info] 工作表：{sheet.title}；保留 {len(rows)} 行，条件过滤 {filtered} 行，异常跳过 {skipped} 行。")
        return rows
    finally:
        workbook.close()


def average_duplicate_points(points):
    """
    对相同b坐标的重复合作率数据取平均。

    points格式：
    [(b, Coop_Rate), ...]
    """
    values_by_b = defaultdict(list)

    for b_value, coop_rate in points:
        values_by_b[b_value].append(coop_rate)

    averaged_points = []

    for b_value, coop_values in values_by_b.items():
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
            (b_value, mean_coop_rate)
        )

    # 按b从小到大排列
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

    # 每张图固定按 m=1、2、3 的顺序绘制。
    m_values = TARGET_M_VALUES

    fig, ax = plt.subplots(
        figsize=panel_inches("Fig4")
    )

    for m_index, m_value in enumerate(m_values):
        # 提取当前m对应的数据
        selected_points = [
            (row[3], row[4])
            for row in current_p_rows
            if row[0] == m_value
        ]

        if not selected_points:
            print(f"[Warning] p={p_value:.2f} 缺少 m={m_value} 的数据。")
            continue

        # 对相同b坐标的重复数据取平均
        averaged_points = average_duplicate_points(
            selected_points
        )

        b_values = [
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
            b_values,
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
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # 坐标轴标签
    ax.set_xlabel(
        r"$\delta$",
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
        np.arange(0, 1.01, 0.25)
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
        / f"cooprate_alpha_{TARGET_ALPHA:g}_p_{p_value:.2f}.png"
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
            "针对每个p绘制一张Cooperation rate-b线图。"
        )
    )

    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help="输入 Excel 文件路径。",
    )

    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "figures" / "mpdm_alpha_0_line_plots"),
        help="图片输出文件夹。",
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
        help="只保存图片，不显示绘图窗口。",
    )

    parser.add_argument(
        "--sheet", default=None, help="工作表名称，默认读取第一张表。"
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
    try:
        rows = parse_data(input_file, sheet_name=args.sheet)
    except Exception as error:
        print(f"[Error] {error}")
        return

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
