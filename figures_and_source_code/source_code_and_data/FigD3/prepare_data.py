"""Import the measured MPD-SRH workbook for paper Figure D3.

The workbook already supplies one final_avg_fc result per parameter point.
Read it without editing Excel contents; never average it with older scans.
Run with the bundled Python runtime containing openpyxl.
"""
from argparse import ArgumentParser
from collections import Counter
from io import BytesIO
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import tempfile

from openpyxl import load_workbook


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = SCRIPT_DIR / "data"
ARCHIVE = DATA_DIR / "MPD_SRH_global_results.xlsx"
PROCESSED = DATA_DIR / "processed_coop_data.txt"
REPORT = ROOT / "交付/FigD3新数据导入检查.json"
SHEET = "Simulation Results"
HEADERS = ("G", "N", "m", "mh", "alpha", "p", "b", "final_avg_fc", "txt_file")
OUTPUT_HEADERS = ("G", "alpha", "b", "p", "Coop_Rate")
CONSTANTS = {"G": 4, "N": 2000, "m": 1, "mh": 3}
ETA_VALUES = tuple(index / 20 for index in range(21))
P_VALUES = tuple(index / 4 for index in range(5))
DELTA_VALUES = tuple(index / 40 for index in range(41))


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def _number(value, field, excel_row):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Excel row {excel_row}: {field} must be numeric, got {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Excel row {excel_row}: {field} is not finite")
    return value


def read_and_validate(source_bytes):
    """Validate the exact byte snapshot that will be archived, without edits."""
    workbook = load_workbook(BytesIO(source_bytes), read_only=True, data_only=True)
    records, paths, seen = [], [], set()
    try:
        if workbook.sheetnames != [SHEET]:
            raise ValueError(f"Expected only worksheet {SHEET!r}; found {workbook.sheetnames!r}")
        iterator = workbook[SHEET].iter_rows(values_only=True)
        if tuple(next(iterator, ())) != HEADERS:
            raise ValueError(f"Workbook header must be exactly {HEADERS!r}")
        for excel_row, values in enumerate(iterator, 2):
            if not any(value is not None for value in values):
                raise ValueError(f"Excel row {excel_row}: unexpected empty source record")
            row = dict(zip(HEADERS, values))
            numeric = {name: _number(row[name], name, excel_row) for name in HEADERS[:-1]}
            for name, expected in CONSTANTS.items():
                if numeric[name] != expected:
                    raise ValueError(f"Excel row {excel_row}: {name} must remain {expected}")
            for name, allowed in (("alpha", ETA_VALUES), ("p", P_VALUES), ("b", DELTA_VALUES)):
                if numeric[name] not in allowed:
                    raise ValueError(f"Excel row {excel_row}: {name} is outside the measured grid")
            if not 0 <= numeric["final_avg_fc"] <= 1:
                raise ValueError(f"Excel row {excel_row}: final_avg_fc must lie in [0, 1]")
            if not isinstance(row["txt_file"], str) or not row["txt_file"].strip():
                raise ValueError(f"Excel row {excel_row}: txt_file provenance is missing")
            key = (int(numeric["G"]), numeric["p"], numeric["alpha"], numeric["b"])
            if key in seen:
                raise ValueError(f"Duplicate source parameter point at Excel row {excel_row}: {key}")
            seen.add(key)
            paths.append(row["txt_file"])
            records.append((int(numeric["G"]), numeric["alpha"], numeric["b"],
                            numeric["p"], numeric["final_avg_fc"]))
    finally:
        workbook.close()
    expected = {(4, p, eta, delta) for p, eta, delta in product(P_VALUES, ETA_VALUES, DELTA_VALUES)}
    missing, extra = expected - seen, seen - expected
    if missing or extra or len(records) != 4305:
        raise ValueError(f"Incomplete Figure D3 grid: missing={len(missing)}, extra={len(extra)}, rows={len(records)}")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate txt_file provenance paths in the source workbook")
    return sorted(records, key=lambda row: (row[0], row[3], row[1], row[2]))


def processed_bytes(records):
    lines = ["\t".join(OUTPUT_HEADERS), "-" * 55]
    lines.extend("\t".join((str(row[0]), *(repr(value) for value in row[1:]))) for row in records)
    return ("\n".join(lines) + "\n").encode("utf-8")


def verify_processed(content, expected):
    lines = content.decode("utf-8-sig").splitlines()
    if tuple(lines[0].split()) != OUTPUT_HEADERS or set(lines[1]) != {"-"}:
        raise ValueError("Invalid processed TXT header or separator")
    actual = []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) != 5:
            raise ValueError("Malformed processed TXT record")
        actual.append((int(parts[0]), *map(float, parts[1:])))
    if len(actual) != len(expected):
        raise ValueError("Processed TXT record count changed")
    # float.hex also distinguishes signed zero, establishing a full round trip.
    matches = sum(before[0] == after[0] and all(a.hex() == b.hex()
                  for a, b in zip(before[1:], after[1:]))
                  for before, after in zip(expected, actual))
    if matches != len(expected):
        raise ValueError("Processed TXT numerical round-trip changed source values")
    return matches


def replace_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="figure7_import_", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def import_workbook(input_path):
    input_path = Path(input_path).expanduser().resolve()
    source_bytes = input_path.read_bytes()
    source_sha = sha256(source_bytes)
    records = read_and_validate(source_bytes)
    output_bytes = processed_bytes(records)
    verify_processed(output_bytes, records)
    if input_path.read_bytes() != source_bytes:
        raise ValueError("The input workbook changed during validation; nothing was imported")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if input_path != ARCHIVE.resolve():
        replace_bytes(ARCHIVE, source_bytes)
    if ARCHIVE.read_bytes() != source_bytes:
        raise ValueError("The archived workbook is not byte-identical to the source")
    replace_bytes(PROCESSED, output_bytes)
    matches = verify_processed(PROCESSED.read_bytes(), records)
    source_unchanged = sha256(input_path.read_bytes()) == source_sha
    if not source_unchanged:
        raise ValueError("The input workbook changed during import")
    counts = Counter(row[3] for row in records)
    values = [row[4] for row in records]
    curve_points = sum(row[1] in (0., .25, .5) for row in records)
    report = {
        "paper_figure": "Figure D3", "code_figure": "FigD3", "passed": True,
        "input_path": str(input_path), "input_sha256": source_sha,
        "input_bytes": len(source_bytes), "original_xlsx_unchanged": source_unchanged,
        "archived_workbook": ARCHIVE.relative_to(ROOT).as_posix(),
        "archive_sha256": sha256(ARCHIVE.read_bytes()), "archive_byte_identical": True,
        "sheet": SHEET, "source_headers": list(HEADERS),
        "processed_headers": list(OUTPUT_HEADERS),
        "column_mapping": {"G": "G", "alpha": "alpha", "b": "b", "p": "p", "Coop_Rate": "final_avg_fc"},
        "plot_parameter_mapping": {"alpha": "eta", "b": "delta", "p": "P_l"},
        "fixed_source_parameters": CONSTANTS, "eta_values": ETA_VALUES,
        "p_values": P_VALUES, "delta_values": DELTA_VALUES,
        "grid_shape_per_p": [len(ETA_VALUES), len(DELTA_VALUES)],
        "source_records": len(records), "unique_grid_points": len(records),
        "expected_grid_points": 4305, "missing_grid_points": 0, "extra_grid_points": 0,
        "duplicate_grid_points": 0, "unique_provenance_paths": len(records),
        "records_by_p": {f"{p:g}": counts[p] for p in P_VALUES},
        "curve_eta": [0., .25, .5], "curve_points": curve_points,
        "phase_points": len(records), "source_values_modified": False,
        "aggregation": "none: one final_avg_fc result per source parameter point",
        "mixed_with_previous_processed": False,
        "float_serialization": "Python repr(float), exact binary floating-point round trip",
        "sort_order": ["G", "p", "alpha", "b"],
        "finite_and_in_range_fc": len(values), "fc_minimum": min(values),
        "fc_maximum": max(values), "fc_zeros": values.count(0),
        "roundtrip_records_verified": matches, "all_numerical_values_roundtrip_identical": True,
        "processed_path": PROCESSED.relative_to(ROOT).as_posix(),
        "processed_sha256": sha256(PROCESSED.read_bytes()),
        "limitations": ["The source has no random-seed column; seed repetitions cannot be audited.",
                        "The source does not define the averaging window for final_avg_fc."],
    }
    replace_bytes(REPORT, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return report


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ARCHIVE,
                        help="Source XLSX; defaults to the project's unchanged archived workbook.")
    result = import_workbook(parser.parse_args().input)
    print(json.dumps({key: result[key] for key in (
        "passed", "source_records", "curve_points", "phase_points", "processed_sha256",
        "original_xlsx_unchanged")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
