# -*- coding: utf-8 -*-
"""Paper Figure D1: measured SRH PGG cooperation over the (r, eta) grid.

Default input is the complete processed table in this group's data directory,
aggregated from its five independent full scans by prepare_data.py.
The source column ``alpha`` denotes the paper's attachment probability eta.
Use --input to select a processed table explicitly, or --scan-dir to read
independent raw scans directly. Inputs are never merged with another dataset,
averaged across coordinates, or filled by interpolation.
"""

import argparse
import hashlib
import json
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from paper_plot_style import configure_style, save_figure, figure_data_digest
from figure_layout import panel_inches

configure_style()

# =========================
# 1. 参数设置
# =========================

DATA_DIR = SCRIPT_DIR / "data"
INPUT_FILE = DATA_DIR / "processed_coop_data.txt"
OUTPUT_DIR = SCRIPT_DIR / "figures" / "phase_diagram_alpha_r_results"
SCAN_DIR = DATA_DIR
AUDIT_FILE = PROJECT_ROOT / "交付" / "FigD1热力图数据检查.json"
AGGREGATION_AUDIT_FILE = PROJECT_ROOT / "交付" / "FigD1数据聚合检查.json"
SCAN_FILES = (
    ("p0.txt", 0.0),
    ("p0.25.txt", 0.25),
    ("p0.5.txt", 0.5),
    ("p0.75.txt", 0.75),
    ("p1.txt", 1.0),
)
REQUIRED_COLUMNS = ("G", "alpha", "p", "r", "Coop_Rate")
EXPECTED_ETA = np.arange(21, dtype=float) / 20
EXPECTED_R = np.arange(41, dtype=float) / 20
CMAP = plt.get_cmap("RdBu_r")
# Match Figure C2's display smoothing without changing the measured matrix.
DISPLAY_INTERPOLATION = "bicubic"


# =========================
# 2. 绘图风格
# =========================

# Typography and physical stroke widths are configured by paper_plot_style.


# =========================
# 3. 数据读取
# =========================

def read_table_skip_separator_lines(file_path):
    """
    读取 txt 文件，并跳过由 ----- 组成的分隔线。
    """
    cleaned_lines = []

    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()

            if not stripped:
                continue

            if re.fullmatch(r"-+", stripped):
                continue

            cleaned_lines.append(line)

    if not cleaned_lines:
        raise ValueError(f"文件 {file_path} 中没有有效数据。")

    header = cleaned_lines[0].split()
    if len(header) != len(set(header)):
        raise ValueError(f"文件 {file_path} 的表头含重复字段：{header}")
    if set(header) != set(REQUIRED_COLUMNS):
        raise ValueError(
            f"文件 {file_path} 必须恰好包含字段 {REQUIRED_COLUMNS}，实际为 {header}"
        )
    for row_number, line in enumerate(cleaned_lines[1:], start=2):
        if len(line.split()) != len(header):
            raise ValueError(f"文件 {file_path} 的有效数据第 {row_number} 行字段数不正确。")

    text = "".join(cleaned_lines)

    df = pd.read_csv(
        StringIO(text),
        sep=r"\s+",
        engine="python",
        converters={column: float for column in REQUIRED_COLUMNS},
    )

    return df


def validate_data(df, source="input"):
    """Reject invalid observations; no row, coordinate, or rate is discarded."""
    if list(df.columns).count("G") != 1 or set(df.columns) != set(REQUIRED_COLUMNS):
        raise ValueError(f"{source} 的字段必须恰好为 {REQUIRED_COLUMNS}。")
    if len(df.columns) != len(REQUIRED_COLUMNS):
        raise ValueError(f"{source} 包含重复字段。")
    if df.empty:
        raise ValueError(f"{source} 没有有效观测。")
    df = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    for column in REQUIRED_COLUMNS:
        try:
            df[column] = pd.to_numeric(df[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise ValueError(f"{source} 的 {column} 列含非数值。") from error
    if not np.isfinite(df.to_numpy(dtype=float)).all():
        raise ValueError(f"{source} 包含缺失值、NaN 或无穷数。")
    if not df["G"].eq(4).all():
        raise ValueError(f"{source} 的全部观测必须满足 g=4。")
    for column, lower, upper in (("alpha", 0, 1), ("p", 0, 1),
                                 ("r", 0, 2), ("Coop_Rate", 0, 1)):
        if not df[column].between(lower, upper).all():
            raise ValueError(f"{source} 的 {column} 超出 [{lower}, {upper}]。")
    duplicate = df.duplicated(["G", "p", "alpha", "r"], keep=False)
    if duplicate.any():
        raise ValueError(f"{source} 包含 {int(duplicate.sum())} 条重复坐标观测。")
    df["G"] = df["G"].astype(int)
    return df.sort_values(["G", "p", "alpha", "r"]).reset_index(drop=True)


def read_processed_data(file_path):
    return validate_data(read_table_skip_separator_lines(file_path), str(file_path))


def file_record(path, row_count):
    path = Path(path).expanduser().resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": int(row_count)}


def validate_complete_scan(df, expected_p, source="scan"):
    df = validate_data(df, source)
    if not np.isclose(df["p"].to_numpy(), expected_p, rtol=0, atol=1e-12).all():
        raise ValueError(f"{source} 的 P_l 必须全部为 {expected_p:g}，与文件名一致。")
    eta = np.sort(df["alpha"].unique())
    r = np.sort(df["r"].unique())
    if len(eta) != 21 or not np.allclose(eta, EXPECTED_ETA, rtol=0, atol=1e-12):
        raise ValueError(f"{source} 必须完整包含 eta=0..1、步长0.05的21个值。")
    if len(r) != 41 or not np.allclose(r, EXPECTED_R, rtol=0, atol=1e-12):
        raise ValueError(f"{source} 必须完整包含 r=0..2、步长0.05的41个值。")
    if len(df) != 21 * 41:
        raise ValueError(f"{source} 的21×41笛卡尔网格必须有861条唯一观测，实际{len(df)}。")
    build_phase_matrix(df)
    return df


def load_phase_data(input_path=None, scan_dir=None):
    """Select one independent source, with no union or overwrite of datasets."""
    if input_path is not None:
        path = Path(input_path).expanduser().resolve()
        df = read_processed_data(path)
        return df, {"mode": "explicit_processed_input", "inputs": [file_record(path, len(df))]}
    if scan_dir is None:
        df = read_processed_data(INPUT_FILE)
        p_values = np.sort(df["p"].unique())
        expected_p = np.array([p for _, p in SCAN_FILES])
        if len(p_values) != 5 or not np.allclose(p_values, expected_p, rtol=0, atol=1e-12):
            raise ValueError("默认聚合表必须完整包含 P_l=0,0.25,0.5,0.75,1 的五组扫描。")
        for _, expected in SCAN_FILES:
            group = df[np.isclose(df["p"], expected, rtol=0, atol=1e-12)]
            validate_complete_scan(group, expected, str(INPUT_FILE))
        target_record = file_record(INPUT_FILE, len(df))
        source = {"mode": "aggregated_complete_pgg", "inputs": [target_record]}
        if AGGREGATION_AUDIT_FILE.is_file():
            aggregation = json.loads(AGGREGATION_AUDIT_FILE.read_text(encoding="utf-8"))
            if aggregation["target"]["sha256"] != target_record["sha256"]:
                raise ValueError("聚合检查报告的 target SHA-256 与默认 processed 表不符。")
            if not aggregation["all_five_columns_match"] or not aggregation["numeric_tokens_preserved"]:
                raise ValueError("聚合检查报告未确认所有原始值与字面数字完整保留。")
            source["raw_inputs"] = aggregation["raw_inputs"]
            source["aggregation_audit"] = str(AGGREGATION_AUDIT_FILE.resolve())
        else:
            source["raw_inputs"] = [file_record(SCAN_DIR / name, 861) for name, _ in SCAN_FILES]
        return df, source
    directory = Path(scan_dir).expanduser().resolve()
    paths = [(directory / name, p) for name, p in SCAN_FILES]
    present = [path.is_file() for path, _ in paths]
    if not all(present):
        missing = [str(path) for (path, _), exists in zip(paths, present) if not exists]
        raise FileNotFoundError(f"PGG扫描目录不完整，缺少：{missing}。请补齐扫描文件或显式--input指定有效表。")
    frames, inputs = [], []
    for path, p in paths:
        frame = validate_complete_scan(read_processed_data(path), p, str(path))
        frames.append(frame)
        inputs.append(file_record(path, len(frame)))
    return validate_data(pd.concat(frames, ignore_index=True), str(directory)), {
        "mode": "complete_pgg_scans", "inputs": inputs,
    }


# =========================
# 4. 构造相图矩阵
# =========================

def build_phase_matrix(group_df):
    """
    将某一组固定 (G, p) 的数据转换成矩阵 Z：
    - 横坐标：r
    - 纵坐标：alpha
    - 值：Coop_Rate
    """
    group_df = validate_data(group_df, "phase group")
    if len(group_df[["G", "p"]].drop_duplicates()) != 1:
        raise ValueError("一张相图必须只包含一个固定的(g, P_l)。")
    table = group_df.pivot(index="alpha", columns="r", values="Coop_Rate")
    table = table.sort_index(axis=0).sort_index(axis=1)
    if table.isna().to_numpy().any():
        missing = int(table.isna().to_numpy().sum())
        raise ValueError(f"实际eta/r笛卡尔网格缺少{missing}个观测，不允许填充或插补。")
    r_values = table.columns.to_numpy(dtype=float)
    alpha_values = table.index.to_numpy(dtype=float)
    return r_values, alpha_values, table.to_numpy(dtype=float)


def half_cell_edges(values):
    """Measured uniform-grid edges; imshow cannot represent an irregular grid."""
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        raise ValueError("相图每一坐标方向至少需要两个实际测量值。")
    steps = np.diff(values)
    if not np.allclose(steps, steps[0], rtol=0, atol=1e-12) or steps[0] <= 0:
        raise ValueError("imshow的实际坐标必须为均匀递增网格，不允许隐式插值。")
    return float(values[0] - steps[0] / 2), float(values[-1] + steps[-1] / 2)


def create_data_audit(df, source):
    """Trace every measured value through the pivot without drawing a figure."""
    figures = []
    for (g, p), group in df.groupby(["G", "p"], sort=True):
        r, eta, matrix = build_phase_matrix(group)
        x_edges, y_edges = half_cell_edges(r), half_cell_edges(eta)
        r_index = {float(value): i for i, value in enumerate(r)}
        eta_index = {float(value): i for i, value in enumerate(eta)}
        pointwise = []
        for row in group.itertuples(index=False):
            actual = float(matrix[eta_index[float(row.alpha)], r_index[float(row.r)]])
            raw = float(row.Coop_Rate)
            pointwise.append({"eta": float(row.alpha), "r": float(row.r),
                              "raw_cooperation_rate": raw, "matrix_value": actual,
                              "match": raw == actual})
        if not all(point["match"] for point in pointwise):
            raise AssertionError("原始观测与相图矩阵不逐项一致。")
        science = {"g": int(g), "P_l": float(p), "r": r.tolist(), "eta": eta.tolist(),
                   "cooperation_rate": matrix.tolist(), "extent": [*x_edges, *y_edges],
                   "cmap": "RdBu_r", "vmin": 0, "vmax": 1,
                   "interpolation": DISPLAY_INTERPOLATION}
        digest = hashlib.sha256(json.dumps(science, sort_keys=True, ensure_ascii=True,
                                          separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        figures.append({"stem": f"phase_G={int(g)}_p={float(p):.2f}",
                        "g": int(g), "P_l": float(p), "grid_shape": list(matrix.shape),
                        "eta_values": eta.tolist(), "r_values": r.tolist(),
                        "extent": [*x_edges, *y_edges], "observations": len(group),
                        "missing_points": int(np.isnan(matrix).sum()), "duplicate_points": 0,
                        "pointwise_match_count": len(pointwise), "all_points_match": True,
                        "pointwise_matches": pointwise, "matrix_scientific_digest": digest})
    audit = {"paper_figure": "Figure D1", "code_directory": "附录图/FigD1",
             **source, "total_observations": int(len(df)),
             "missing_points": 0, "duplicate_points": 0,
             "source_values_modified": False, "interpolation": DISPLAY_INTERPOLATION,
             "display_resample": True, "missing_observations_interpolated": 0,
             "cmap": "RdBu_r", "figures": figures,
             "digest_definition": "SHA-256 of canonical JSON: g/P_l, measured axes, pivot matrix, extent and colour mapping."}
    return audit


def write_data_audit(df, source, target=AUDIT_FILE, audit=None):
    if audit is None:
        audit = create_data_audit(df, source)
    target = Path(target).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return audit


# =========================
# 5. 绘图函数
# =========================

def safe_filename(text):
    text = str(text)
    text = re.sub(r"[^0-9a-zA-Z_.=-]+", "_", text)
    return text[:180]


def plot_phase_diagram(group_df, output_dir, audit_item=None):
    """
    对固定的 (G, p) 画一张相图：
    x = r
    y = alpha
    color = Coop_Rate
    """
    G = int(group_df["G"].iloc[0])
    p_val = float(group_df["p"].iloc[0])

    r_values, alpha_values, Z = build_phase_matrix(group_df)

    fig, ax = plt.subplots(figsize=panel_inches("FigD1"))

    extent = [*half_cell_edges(r_values), *half_cell_edges(alpha_values)]

    im = ax.imshow(
        Z,
        origin="lower",
        aspect="auto",
        extent=extent,
        cmap=CMAP,
        vmin=0.0,
        vmax=1.0,
        interpolation=DISPLAY_INTERPOLATION,
        resample=True,
    )

    ax.set_xlabel(r"$r$")
    ax.set_ylabel("Random-attachment\n" + r"probability, $\eta$")
    ax.set_title(rf"$g={G},\ P_l={p_val:.2f}$")

    # Preserve the data grid while keeping labels legible at final paper size.
    ax.set_xticks(np.arange(0.0, 2.01, 0.5))
    ax.set_xticks(np.arange(0.0, 2.01, 0.05), minor=True)
    if alpha_values[-1] == 1 and alpha_values[0] == 0:
        ax.set_yticks(np.linspace(0, 1, 5))
    else:
        # Preserve the observed eta coordinates in an explicitly selected table.
        ax.set_yticks(alpha_values)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_ticks([0, .25, .5, .75, 1])
    cbar.set_label(r"Cooperation rate, $\bar{F}_c$")

    base_name = safe_filename(f"phase_G={G}_p={p_val:.2f}")

    png_path = os.path.join(output_dir, f"{base_name}.png")
    pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
    save_figure(fig, png_path, bbox_inches="tight")
    if audit_item is not None:
        # Same artist digest used by paper_plot_style's style audit/cache.
        audit_item["artist_data_sha256"] = figure_data_digest(fig)

    plt.close(fig)

    return png_path, pdf_path


# =========================
# 6. 主程序
# =========================

def main():
    parser = argparse.ArgumentParser(description="SRH PGG phase diagrams by g and P_l.")
    parser.add_argument("--input", type=Path, default=None,
                        help="显式选择独立processed表；不与其他数据源合并。")
    parser.add_argument("--scan-dir", type=Path, default=None,
                        help="显式读取目录中的五个p*.txt；默认读取已聚合processed表。")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--audit-file", type=Path, default=AUDIT_FILE)
    args = parser.parse_args()
    if args.input is not None and args.scan_dir is not None:
        parser.error("--input 和 --scan-dir 只能选择一种独立数据源。")
    output_dir = args.output_dir.expanduser().resolve()
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 70)
    print("Step 1: Reading data...")

    df, source = load_phase_data(args.input, args.scan_dir)
    audit = write_data_audit(df, source, args.audit_file)
    audit_by_group = {(item["g"], item["P_l"]): item for item in audit["figures"]}

    print(f"Data loaded: {len(df)} rows")
    print("Columns:", list(df.columns))
    print("G values:", sorted(df["G"].unique()))
    print("p values:", sorted(df["p"].unique()))
    print("alpha range:", (df["alpha"].min(), df["alpha"].max()))
    print("r range:", (df["r"].min(), df["r"].max()))

    print("=" * 70)
    print("Step 2: Plotting phase diagrams...")

    saved_files = []

    # 每个 (G, p) 画一张图
    for (G, p_val), group in df.groupby(["G", "p"], dropna=False):
        png_path, pdf_path = plot_phase_diagram(
            group, output_dir, audit_item=audit_by_group[(int(G), float(p_val))]
        )
        saved_files.append(png_path)
        if pdf_path is not None:
            saved_files.append(pdf_path)

        print(f"[OK] Saved figure for G={G}, p={p_val:.2f}")

    write_data_audit(df, source, args.audit_file, audit=audit)

    print("=" * 70)
    print("Finished.")
    print("Output directory:")
    print("  ", output_dir)
    print("Saved files:")
    for path in saved_files:
        print("  ", path)


if __name__ == "__main__":
    main()
