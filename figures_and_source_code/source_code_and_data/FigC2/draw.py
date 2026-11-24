import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import load_workbook

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import PL_COLORS
from figure_layout import panel_inches

configure_style()

# 只绘制以下三个 G 值
TARGET_G_VALUES = [3, 4, 5]

# 每张图只绘制以下五个 p 值
TARGET_P_VALUES = [0.00, 0.25, 0.50, 0.75, 1.00]

# 浮点数比较容差
FLOAT_TOLERANCE = 1e-8

# 默认输入文件；也可以通过 --input 指定其他文件
DEFAULT_INPUT = str(SCRIPT_DIR / "data" / "MPD_URH_global_results.xlsx")


def parse_data(file_path: Path, sheet_name=None):
    """按表头读取 Excel，返回 [(G, p, b, final_avg_fc), ...]。

    默认读取第一张工作表，第一行为表头，其他列不会参与分组。
    data_only=True 读取公式单元格由 Excel 保存的计算结果。
    """
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        if sheet_name is None:
            sheet = workbook.worksheets[0]
        else:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(
                    f"不存在工作表 {sheet_name!r}，可选：{workbook.sheetnames}"
                )
            sheet = workbook[sheet_name]

        records = sheet.iter_rows(values_only=True)
        header = next(records, None)
        if header is None:
            raise ValueError("工作表为空。")

        # 根据列名定位数据，允许列顺序改变及表头两侧存在空白
        names = [str(value).strip() if value is not None else "" for value in header]
        required_columns = ("G", "p", "b", "final_avg_fc")
        missing = [name for name in required_columns if name not in names]
        if missing:
            raise ValueError(f"工作表缺少必要列：{', '.join(missing)}")
        duplicates = [name for name in required_columns if names.count(name) > 1]
        if duplicates:
            raise ValueError(f"工作表存在重复列名：{', '.join(duplicates)}")
        indices = [names.index(name) for name in required_columns]

        rows = []
        skipped = 0
        for row_number, record in enumerate(records, start=2):
            if all(value is None for value in record):
                continue
            try:
                g_number, p_value, b_value, coop_rate = (
                    float(record[index]) for index in indices
                )
                if not all(math.isfinite(value) for value in (
                    g_number, p_value, b_value, coop_rate
                )):
                    raise ValueError("关键列含 NaN 或无穷值")
                if not g_number.is_integer():
                    raise ValueError("G 必须为整数")
                rows.append((int(g_number), p_value, b_value, coop_rate))
            except (TypeError, ValueError, OverflowError) as error:
                skipped += 1
                if skipped <= 5:
                    print(f"[Warning] 跳过第 {row_number} 行：{error}")

        print(f"[Info] 工作表：{sheet.title}；有效 {len(rows)} 行，跳过 {skipped} 行。")
        return rows
    finally:
        workbook.close()


def get_standard_p(p_value: float):
    """将接近目标值的 p 转换成标准值，不符合条件则返回 None。"""
    for target_p in TARGET_P_VALUES:
        if abs(p_value - target_p) < FLOAT_TOLERANCE:
            return target_p
    return None


def average_duplicate_points(points):
    """对相同 b 值的重复合作率取平均，然后按 b 从小到大排序。"""
    values_by_b = defaultdict(list)
    for b_value, coop_rate in points:
        values_by_b[b_value].append(coop_rate)

    averaged_points = [
        (b_value, sum(coop_values) / len(coop_values))
        for b_value, coop_values in values_by_b.items()
    ]
    averaged_points.sort(key=lambda item: item[0])
    return averaged_points


def plot_for_g(rows, g_value: int, output_dir: Path):
    """为给定 G 绘制一张图，保持原代码的绘图样式。"""
    data_by_p = defaultdict(list)
    for row_g, row_p, row_b, row_coop_rate in rows:
        if row_g != g_value:
            continue
        standard_p = get_standard_p(row_p)
        # p=0 是有效值，因此必须判断是否为 None
        if standard_p is None:
            continue
        data_by_p[standard_p].append((row_b, row_coop_rate))

    if not data_by_p:
        print(f"[Warning] G={g_value} 没有找到符合条件的数据。")
        return None

    fig, ax = plt.subplots(figsize=panel_inches("FigC2"))

    line_styles = {
        0.00: {"color": PL_COLORS[0.00], "marker": "o"},
        0.25: {"color": PL_COLORS[0.25], "marker": "s"},
        0.50: {"color": PL_COLORS[0.50], "marker": "^"},
        0.75: {"color": PL_COLORS[0.75], "marker": "D"},
        1.00: {"color": PL_COLORS[1.00], "marker": "v"},
    }

    for p_value in TARGET_P_VALUES:
        if p_value not in data_by_p:
            print(f"[Warning] G={g_value} 缺少 p={p_value:.2f} 的数据。")
            continue

        points = average_duplicate_points(data_by_p[p_value])
        b_values = [point[0] for point in points]
        coop_rates = [point[1] for point in points]
        style = line_styles[p_value]

        ax.plot(
            b_values,
            coop_rates,
            color=style["color"],
            marker=style["marker"],
            linewidth=LINE_WIDTH_PT,
            markersize=4.5,
            markerfacecolor="white",
            markeredgewidth=LINE_WIDTH_PT,
            label=rf"$P_l = {p_value:.2f}$",
        )

    # 保留坐标范围，主刻度适配论文中的实际面板尺寸。
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel(r"$\delta$", fontsize=8)
    ax.set_ylabel(r"Cooperation rate, $\bar{F}_c$", fontsize=8)
    ax.set_title(rf"$g = {g_value}$", fontsize=8)
    ax.set_xticks([i / 4 for i in range(5)])
    ax.set_yticks([i / 5 for i in range(6)])
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, linestyle="--", linewidth=LINE_WIDTH_PT, alpha=0.35)
    ax.legend(
        title=r"$P_l$",
        fontsize=8,
        title_fontsize=8,
        loc="best",
        frameon=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"cooprate_G_{g_value}.png"
    save_figure(fig, output_path, bbox_inches="tight")
    print(f"[Saved] {output_path.resolve()}")
    return fig


def resolve_input_path(input_path: str):
    """优先使用指定路径，否则从当前目录递归搜索同名文件。"""
    path = Path(input_path)
    if path.is_file():
        return path

    candidates = [item for item in Path(".").rglob(path.name) if item.is_file()]
    if len(candidates) == 1:
        print(f"[Info] 使用搜索到的文件：{candidates[0]}")
        return candidates[0]
    if len(candidates) > 1:
        raise FileNotFoundError(
            f"找到多个名为 {path.name} 的文件，请通过 --input 指定完整路径。"
        )
    raise FileNotFoundError(f"找不到输入文件：{input_path}")


def main():
    parser = argparse.ArgumentParser(
        description="读取 Excel，绘制 G=3、4、5 下不同 p 的 Cooperation rate-b 曲线。"
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="输入 Excel 文件路径。")
    parser.add_argument("--sheet", default=None, help="工作表名称，默认读取第一张表。")
    parser.add_argument(
        "--output-dir", default=str(SCRIPT_DIR / "figures" / "line_plots_G3_G4_G5"), help="图片输出文件夹。"
    )
    parser.add_argument("--no-show", action="store_true", help="只保存图片，不弹出窗口。")
    args = parser.parse_args()

    try:
        input_file = resolve_input_path(args.input)
        rows = parse_data(input_file, sheet_name=args.sheet)
    except Exception as error:
        print(f"[Error] {error}")
        return 1

    if not rows:
        print(f"[Error] 文件中没有读取到有效数据：{input_file}")
        return 1

    target_g_values = sorted({row[0] for row in rows if row[0] in TARGET_G_VALUES})
    if not target_g_values:
        print(f"[Error] 数据中没有找到目标 G：{TARGET_G_VALUES}")
        return 1

    output_dir = Path(args.output_dir)
    saved_count = 0
    for g_value in target_g_values:
        figure = plot_for_g(rows, g_value, output_dir)
        if figure is not None:
            saved_count += 1
            if args.no_show:
                plt.close(figure)

    if not saved_count:
        print("[Error] 没有可绘制的目标 p 数据。")
        return 1
    if not args.no_show:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
