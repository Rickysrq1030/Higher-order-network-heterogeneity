# 导入 Path，用于处理输入、输出文件路径。
from pathlib import Path
import sys

# 导入 NumPy，用于处理二维数值矩阵和缺失值。
import numpy as np

# 导入 Pandas，用于读取表格数据和构造透视表。
import pandas as pd

# 导入 Matplotlib 主绘图模块。
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from figure_layout import panel_inches, full_inches

configure_style()


# 获取脚本所在目录，确保从任意工作目录运行时都能找到数据文件。
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"

# 指定原始数据文件；文件应与本代码位于同一目录。
INPUT_FILE = DATA_DIR / "processed_coop_data.txt"

# 指定相图的输出文件夹。
OUTPUT_DIR = SCRIPT_DIR / "figures" / "phase_diagrams_by_p"

# 创建输出文件夹；如果已经存在则不会报错。
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 使用空白字符作为分隔符读取数据。
# skiprows=[1] 表示跳过第二行由短横线组成的分隔线。
data = pd.read_csv(
    INPUT_FILE,
    sep=r"\s+",
    skiprows=[1],
    engine="python",
)


# 定义数据文件中必须存在的列名。
required_columns = {"G", "alpha", "b", "p", "Coop_Rate"}

# 检查实际数据是否包含所有必要列。
missing_columns = required_columns - set(data.columns)

# 如果缺少必要列，就停止程序并报告缺失的列名。
if missing_columns:
    raise ValueError(f"数据文件缺少列：{sorted(missing_columns)}")


# 删除关键参数中存在空值的数据行。
data = data.dropna(subset=["G", "alpha", "b", "p", "Coop_Rate"])

# 仅保留 b 位于0到1之间的数据。
data = data[data["b"].between(0, 1)]

# 仅保留 p 位于0到1之间的数据。
data = data[data["p"].between(0, 1)]

# 仅保留合作率位于0到1之间的数据。
data = data[data["Coop_Rate"].between(0, 1)]


# 获得文件中所有不同的 p，并按照从小到大排序。
p_values = sorted(data["p"].unique())

# 如果数据中没有任何 p，说明没有可绘制的数据。
if not p_values:
    raise ValueError("数据文件中没有可以绘制的有效数据")


# 创建蓝—白—红色图的副本。
# RdBu_r 中低值是蓝色，高值是红色。
cmap = plt.get_cmap("RdBu_r").copy()

# 将缺失数据对应的区域设置为灰色。
cmap.set_bad("#D2D2D2")


# 按照不同的 p 循环，每个 p 绘制一张相图。
for p_value in p_values:

    # 提取当前 p 对应的所有数据。
    group = data[np.isclose(data["p"], p_value)].copy()

    # 获取当前 p 下所有不同的 G。
    g_values = sorted(group["G"].unique())

    # 当前实验通常只有一个固定的 G。
    if len(g_values) == 1:

        # 读取唯一的 G 值。
        g_value = g_values[0]

        # 构造用于标题的 G 文本。
        g_text = rf"g={g_value:g}"

    # 如果同一个 p 下存在多个 G，则在标题中列出。
    else:

        # 将多个 G 转换为逗号分隔的字符串。
        values_text = ", ".join(f"{value:g}" for value in g_values)

        # 构造多 G 标题。
        g_text = rf"g \in \{{{values_text}\}}"


    # 将长表转换成二维矩阵。
    # 行对应 alpha，列对应 b，单元格对应合作率。
    phase_table = group.pivot_table(
        index="alpha",
        columns="b",
        values="Coop_Rate",
        aggfunc="mean",
    )

    # 按照 alpha 从小到大排列矩阵的行。
    phase_table = phase_table.sort_index(axis=0)

    # 按照 b 从小到大排列矩阵的列。
    phase_table = phase_table.sort_index(axis=1)

    # 将 Pandas 表格转换成 NumPy 二维数组。
    phase_matrix = phase_table.to_numpy(dtype=float)

    # 将矩阵中的 NaN 标记为缺失值。
    # 缺失值将在相图中显示成灰色。
    phase_matrix = np.ma.masked_invalid(phase_matrix)


    # 创建画布和坐标轴。
    # 使用论文面板的最终物理大小；保存时统一处理边距。
    fig, ax = plt.subplots(
        figsize=panel_inches("FigD3"),
    )

    # 绘制相图。
    image = ax.imshow(
        phase_matrix,              # 输入合作率二维矩阵。
        origin="lower",            # 让较小的 alpha 出现在图像底部。
        extent=(0, 1, 0, 1),       # 设置横轴和纵轴的实际范围。
        aspect="auto",             # 让图像自动填充坐标区域。
        interpolation="bicubic",   # 使用双三次插值进行平滑显示。
        cmap=cmap,                 # 使用蓝—白—红色图。
        vmin=0,                    # 固定颜色映射的最小值为0。
        vmax=1,                    # 固定颜色映射的最大值为1。
    )


    # 固定横坐标 b 的范围为0到1。
    ax.set_xlim(0, 1)

    # 固定纵坐标 alpha 的范围为0到1。
    ax.set_ylim(0, 1)

    # 设置横坐标名称。
    ax.set_xlabel(r"$\delta$")

    # 设置纵坐标名称。
    ax.set_ylabel("Random-attachment\n" + r"probability, $\eta$")

    # 设置标题，同时显示当前 G 和 p。
    ax.set_title(
        rf"${g_text},\ P_l={p_value:g}$",
        pad=3,
    )

    # 五个主刻度，在最终面板大小下保持清楚。
    ax.set_xticks(np.linspace(0, 1, 5))

    # 设置纵坐标的五个主要刻度：0、0.25、0.5、0.75、1。
    ax.set_yticks(np.linspace(0, 1, 5))

    # 设置坐标刻度文字大小和刻度方向。
    ax.tick_params(
        axis="both",
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
    )

    # 颜色条只明确标出0和1。
    colorbar.set_ticks([0, 1])

    # 设置颜色条刻度文字大小。
    colorbar.ax.tick_params()

    # 设置颜色条外边框宽度。
    colorbar.outline.set_linewidth(LINE_WIDTH_PT)


    # 将 p 转换成适合文件名的文本。
    p_filename = f"{p_value:.2f}".replace(".", "p")

    # 构造当前 p 对应的图片文件名。
    output_file = OUTPUT_DIR / f"p_{p_filename}_b-alpha_phase.png"

    # 保存 600 dpi PNG 和矢量 PDF。
    save_figure(fig,
        output_file,
        facecolor="white",
    )

    # 关闭当前画布，避免绘制大量 G 时占用过多内存。
    plt.close(fig)

    # 在终端中报告当前图片的位置。
    print(f"已生成：{output_file}")


# 所有 p 绘制结束后输出提示。
print(f"全部完成，共生成 {len(p_values)} 张相图。")
