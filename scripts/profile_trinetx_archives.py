#!/usr/bin/env python3
"""Safe aggregate profiling for TriNetX ZIP exports.

This script reads selected CSV-like members inside TriNetX ZIP exports and writes
aggregate profiles only. It does not extract archives and does not write raw rows.

Default mode is a bounded sample per file. Use --full-scan only when you are
ready for a long run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from typing import Any, Iterable

DATE_RE = re.compile(r"date|year|month|dob|birth|death", re.I)
CODE_TABLES = {
    "diagnosis.csv", "procedure.csv", "medication_ingredient.csv",
    "medication_drug.csv", "lab_result.csv", "vitals_signs.csv",
    "genomic.csv", "tumor.csv", "tumor_properties.csv", "oncology_treatment.csv",
}
DEFAULT_TABLES = {
    "patient.csv", "patient_cohort.csv", "cohort_details.csv",
    "dataset_details.csv", "manifest.csv", "standardized_terminology.csv",
    "diagnosis.csv", "procedure.csv", "medication_ingredient.csv",
    "medication_drug.csv", "lab_result.csv", "vitals_signs.csv",
    "encounter.csv", "cost_medical.csv", "cost_pharmacy.csv",
}
DEMOGRAPHIC_FIELDS = {
    "sex", "race", "ethnicity", "marital_status", "reason_yob_missing",
    "patient_regional_location",
}
AMOUNT_FIELDS = {
    "charge_amount", "allowed_amount", "payer_amount", "patient_amount",
    "coupon_value", "quantity_dispensed", "days_supply", "refills_authorized",
    "fill_number",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Profile TriNetX ZIP exports with safe aggregate outputs.")
    p.add_argument("--input-glob", default="~/datasets/trinetx/*.zip")
    p.add_argument("--output-dir", default="outputs/trinetx_profile")
    p.add_argument("--max-rows-per-file", type=int, default=250000,
                   help="Rows to scan per file in default sampled mode.")
    p.add_argument("--full-scan", action="store_true", help="Scan all rows in selected files. Can be slow.")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--small-cell-threshold", type=int, default=11)
    p.add_argument("--max-distinct-keys", type=int, default=250000)
    p.add_argument("--include-source-values", action="store_true",
                   help="Include source_id values. Default is false to avoid exposing site/source labels.")
    p.add_argument("--tables", default=",".join(sorted(DEFAULT_TABLES)),
                   help="Comma-separated member filenames to profile.")
    p.add_argument("--make-zip", action="store_true")
    return p.parse_args()


def archive_label(name: str) -> str:
    if name.startswith("66350692"):
        return "control_20240514"
    if name.startswith("stroke_diamond"):
        return "stroke_diamond"
    if name.startswith("stroke_research"):
        return "stroke_research"
    return Path(name).stem[:80]


def detect_format(raw: bytes, suffix: str) -> tuple[str, str]:
    encoding = "utf-8"
    text = ""
    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            text = raw.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            pass
    if suffix == ".tsv":
        return encoding, "\t"
    first = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: first.count(d) for d in [",", "\t", "|", ";"]}
    delim = max(counts, key=counts.get)
    return encoding, delim if counts[delim] else ","


def open_dict_reader(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[csv.DictReader, io.TextIOWrapper]:
    with zf.open(info, "r") as fh:
        raw = fh.read(65536)
    encoding, delim = detect_format(raw, Path(info.filename).suffix.lower())
    raw_fh = zf.open(info, "r")
    text = io.TextIOWrapper(raw_fh, encoding=encoding, errors="replace", newline="")
    return csv.DictReader(text, delimiter=delim), text


def parse_date_value(value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d", "%Y-%m", "%Y"]:
        try:
            d = dt.datetime.strptime(v[:10] if fmt == "%Y-%m-%d" else v, fmt)
            if fmt == "%Y":
                return f"{d.year:04d}"
            if fmt == "%Y-%m":
                return f"{d.year:04d}-{d.month:02d}"
            return d.date().isoformat()
        except Exception:
            pass
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", v):
        return v[:10]
    return None


def add_counter(counter: Counter, key: tuple[Any, ...], max_keys: int) -> None:
    if key in counter or len(counter) < max_keys:
        counter[key] += 1
    else:
        counter[("__OTHER_KEYS_OVER_CAP__",)] += 1


def safe_count_rows(counter: Counter, threshold: int, base: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    suppressed_n = 0
    suppressed_categories = 0
    for key, n in counter.items():
        if n < threshold:
            suppressed_n += n
            suppressed_categories += 1
            continue
        row = dict(base)
        if not isinstance(key, tuple):
            key = (key,)
        for i, value in enumerate(key, start=1):
            row[f"value_{i}"] = value
        row["n"] = n
        row["suppressed"] = False
        rows.append(row)
    if suppressed_categories:
        row = dict(base)
        row["value_1"] = "__SUPPRESSED_SMALL_CELLS__"
        row["n"] = None
        row["suppressed"] = True
        row["suppressed_categories"] = suppressed_categories
        row["suppressed_total_known"] = suppressed_n if suppressed_n >= threshold else None
        rows.append(row)
    return rows


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n_numeric": 0, "min": None, "max": None, "mean": None}
    return {
        "n_numeric": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def profile_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    archive_name: str,
    archive_short: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    member = Path(info.filename).name
    reader, text = open_dict_reader(zf, info)
    fields = reader.fieldnames or []
    date_fields = [c for c in fields if DATE_RE.search(c)]
    code_fields = [c for c in fields if c in {"code", "code_system"} or c.endswith("_code") or c.endswith("_code_system")]
    demo_fields = [c for c in fields if c in DEMOGRAPHIC_FIELDS]
    amount_fields = [c for c in fields if c in AMOUNT_FIELDS]

    code_system_counts: Counter = Counter()
    top_code_counts: Counter = Counter()
    demo_counts: dict[str, Counter] = defaultdict(Counter)
    date_stats: dict[str, dict[str, Any]] = {c: {"min": None, "max": None, "n_valid": 0, "n_missing": 0, "n_invalid": 0} for c in date_fields}
    amount_values: dict[str, list[float]] = defaultdict(list)
    metadata_rows: list[dict[str, Any]] = []
    row_count = 0
    max_rows = None if args.full_scan else args.max_rows_per_file

    try:
        for row in reader:
            row_count += 1
            if max_rows is not None and row_count > max_rows:
                row_count -= 1
                break

            if member in {"cohort_details.csv", "dataset_details.csv", "manifest.csv"}:
                safe_row = {k: v for k, v in row.items() if k and k.lower() not in {"patient_id", "encounter_id", "unique_id", "source_id"}}
                safe_row.update({"archive_name": archive_name, "archive_short": archive_short, "member_path": member})
                metadata_rows.append(safe_row)
                continue

            if "code_system" in row:
                cs = (row.get("code_system") or "").strip() or "__MISSING__"
                add_counter(code_system_counts, (cs,), args.max_distinct_keys)
            if "code_system" in row and "code" in row and member in CODE_TABLES:
                cs = (row.get("code_system") or "").strip() or "__MISSING__"
                code = (row.get("code") or "").strip() or "__MISSING__"
                add_counter(top_code_counts, (cs, code), args.max_distinct_keys)

            for c in demo_fields:
                v = (row.get(c) or "").strip() or "__MISSING__"
                add_counter(demo_counts[c], (v,), args.max_distinct_keys)

            for c in date_fields:
                v = row.get(c) or ""
                parsed = parse_date_value(v)
                st = date_stats[c]
                if not v.strip():
                    st["n_missing"] += 1
                elif parsed is None:
                    st["n_invalid"] += 1
                else:
                    st["n_valid"] += 1
                    st["min"] = parsed if st["min"] is None or parsed < st["min"] else st["min"]
                    st["max"] = parsed if st["max"] is None or parsed > st["max"] else st["max"]

            for c in amount_fields:
                v = (row.get(c) or "").strip().replace(",", "")
                if not v:
                    continue
                try:
                    if len(amount_values[c]) < 100000:
                        amount_values[c].append(float(v))
                except Exception:
                    pass
    finally:
        try:
            text.detach().close()
        except Exception:
            pass

    out: dict[str, Any] = {
        "archive_name": archive_name,
        "archive_short": archive_short,
        "member_path": member,
        "rows_scanned": row_count,
        "scan_mode": "full" if args.full_scan else "sample",
        "code_system_rows": safe_count_rows(code_system_counts, args.small_cell_threshold, {"archive_name": archive_name, "archive_short": archive_short, "member_path": member}),
        "top_code_rows": safe_count_rows(top_code_counts, args.small_cell_threshold, {"archive_name": archive_name, "archive_short": archive_short, "member_path": member})[: args.top_n + 1],
        "demographic_rows": [],
        "date_rows": [],
        "amount_rows": [],
        "metadata_rows": metadata_rows,
    }
    for field, counter in demo_counts.items():
        out["demographic_rows"].extend(safe_count_rows(counter, args.small_cell_threshold, {"archive_name": archive_name, "archive_short": archive_short, "member_path": member, "field": field}))
    for field, st in date_stats.items():
        out["date_rows"].append({"archive_name": archive_name, "archive_short": archive_short, "member_path": member, "field": field, **st})
    for field, values in amount_values.items():
        out["amount_rows"].append({"archive_name": archive_name, "archive_short": archive_short, "member_path": member, "field": field, **numeric_summary(values)})
    return out


def zip_output(out: Path) -> Path:
    zpath = out.with_suffix(".zip")
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(out))
    return zpath


def main() -> int:
    args = parse_args()
    started = dt.datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    selected = {t.strip() for t in args.tables.split(",") if t.strip()}
    paths = [Path(p) for p in sorted(glob.glob(os.path.expanduser(args.input_glob))) if p.endswith(".zip")]
    if not paths:
        print(f"No ZIP files found for pattern: {args.input_glob}", file=sys.stderr)
        return 2

    out = Path(args.output_dir) / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    table_profiles: list[dict[str, Any]] = []
    code_system_rows: list[dict[str, Any]] = []
    top_code_rows: list[dict[str, Any]] = []
    demographic_rows: list[dict[str, Any]] = []
    date_rows: list[dict[str, Any]] = []
    amount_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []

    for path in paths:
        archive_name = path.name
        archive_short = archive_label(archive_name)
        print(f"Profiling {archive_name}")
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member = Path(info.filename).name
                if member not in selected:
                    continue
                if Path(info.filename).suffix.lower() not in {".csv", ".txt", ".tsv"}:
                    continue
                print(f"  {member}")
                try:
                    prof = profile_member(zf, info, archive_name, archive_short, args)
                    table_profiles.append({
                        "archive_name": archive_name,
                        "archive_short": archive_short,
                        "member_path": member,
                        "rows_scanned": prof["rows_scanned"],
                        "scan_mode": prof["scan_mode"],
                    })
                    code_system_rows.extend(prof["code_system_rows"])
                    top_code_rows.extend(prof["top_code_rows"])
                    demographic_rows.extend(prof["demographic_rows"])
                    date_rows.extend(prof["date_rows"])
                    amount_rows.extend(prof["amount_rows"])
                    metadata_rows.extend(prof["metadata_rows"])
                except Exception as e:
                    table_profiles.append({
                        "archive_name": archive_name,
                        "archive_short": archive_short,
                        "member_path": member,
                        "rows_scanned": None,
                        "scan_mode": "error",
                        "error": f"{type(e).__name__}: {e}",
                    })

    write_csv(out / "table_profiles.csv", table_profiles,
              ["archive_name", "archive_short", "member_path", "rows_scanned", "scan_mode", "error"])
    write_csv(out / "code_system_counts.csv", code_system_rows,
              ["archive_name", "archive_short", "member_path", "value_1", "n", "suppressed", "suppressed_categories", "suppressed_total_known"])
    write_csv(out / "top_codes_suppressed.csv", top_code_rows,
              ["archive_name", "archive_short", "member_path", "value_1", "value_2", "n", "suppressed", "suppressed_categories", "suppressed_total_known"])
    write_csv(out / "patient_demographics_suppressed.csv", demographic_rows,
              ["archive_name", "archive_short", "member_path", "field", "value_1", "n", "suppressed", "suppressed_categories", "suppressed_total_known"])
    write_csv(out / "date_ranges.csv", date_rows,
              ["archive_name", "archive_short", "member_path", "field", "min", "max", "n_valid", "n_missing", "n_invalid"])
    write_csv(out / "numeric_summaries.csv", amount_rows,
              ["archive_name", "archive_short", "member_path", "field", "n_numeric", "min", "max", "mean"])
    write_csv(out / "metadata_tables.csv", metadata_rows,
              sorted(set().union(*(r.keys() for r in metadata_rows))) if metadata_rows else ["archive_name", "archive_short", "member_path"])

    manifest = {
        "started_at": started,
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - t0, 3),
        "input_glob": args.input_glob,
        "output_dir": str(out),
        "scan_mode": "full" if args.full_scan else "sample",
        "max_rows_per_file": args.max_rows_per_file,
        "small_cell_threshold": args.small_cell_threshold,
        "top_n": args.top_n,
        "include_source_values": args.include_source_values,
        "privacy_note": "Aggregate metadata only. Raw rows and patient-level identifiers are not written.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.make_zip:
        print(f"Wrote profile ZIP: {zip_output(out)}")
    print(f"Wrote profile outputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
