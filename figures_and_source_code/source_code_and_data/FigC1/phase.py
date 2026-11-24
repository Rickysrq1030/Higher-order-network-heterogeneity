# -*- coding: utf-8 -*-
"""
Phase-diagram plotting for cooperation-rate data.

输入数据格式示例：
G          N          alpha      p          r          Coop_Rate
---------------------------------------------------------------------------
4          2000       1.00       0.950      0.000      0.2128
4          2000       1.00       0.950      0.050      0.1729
...

功能：
1. 读取 txt 数据；
2. 按 (G, N, alpha) 分组；
3. 绘制横轴 r、纵轴 p 的合作率相图；
4. 颜色映射：0=蓝色，1=红色，中间值渐变；
5. 保存图片到输出文件夹。

作者建议：
- 如果一个文件中只有一组固定的 G, N, alpha，也可以直接画一张图；
- 如果有多组，则自动每组画一张图。
"""

import os
import re
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure
from figure_layout import panel_inches

configure_style()

# =========================
# 1. 参数设置
# =========================

INPUT_FILE = SCRIPT_DIR / "data" / "processed_coop_data.txt"
OUTPUT_DIR = SCRIPT_DIR / "figures" / "phase_diagram_results"

# 相图坐标范围与步长
R_MIN, R_MAX, R_STEP = 0.0, 2.0, 0.05
P_MIN, P_MAX, P_STEP = 0.0, 1.0, 0.05

# 与论文 Figure C2 保持同一色图：低值深蓝，中间白色，高值暗红。
CMAP = plt.get_cmap("RdBu_r").copy()
CMAP.set_bad("#D2D2D2")


# =========================
# 2. 绘图风格
# =========================

# 字体、字号与导出格式由共享论文绘图样式统一设置。


# =========================
# 3. 数据读取
# =========================

def read_table_skip_separator_lines(file_path):
    """
    读取 txt 数据文件，并跳过仅由 '-' 组成的分隔线。
    """
    cleaned_lines = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()

            if not stripped:
                continue

            if re.fullmatch(r"-+", stripped):
                continue

            cleaned_lines.append(line)

    if not cleaned_lines:
        raise ValueError(f"文件 {file_path} 中没有有效数据。")

    text = "".join(cleaned_lines)

    df = pd.read_csv(
        StringIO(text),
        sep=r"\s+",
        engine="python"
    )

    return df


def read_processed_data(file_path):
    """
    读取并清洗数据。
    """
    df = read_table_skip_separator_lines(file_path)

    df.columns = [str(col).strip() for col in df.columns]

    required_cols = ["G", "N", "alpha", "p", "r", "Coop_Rate"]
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(
            f"输入文件缺少必要列: {missing_cols}\n"
            f"当前列名为: {list(df.columns)}"
        )

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols).copy()

    if df.empty:
        raise ValueError("清洗后数据为空，请检查输入文件内容。")

    df["G"] = df["G"].astype(int)
    df["N"] = df["N"].astype(int)
    df["alpha"] = df["alpha"].round(6)
    df["p"] = df["p"].round(6)
    df["r"] = df["r"].round(6)
    df["Coop_Rate"] = df["Coop_Rate"].round(6)

    df = df.sort_values(["G", "N", "alpha", "p", "r"]).reset_index(drop=True)

    return df


# =========================
# 4. 构造相图矩阵
# =========================

def build_phase_matrix(group_df):
    """
    将某一组 (G, N, alpha) 数据转换为相图矩阵。
    
    返回：
        r_values: 横坐标数组
        p_values: 纵坐标数组
        Z: shape=(len(p_values), len(r_values)) 的合作率矩阵
    """
    r_values = np.round(np.arange(R_MIN, R_MAX + 1e-12, R_STEP), 6)
    p_values = np.round(np.arange(P_MIN, P_MAX + 1e-12, P_STEP), 6)

    Z = np.full((len(p_values), len(r_values)), np.nan)

    # 如果有重复点，先取平均
    tmp = (
        group_df.groupby(["p", "r"], as_index=False)["Coop_Rate"]
        .mean()
        .reset_index(drop=True)
    )

    for _, row in tmp.iterrows():
        p_val = round(float(row["p"]), 6)
        r_val = round(float(row["r"]), 6)
        coop = float(row["Coop_Rate"])

        p_idx = np.where(np.isclose(p_values, p_val))[0]
        r_idx = np.where(np.isclose(r_values, r_val))[0]

        if len(p_idx) == 0 or len(r_idx) == 0:
            continue

        Z[p_idx[0], r_idx[0]] = coop

    return r_values, p_values, Z


# =========================
# 5. 绘图
# =========================

def safe_filename(text):
    text = str(text)
    text = re.sub(r"[^0-9a-zA-Z_.=-]+", "_", text)
    return text[:180]


def plot_phase_diagram(group_df, output_dir):
    """
    对某一组固定的 (G, N, alpha) 绘制相图。
    """
    G = int(group_df["G"].iloc[0])
    N = int(group_df["N"].iloc[0])
    alpha = float(group_df["alpha"].iloc[0])

    r_values, p_values, Z = build_phase_matrix(group_df)

    fig, ax = plt.subplots(figsize=panel_inches("FigC1"))

    # imshow 的 extent 设置为网格边界
    extent = [
        R_MIN - R_STEP / 2,
        R_MAX + R_STEP / 2,
        P_MIN - P_STEP / 2,
        P_MAX + P_STEP / 2
    ]

    im = ax.imshow(
        Z,
        origin="lower",
        aspect="auto",
        extent=extent,
        cmap=CMAP,
        vmin=0.0,
        vmax=1.0,
        interpolation="bicubic"
    )

    ax.set_xlabel(r"$r$")
    ax.set_ylabel(r"Link-player proportion, $P_l$")
    ax.set_title(rf"$g={G}$")

    # 不要所有刻度都显示，否则太密
    ax.set_xticks(np.arange(0.0, 2.01, 0.5))
    ax.set_yticks(np.arange(0.0, 1.01, 0.2))

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(r"Cooperation rate, $\bar{F}_c$")


    base_name = f"phase_G={G}_N={N}_alpha={alpha:.2f}"
    base_name = safe_filename(base_name)

    png_path = os.path.join(output_dir, f"{base_name}.png")
    pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
    save_figure(fig, png_path, bbox_inches="tight")

    plt.close(fig)

    return png_path, pdf_path


# =========================
# 6. 主程序
# =========================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 70)
    print("Step 1: Reading data...")

    df = read_processed_data(INPUT_FILE)

    print(f"Data loaded: {len(df)} rows")
    print("Columns:", list(df.columns))
    print("G values:", sorted(df["G"].unique()))
    print("N values:", sorted(df["N"].unique()))
    print("alpha values:", sorted(df["alpha"].unique()))
    print("p range:", (df["p"].min(), df["p"].max()))
    print("r range:", (df["r"].min(), df["r"].max()))

    print("=" * 70)
    print("Step 2: Plotting phase diagrams...")

    group_cols = ["G", "N", "alpha"]
    saved_files = []

    for keys, group in df.groupby(group_cols, dropna=False):
        png_path, pdf_path = plot_phase_diagram(group, OUTPUT_DIR)
        saved_files.append(png_path)
        if pdf_path is not None:
            saved_files.append(pdf_path)

        print(f"[OK] Saved figure for G={keys[0]}, N={keys[1]}, alpha={keys[2]:.2f}")

    print("=" * 70)
    print("Finished.")
    print("Output directory:")
    print("  ", os.path.abspath(OUTPUT_DIR))
    print("Saved files:")
    for path in saved_files:
        print("  ", path)


if __name__ == "__main__":
    main()
