"""Import Figure D1's complete SRH PGG workbook without averaging observations.

The default source is this figure's data/PGG_SRH_global_results.xlsx. Importing
it replaces all five p*.txt scans and their processed table from one validated
4305-point snapshot. Traditional TXT aggregation requires explicit --scan-dir;
a missing or invalid workbook never falls back to previously generated scans.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import re
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = SCRIPT_DIR / "data"
PHASE_PATH = SCRIPT_DIR / "phase.py"
DEFAULT_SCAN_DIR = DATA_DIR
DEFAULT_INPUT = DATA_DIR / "PGG_SRH_global_results.xlsx"
DEFAULT_TARGET = DATA_DIR / "processed_coop_data.txt"
DEFAULT_AUDIT = PROJECT_ROOT / "交付" / "FigD1数据聚合检查.json"
WORKBOOK_HEADERS = ("G", "N", "m", "mh", "alpha", "p", "R", "r", "final_avg_fc", "txt_file")
OUTPUT_HEADERS = ("G", "alpha", "p", "r", "Coop_Rate")
FIXED_PARAMETERS = {"G": 4, "N": 2000, "m": 1, "mh": 3}
ETA_VALUES = tuple(index / 20 for index in range(21))
P_VALUES = tuple(index / 4 for index in range(5))
R_VALUES = tuple(index / 20 for index in range(41))


def load_phase_module():
    spec = importlib.util.spec_from_file_location("figure6_phase_data", PHASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_numeric_tokens(path, columns):
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
             if line.strip() and not re.fullmatch(r"-+", line.strip())]
    header = lines[0].split()
    indices = [header.index(column) for column in columns]
    return [tuple(row.split()[index] for index in indices) for row in lines[1:]]


def token_sort_key(tokens):
    # Sort in the same G, p, alpha, r order as the strict phase reader.
    return tuple(Decimal(tokens[index]) for index in (0, 2, 1, 3))


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == content:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="figure6_import_", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _number(value, column, excel_row):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Excel 第 {excel_row} 行的 {column} 必须是数值，实际 {value!r}。")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Excel 第 {excel_row} 行的 {column} 不是有限数值。")
    return value


def _grid_index(value, allowed, column, excel_row):
    matches = [index for index, candidate in enumerate(allowed)
               if math.isclose(value, candidate, rel_tol=0, abs_tol=1e-12)]
    if len(matches) != 1:
        raise ValueError(f"Excel 第 {excel_row} 行的 {column} 不在规定的测量网格上。")
    # The index validates grid membership; the original numeric value is retained.
    return matches[0]


def read_and_validate_workbook(source_bytes):
    """Return exact cell floats and provenance after validating the whole grid."""
    workbook = load_workbook(BytesIO(source_bytes), read_only=True, data_only=False)
    records, seen, provenance = [], set(), set()
    eta_by_p, r_by_p = {}, {}
    max_r_relation_error = 0.0
    try:
        if len(workbook.sheetnames) != 1:
            raise ValueError(f"PGG 工作簿必须只有一张数据工作表，实际 {workbook.sheetnames!r}。")
        sheet_name = workbook.sheetnames[0]
        iterator = workbook[sheet_name].iter_rows(values_only=True)
        if tuple(next(iterator, ())) != WORKBOOK_HEADERS:
            raise ValueError(f"PGG 工作簿表头必须恰好为 {WORKBOOK_HEADERS!r}。")
        for excel_row, values in enumerate(iterator, start=2):
            if len(values) != len(WORKBOOK_HEADERS):
                raise ValueError(f"Excel 第 {excel_row} 行的字段数错误。")
            row = dict(zip(WORKBOOK_HEADERS, values))
            numeric = {column: _number(row[column], column, excel_row)
                       for column in WORKBOOK_HEADERS[:-1]}
            for column, expected in FIXED_PARAMETERS.items():
                if numeric[column] != expected:
                    raise ValueError(f"Excel 第 {excel_row} 行的 {column} 必须为 {expected}。")
            eta_index = _grid_index(numeric["alpha"], ETA_VALUES, "alpha", excel_row)
            p_index = _grid_index(numeric["p"], P_VALUES, "p", excel_row)
            r_index = _grid_index(numeric["r"], R_VALUES, "r", excel_row)
            relation_error = abs(numeric["R"] / numeric["G"] - numeric["r"])
            if relation_error > 1e-12:
                raise ValueError(f"Excel 第 {excel_row} 行不满足 R/G=r。")
            max_r_relation_error = max(max_r_relation_error, relation_error)
            if not 0 <= numeric["final_avg_fc"] <= 1:
                raise ValueError(f"Excel 第 {excel_row} 行的 final_avg_fc 必须在 [0, 1]。")
            point = (p_index, eta_index, r_index)
            if point in seen:
                raise ValueError(f"Excel 第 {excel_row} 行含重复 (p, alpha, r) 坐标。")
            seen.add(point)
            path = row["txt_file"]
            if not isinstance(path, str) or not path.strip() or path in provenance:
                raise ValueError(f"Excel 第 {excel_row} 行的 txt_file 来源路径缺失或重复。")
            provenance.add(path)
            eta_by_p.setdefault(p_index, set()).add(numeric["alpha"])
            r_by_p.setdefault(p_index, set()).add(numeric["r"])
            records.append((int(numeric["G"]), numeric["alpha"], numeric["p"],
                            numeric["r"], numeric["final_avg_fc"]))
    finally:
        workbook.close()
    expected_grid = {(p, eta, r) for p in range(5) for eta in range(21) for r in range(41)}
    if seen != expected_grid or len(records) != 4305:
        raise ValueError(f"完整 PGG 网格必须有 4305 个唯一点：缺少 {len(expected_grid - seen)}，"
                         f"额外 {len(seen - expected_grid)}，实际 {len(records)} 行。")
    # Reject inconsistent representations that would create extra axis levels
    # during pivoting; never round or otherwise replace source coordinates.
    if any(len(eta_by_p[index]) != 21 or len(r_by_p[index]) != 41 for index in range(5)):
        raise ValueError("同一 p 分组的原始坐标必须恰好包含 21 个 alpha 和 41 个 r。")
    if len({row[2] for row in records}) != 5:
        raise ValueError("原始 p 坐标必须恰好包含五个不同值。")
    records.sort(key=lambda row: (row[0], row[2], row[1], row[3]))
    return records, {"sheet": sheet_name, "source_headers": list(WORKBOOK_HEADERS),
                     "fixed_source_parameters": FIXED_PARAMETERS,
                     "source_records": len(records), "unique_provenance_paths": len(provenance),
                     "R_over_G_equals_r": True, "R_over_G_max_absolute_error": max_r_relation_error,
                     "coordinate_tolerance": 1e-12, "coordinates_modified": False}


def processed_bytes(records):
    lines = ["\t".join(OUTPUT_HEADERS), "-" * 60]
    lines.extend("\t".join((str(row[0]), *(repr(value) for value in row[1:]))) for row in records)
    return ("\n".join(lines) + "\n").encode("utf-8")


def verify_processed(content, expected):
    """Check every output float bit, without pandas' decimal conversion path."""
    lines = content.decode("utf-8-sig").splitlines()
    if tuple(lines[0].split()) != OUTPUT_HEADERS or set(lines[1]) != {"-"}:
        raise ValueError("处理表的表头或分隔符错误。")
    actual = []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) != len(OUTPUT_HEADERS):
            raise ValueError("处理表的数据行必须恰好有五列。")
        actual.append((int(parts[0]), *map(float, parts[1:])))
    if len(actual) != len(expected):
        raise ValueError("处理表的行数与原始扫描不符。")
    match = np.array([[before[0] == after[0],
                       *(a.hex() == b.hex() for a, b in zip(before[1:], after[1:]))]
                      for before, after in zip(expected, actual)], dtype=bool)
    if not match.all():
        raise ValueError("处理表存在不能精确回读为原始浮点值的数据。")
    return match


def _audit_base(phase, target, sources, expected, match):
    return {
        "paper_figure": "Figure D1", "code_directory": "附录图/FigD1",
        "mode": "aggregated_complete_pgg", "raw_inputs": sources,
        "target": phase.file_record(target, len(expected)),
        "sort_columns": ["G", "p", "alpha", "r"],
        "columns": list(OUTPUT_HEADERS), "total_observations": len(expected),
        "groups": [{"g": 4, "P_l": p, "observations": 861,
                    "grid_shape": [21, 41], "eta_values": 21, "r_values": 41,
                    "missing_points": 0, "duplicate_points": 0} for p in P_VALUES],
        "pointwise_row_match_count": int(np.all(match, axis=1).sum()),
        "pointwise_value_match_count": int(match.sum()),
        "value_match_counts_by_column": {
            column: int(match[:, index].sum()) for index, column in enumerate(OUTPUT_HEADERS)},
        "all_five_columns_match": bool(match.all()), "numeric_tokens_preserved": True,
        "source_values_modified": False, "averaging_applied": False,
        "interpolation_applied": False,
    }


def import_workbook(input_path=DEFAULT_INPUT, target=DEFAULT_TARGET, audit_path=DEFAULT_AUDIT):
    phase = load_phase_module()
    input_path, target, audit_path = [Path(path).expanduser().resolve()
                                      for path in (input_path, target, audit_path)]
    scan_paths = [(target.parent / name, p) for name, p in phase.SCAN_FILES]
    if len({input_path, target, audit_path, *(path for path, _ in scan_paths)}) != 8:
        raise ValueError("原始工作簿、处理表、检查报告与五份扫描不能互相覆盖。")
    # Missing/invalid XLSX is fatal: previously generated TXT files are outputs,
    # never an implicit replacement for the explicitly selected source.
    source_bytes = input_path.read_bytes()
    records, workbook_metadata = read_and_validate_workbook(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    output = processed_bytes(records)
    match = verify_processed(output, records)
    frame = phase.validate_data(pd.DataFrame(records, columns=OUTPUT_HEADERS), str(input_path))
    scans = []
    for path, p in scan_paths:
        subset = [row for row in records if math.isclose(row[2], p, rel_tol=0, abs_tol=1e-12)]
        subset_frame = frame[np.isclose(frame["p"], p, rtol=0, atol=1e-12)]
        phase.validate_complete_scan(subset_frame, p, str(input_path))
        content = processed_bytes(subset)
        verify_processed(content, subset)
        scans.append((path, p, subset, content))
    if input_path.read_bytes() != source_bytes:
        raise ValueError("验证期间原始工作簿发生变化；未导入。")
    for path, _, _, content in scans:
        atomic_write(path, content)
    atomic_write(target, output)
    match = verify_processed(target.read_bytes(), records)
    sources = []
    processed_tokens = []
    for path, p, subset, content in scans:
        if path.read_bytes() != content:
            raise AssertionError(f"派生扫描 {path} 与已验证内容不一致。")
        verify_processed(path.read_bytes(), subset)
        processed_tokens.extend(raw_numeric_tokens(path, OUTPUT_HEADERS))
        sources.append({**phase.file_record(path, len(subset)), "P_l": p,
                        "grid_shape": [21, 41], "eta_values": 21, "r_values": 41,
                        "source_type": "derived_exact_workbook_scan",
                        "source_workbook_sha256": source_sha})
    if processed_tokens != raw_numeric_tokens(target, OUTPUT_HEADERS):
        raise AssertionError("五份派生扫描与聚合处理表的数字字面值不一致。")
    if input_path.read_bytes() != source_bytes:
        raise ValueError("导入期间原始工作簿发生变化；不会记录成功报告。")
    audit = _audit_base(phase, target, sources, records, match)
    audit.update({"input_type": "xlsx", "import_mode": "complete_pgg_workbook",
                  "workbook_input": phase.file_record(input_path, len(records)),
                  **workbook_metadata, "original_xlsx_unchanged": True,
                  "column_mapping": {"G": "G", "alpha": "alpha", "p": "p", "r": "r",
                                     "Coop_Rate": "final_avg_fc"},
                  "float_serialization": "Python repr(float), verified by float.hex() round trip",
                  "all_numerical_values_roundtrip_identical": True,
                  "numeric_tokens_definition": "Exact repr(float) tokens shared by the five derived scans and processed table.",
                  "previous_processed_data_read": False, "mixed_with_previous_data": False,
                  "processed_outputs_replaced": [str(path) for path, _ in scan_paths] + [str(target)]})
    atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2,
                                     allow_nan=False).encode("utf-8"))
    return audit


def aggregate(scan_dir=None, target=DEFAULT_TARGET, audit_path=DEFAULT_AUDIT, input_path=None):
    if scan_dir is None:
        return import_workbook(DEFAULT_INPUT if input_path is None else input_path, target, audit_path)
    if input_path is not None:
        raise ValueError("--input 和 --scan-dir 只能选择一个独立来源。")
    phase = load_phase_module()
    scan_dir, target, audit_path = [Path(path).expanduser().resolve()
                                   for path in (scan_dir, target, audit_path)]
    if target in {scan_dir / name for name, _ in phase.SCAN_FILES}:
        raise ValueError("聚合目标不能覆盖五份原始扫描。")
    frames, tokens, sources = [], [], []
    for name, expected_p in phase.SCAN_FILES:
        path = scan_dir / name
        frame = phase.validate_complete_scan(phase.read_processed_data(path), expected_p, str(path))
        frames.append(frame)
        source_tokens = raw_numeric_tokens(path, phase.REQUIRED_COLUMNS)
        if len(source_tokens) != len(frame):
            raise AssertionError(f"{path} 的原始数字 token 行数不符。")
        tokens.extend(source_tokens)
        sources.append({**phase.file_record(path, len(frame)), "P_l": expected_p,
                        "grid_shape": [21, 41], "eta_values": 21, "r_values": 41})
    expected = phase.validate_data(pd.concat(frames, ignore_index=True), str(scan_dir))
    tokens.sort(key=token_sort_key)
    if len(tokens) != 4305:
        raise AssertionError("五份完整扫描必须恰好包含 4305 条观测。")
    text = "\t".join(phase.REQUIRED_COLUMNS) + "\n" + "-" * 60 + "\n"
    text += "".join("\t".join(row) + "\n" for row in tokens)
    target_bytes = text.encode("utf-8")
    # Validate the exact proposed table before replacing the processed output.
    proposed = phase.validate_data(pd.read_csv(StringIO(
        "\t".join(phase.REQUIRED_COLUMNS) + "\n" +
        "".join("\t".join(row) + "\n" for row in tokens)), sep=r"\s+",
        converters={column: float for column in phase.REQUIRED_COLUMNS}), str(target))
    actual_values = proposed.loc[:, list(phase.REQUIRED_COLUMNS)].to_numpy(dtype=float)
    expected_values = expected.loc[:, list(phase.REQUIRED_COLUMNS)].to_numpy(dtype=float)
    match = actual_values == expected_values
    if not match.all():
        raise AssertionError("聚合结果的五列数值必须逐项等于五份原始扫描。")
    atomic_write(target, target_bytes)
    result = phase.read_processed_data(target)
    if not np.array_equal(result.to_numpy(dtype=float), expected_values):
        raise AssertionError("落盘后的聚合表与原始扫描不逐项一致。")
    if raw_numeric_tokens(target, phase.REQUIRED_COLUMNS) != tokens:
        raise AssertionError("落盘后的数字 tokens 未完整保留原始字面值。")
    audit = _audit_base(phase, target, sources, result, match)
    audit.update({"input_type": "explicit_txt_scans", "import_mode": "explicit_complete_pgg_scans"})
    atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2,
                                     allow_nan=False).encode("utf-8"))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, default=None,
                        help="完整 PGG XLSX；默认本图 data/PGG_SRH_global_results.xlsx。")
    source.add_argument("--scan-dir", type=Path, default=None,
                        help="显式选择传统五份 TXT 扫描；默认不会读取旧扫描。")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    audit = aggregate(args.scan_dir, args.target, args.audit_file, args.input)
    print(json.dumps({"target": audit["target"],
                      "pointwise_row_match_count": audit["pointwise_row_match_count"],
                      "all_five_columns_match": audit["all_five_columns_match"],
                      "numeric_tokens_preserved": audit["numeric_tokens_preserved"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
