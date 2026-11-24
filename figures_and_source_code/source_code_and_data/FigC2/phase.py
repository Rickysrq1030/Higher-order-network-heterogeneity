# 导入 Path，用于处理输入、输出文件路径。
from pathlib import Path
import sys

# 使用标准库复制色图，兼容不提供 Colormap.copy() 的 Matplotlib 版本。
from copy import copy

# 导入 NumPy，用于处理二维数值矩阵和缺失值。
import numpy as np

# 导入 Pandas，用于读取表格数据和构造透视表。
import pandas as pd

# 导入 Matplotlib 主绘图模块。
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from figure_layout import panel_inches

configure_style()

# 指定 Excel 数据文件，可修改为其他文件路径。
INPUT_FILE = SCRIPT_DIR / "data" / "MPD_URH_global_results.xlsx"

# 默认读取第一张工作表，也可以改为工作表名称，例如 "Simulation Results"。
SHEET_NAME = 0

# 指定相图的输出文件夹。
OUTPUT_DIR = SCRIPT_DIR / "figures" / "phase_diagrams_by_G"

# 创建输出文件夹；如果已经存在则不会报错。
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 读取 Excel，按表头定位数据，不依赖列的先后顺序。
# 运行前安装依赖：python -m pip install numpy pandas matplotlib openpyxl
data = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME, engine="openpyxl")
data.columns = data.columns.astype(str).str.strip()

# 只有这四列是必需的；保留原数据中的可选 alpha 列。
required_columns = {"G", "p", "b", "final_avg_fc"}
missing_columns = required_columns - set(data.columns)
if missing_columns:
    raise ValueError(f"数据文件缺少列：{sorted(missing_columns)}")

# 将关键列转换成数值，无法转换、缺失或无限值会在下方删除。
for column in required_columns:
    data[column] = pd.to_numeric(data[column], errors="coerce")
data[list(required_columns)] = data[list(required_columns)].replace(
    [np.inf, -np.inf], np.nan
)
original_count = len(data)
data = data.dropna(subset=list(required_columns)).copy()

# 合作率使用新的 final_avg_fc 列。
# alpha 不参与分组，URH 的固定值不在图中展示。
if "alpha" in data.columns:
    data["alpha"] = pd.to_numeric(data["alpha"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )

# 仅保留 b 位于0到1之间的数据。
data = data[data["b"].between(0, 1)]

# 仅保留 p 位于0到1之间的数据。
data = data[data["p"].between(0, 1)]

# 仅保留合作率位于0到1之间的数据。
data = data[data["final_avg_fc"].between(0, 1)]


print(f"读取 {original_count} 行，保留 {len(data)} 行有效数据，过滤 {original_count - len(data)} 行。")


# 获得文件中所有不同的 G，并按照从小到大排序。
g_values = sorted(data["G"].unique())

# 如果数据中没有任何 G，说明没有可绘制的数据。
if not g_values:
    raise ValueError("数据文件中没有可以绘制的有效数据")


# 创建蓝—白—红色图的副本。
# RdBu_r 中低值是蓝色，高值是红色。
cmap = copy(plt.get_cmap("RdBu_r"))

# 将缺失数据对应的区域设置为灰色。
cmap.set_bad("#D2D2D2")


# 按照不同的 G 循环，每个 G 绘制一张相图。
for g_value in g_values:

    # 提取当前 G 对应的所有数据。
    group = data[data["G"] == g_value].copy()

    title_text = rf"$g={g_value:g}$"


    # 将长表转换成二维矩阵。
    # 行对应 p，列对应 b，单元格对应合作率。
    phase_table = group.pivot_table(
        index="p",
        columns="b",
        values="final_avg_fc",
        aggfunc="mean",
    )

    # 按照 p 从小到大排列矩阵的行。
    phase_table = phase_table.sort_index(axis=0)

    # 按照 b 从小到大排列矩阵的列。
    phase_table = phase_table.sort_index(axis=1)

    # 将 Pandas 表格转换成 NumPy 二维数组。
    phase_matrix = phase_table.to_numpy(dtype=float)

    # 将矩阵中的 NaN 标记为缺失值。
    # 缺失值将在相图中显示成灰色。
    phase_matrix = np.ma.masked_invalid(phase_matrix)


    # 创建画布和坐标轴。
    # 根据论文最终插入尺寸创建画布，边距由共享保存样式统一设置。
    fig, ax = plt.subplots(
        figsize=panel_inches("FigC2"),
    )

    # 绘制相图。
    image = ax.imshow(
        phase_matrix,              # 输入合作率二维矩阵。
        origin="lower",            # 让较小的 p 出现在图像底部。
        extent=(0, 1, 0, 1),       # 设置横轴和纵轴的实际范围。
        aspect="auto",             # 让图像自动填充坐标区域。
        interpolation="bicubic",   # 使用双三次插值进行平滑显示。
        cmap=cmap,                 # 使用蓝—白—红色图。
        vmin=0,                    # 固定颜色映射的最小值为0。
        vmax=1,                    # 固定颜色映射的最大值为1。
    )


    # 固定横坐标 b 的范围为0到1。
    ax.set_xlim(0, 1)

    # 固定纵坐标 p 的范围为0到1。
    ax.set_ylim(0, 1)

    # 设置横坐标名称。
    ax.set_xlabel(r"$\delta$", fontsize=8)

    # 设置纵坐标名称。
    ax.set_ylabel(r"Link-player proportion, $P_l$", fontsize=8)

    # 设置论文中固定超边规模的符号。
    ax.set_title(
        title_text,
        fontsize=8,
        pad=10,
    )

    # 设置横坐标刻度：0、0.2、0.4、0.6、0.8、1。
    ax.set_xticks(np.linspace(0, 1, 6))

    # 设置纵坐标刻度：0、0.2、0.4、0.6、0.8、1。
    ax.set_yticks(np.linspace(0, 1, 6))

    # 设置坐标刻度文字大小和刻度方向。
    ax.tick_params(
        axis="both",
        labelsize=8,
        direction="out",
    )

    # 关闭背景网格线。
    ax.grid(False)

    # 遍历相图四周的坐标轴边框。
    for spine in ax.spines.values():

        # 设置边框线宽。
        spine.set_linewidth(LINE_WIDTH_PT)


    # 在相图右侧添加颜色条。
    colorbar = fig.colorbar(
        image,
        ax=ax,
        pad=0.035,
        fraction=0.055,
    )

    # 设置颜色条标题。
    colorbar.set_label(
        r"Cooperation rate, $\bar{F}_c$",
        fontsize=8,
    )

    # 颜色条只明确标出0和1。
    colorbar.set_ticks([0, 1])

    # 设置颜色条刻度文字大小。
    colorbar.ax.tick_params(labelsize=8)

    # 设置颜色条外边框宽度。
    colorbar.outline.set_linewidth(LINE_WIDTH_PT)


    # 将 G 转换成适合文件名的文本。
    g_filename = f"{g_value:g}".replace(".", "p")

    # 构造当前 G 对应的图片文件名。
    output_file = OUTPUT_DIR / f"G_{g_filename}_b-p_phase.png"

    # 保存600 dpi PNG和矢量PDF。
    save_figure(
        fig,
        output_file,
        facecolor="white",
    )

    # 关闭当前画布，避免绘制大量 G 时占用过多内存。
    plt.close(fig)

    # 在终端中报告当前图片的位置。
    print(f"已生成：{output_file}")


# 所有 G 绘制结束后输出提示。
print(f"全部完成，共生成 {len(g_values)} 张相图。")
