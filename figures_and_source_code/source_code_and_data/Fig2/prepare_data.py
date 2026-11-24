"""Import the complete measured SRH PGG m scan for paper Figure 2.

Read the local raw Excel file without changing it. Every cooperation rate is
copied directly to the processed table; no averaging or interpolation is used.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from openpyxl import load_workbook


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_INPUT = DATA_DIR / "PGG_SRH_global_results.xlsx"
DEFAULT_TARGET = DATA_DIR / "processed_coop_data.txt"
DEFAULT_AUDIT = PROJECT_ROOT / "交付" / "Fig2数据导入检查.json"
SOURCE_COLUMNS = ("G", "N", "m", "mh", "alpha", "p", "R", "r",
                  "final_avg_fc", "txt_file")
TABLE_COLUMNS = ("m", "alpha", "p", "r", "Coop_Rate")
P_VALUES = (0.0, 0.25, 0.5, 0.75, 1.0)
R_VALUES = tuple(index / 20 for index in range(41))
EXPECTED_KEYS = {(m, p_index, r_index) for m in (1, 2, 3)
                 for p_index in range(5) for r_index in range(41)}


def numeric_cell(value, name, row_number):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Excel 第 {row_number} 行的 {name} 必须是数值。")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Excel 第 {row_number} 行的 {name} 必须是有限数值。")
    return result


def grid_index(value, allowed, name, row_number):
    matches = [index for index, expected in enumerate(allowed)
               if math.isclose(value, expected, rel_tol=0, abs_tol=1e-12)]
    if len(matches) != 1:
        raise ValueError(f"Excel 第 {row_number} 行的 {name}={value!r} 不在规定网格。")
    return matches[0]


def validate_observations(observations):
    """Reject invalid parameters, duplicates and every incomplete 615-point grid."""
    by_key = {}
    for row in observations:
        number = row["source_row"]
        for column, expected in (("G", 4), ("N", 2000), ("mh", 3), ("alpha", 0)):
            if row[column] != expected:
                raise ValueError(f"Excel 第 {number} 行必须满足 {column}={expected}。")
        if row["m"] not in (1, 2, 3):
            raise ValueError(f"Excel 第 {number} 行的 m 必须是 1、2 或 3。")
        p_index = grid_index(row["p"], P_VALUES, "p", number)
        r_index = grid_index(row["r"], R_VALUES, "r", number)
        if not math.isclose(row["R"] / row["G"], row["r"], rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"Excel 第 {number} 行不满足 R/G=r。")
        if not 0 <= row["final_avg_fc"] <= 1:
            raise ValueError(f"Excel 第 {number} 行的 final_avg_fc 必须在 0～1 之间。")
        key = (int(row["m"]), p_index, r_index)
        if key in by_key:
            raise ValueError(f"Excel 第 {number} 行与第 {by_key[key]['source_row']} 行重复：{key}。")
        by_key[key] = row
    missing, extra = EXPECTED_KEYS - set(by_key), set(by_key) - EXPECTED_KEYS
    if missing or extra:
        raise ValueError(f"Figure 2 必须完整包含 615 个唯一观测；缺失 {len(missing)}，多余 {len(extra)}。")
    return [by_key[key] for key in sorted(EXPECTED_KEYS)]


def read_excel(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError("Figure 2 原始 Excel 必须恰好包含一张工作表。")
        sheet = workbook.worksheets[0]
        records = sheet.iter_rows(values_only=True)
        header = next(records, None)
        if header is None:
            raise ValueError("Figure 2 原始 Excel 为空。")
        names = [str(value).strip() if value is not None else "" for value in header]
        if len(names) != len(SOURCE_COLUMNS) or set(names) != set(SOURCE_COLUMNS):
            raise ValueError(f"Figure 2 Excel 表头必须恰好包含 {SOURCE_COLUMNS}。")
        indices = {name: names.index(name) for name in SOURCE_COLUMNS}
        observations = []
        for number, record in enumerate(records, start=2):
            if all(value is None for value in record):
                continue
            row = {name: numeric_cell(record[indices[name]], name, number)
                   for name in SOURCE_COLUMNS if name != "txt_file"}
            source_file = record[indices["txt_file"]]
            if not isinstance(source_file, str) or not source_file.strip():
                raise ValueError(f"Excel 第 {number} 行的 txt_file 必须是非空文本。")
            observations.append({**row, "txt_file": source_file, "source_row": number})
        return sheet.title, validate_observations(observations)
    finally:
        workbook.close()


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".import.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def file_record(path, rows):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": rows}


def prepare(input_path=DEFAULT_INPUT, target=DEFAULT_TARGET, audit_path=DEFAULT_AUDIT):
    input_path, target, audit_path = [Path(path).expanduser().resolve()
                                     for path in (input_path, target, audit_path)]
    if len({input_path, target, audit_path}) != 3:
        raise ValueError("原始 Excel、处理表和审计报告必须使用三个不同路径。")
    source_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    sheet, rows = read_excel(input_path)
    expected = [(row["m"], row["alpha"], row["p"], row["r"], row["final_avg_fc"])
                for row in rows]
    # repr provides exact float round trips; do not round rates or coordinates.
    serialized = ["\t".join(repr(value) for value in row) for row in expected]
    actual = [tuple(map(float, line.split())) for line in serialized]
    matches = [[source == output for source, output in zip(before, after)]
               for before, after in zip(expected, actual)]
    if not all(all(match) for match in matches):
        raise AssertionError("拟写入处理表的五列数值未逐项保持 Excel 原值。")
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("读取期间原始 Excel 发生变化，取消导入。")
    text = "\t".join(TABLE_COLUMNS) + "\n" + "-" * 60 + "\n"
    text += "\n".join(serialized) + "\n"
    atomic_write(target, text.encode("utf-8"))
    written = [tuple(map(float, line.split()))
               for line in target.read_text(encoding="utf-8").splitlines()[2:]]
    if written != expected:
        raise AssertionError("落盘处理表的五列数值未逐项保持 Excel 原值。")
    audit = {
        "paper_figure": "Figure 2", "code_directory": "正文图/Fig2",
        "mode": "direct_excel_import_complete_pgg_m_scan",
        "raw_input": {"path": str(input_path), "sha256": source_hash,
                      "sheet": sheet, "rows": len(rows), "columns": list(SOURCE_COLUMNS)},
        "target": file_record(target, len(rows)), "columns": list(TABLE_COLUMNS),
        "column_mapping": {"m": "m", "alpha": "alpha", "p": "p", "r": "r",
                           "final_avg_fc": "Coop_Rate"},
        "fixed_parameters": {"G": 4, "N": 2000, "mh": 3, "alpha": 0},
        "grid_shape": [3, 5, 41], "m_values": [1, 2, 3], "P_l_values": list(P_VALUES),
        "r_values": list(R_VALUES), "total_observations": len(rows),
        "missing_points": 0, "duplicate_points": 0, "R_over_G_matches_r": True,
        "pointwise_row_match_count": sum(all(match) for match in matches),
        "pointwise_value_match_count": sum(sum(match) for match in matches),
        "value_match_counts_by_column": {
            column: sum(match[index] for match in matches)
            for index, column in enumerate(TABLE_COLUMNS)},
        "pointwise_checks": [{"source_row": row["source_row"], "txt_file": row["txt_file"],
                              "m": row["m"], "P_l": row["p"], "r": row["r"],
                              "all_five_columns_match": all(match)}
                             for row, match in zip(rows, matches)],
        "all_five_columns_match": True, "float_roundtrip_preserved": True,
        "source_values_modified": False, "averaging_applied": False,
        "interpolation_applied": False,
    }
    atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2,
                                      allow_nan=False).encode("utf-8"))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    audit = prepare(args.input, args.target, args.audit_file)
    print(json.dumps({"target": audit["target"],
                      "pointwise_row_match_count": audit["pointwise_row_match_count"],
                      "all_five_columns_match": audit["all_five_columns_match"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
