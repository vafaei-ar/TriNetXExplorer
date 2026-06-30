#!/usr/bin/env python3
"""Conservative audit of TriNetX ZIP exports.

Writes aggregate metadata only: archive inventory, ZIP members, inferred CSV
schemas, row counts, and sampled missingness/type screens. It does not extract
archives or write raw patient-level rows.
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
from collections import Counter
from typing import Any, Iterable

TEXT_EXTS = {".csv", ".tsv", ".txt", ".psv"}
TABLE_HINTS = [
    "diagnos", "procedure", "medication", "lab", "encounter", "patient",
    "demograph", "vital", "observation", "order", "provider", "death",
    "visit", "facility", "cohort", "condition", "prescription", "dispens",
]
ID_RE = re.compile(r"(^|_)(patient|person|member|encounter|visit|provider|facility|id)($|_)", re.I)
DATE_RE = re.compile(r"date|time|year|month|dob|birth|death", re.I)
CODE_RE = re.compile(r"code|icd|cpt|hcpcs|ndc|loinc|rxnorm|snomed|concept", re.I)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit TriNetX ZIP exports.")
    p.add_argument("--input-glob", default="~/datasets/trinetx/*.zip")
    p.add_argument("--output-dir", default="outputs/trinetx_audit")
    p.add_argument("--sample-rows", type=int, default=5000)
    p.add_argument("--max-files", type=int, default=None)
    p.add_argument("--skip-row-counts", action="store_true")
    p.add_argument("--make-zip", action="store_true")
    return p.parse_args()


def norm(name: str) -> str:
    name = name.strip().replace("\ufeff", "")
    name = re.sub(r"[^0-9A-Za-z]+", "_", name)
    return re.sub(r"_+", "_", name).strip("_").lower() or "unnamed"


def infer_table(path: str) -> str:
    haystack = " ".join([p.lower() for p in Path(path).parts] + [Path(path).stem.lower()])
    for hint in TABLE_HINTS:
        if hint in haystack:
            return hint
    return norm(Path(path).stem)[:80]


def infer_role(col: str) -> str:
    n = norm(col)
    if ID_RE.search(n):
        return "identifier_like"
    if DATE_RE.search(n):
        return "date_time_like"
    if CODE_RE.search(n):
        return "code_like"
    if any(x in n for x in ["sex", "gender", "race", "ethnic", "age"]):
        return "demographic_like"
    if any(x in n for x in ["result", "value", "unit", "quantity", "count"]):
        return "measure_like"
    return "other"


def zip_time(info: zipfile.ZipInfo) -> str | None:
    try:
        return dt.datetime(*info.date_time).isoformat(timespec="seconds")
    except Exception:
        return None


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
    if suffix == ".psv":
        return encoding, "|"
    first = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: first.count(d) for d in [",", "\t", "|", ";"]}
    delim = max(counts, key=counts.get)
    return encoding, delim if counts[delim] else ","


def read_header(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[list[str], str, str]:
    with zf.open(info, "r") as fh:
        raw = fh.read(65536)
    encoding, delim = detect_format(raw, Path(info.filename).suffix.lower())
    text = raw.decode(encoding, errors="replace")
    header = next(csv.reader(io.StringIO(text), delimiter=delim), [])
    return [h.strip().replace("\ufeff", "") for h in header], encoding, delim


def count_rows(zf: zipfile.ZipFile, info: zipfile.ZipInfo, encoding: str) -> int:
    n = -1
    with zf.open(info, "r") as raw:
        text = io.TextIOWrapper(raw, encoding=encoding, errors="replace", newline="")
        for _ in text:
            n += 1
    return max(n, 0)


def looks_date(v: str) -> bool:
    v = v.strip()
    if not v:
        return True
    patterns = [
        r"^\d{4}-\d{2}-\d{2}$", r"^\d{1,2}/\d{1,2}/\d{2,4}$",
        r"^\d{8}$", r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", r"^\d{4}$",
    ]
    return any(re.match(p, v) for p in patterns)


def sample_profiles(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, header: list[str], encoding: str, delim: str, nrows: int
) -> dict[str, dict[str, Any]]:
    if nrows <= 0 or not header:
        return {}
    stats: dict[str, dict[str, Any]] = {
        c: {"nonmissing": 0, "missing": 0, "distinct": set(), "numeric": True, "date": True}
        for c in header
    }
    with zf.open(info, "r") as raw:
        text = io.TextIOWrapper(raw, encoding=encoding, errors="replace", newline="")
        for i, row in enumerate(csv.DictReader(text, delimiter=delim)):
            if i >= nrows:
                break
            for col in header:
                val = (row.get(col) or "").strip()
                st = stats[col]
                if val == "":
                    st["missing"] += 1
                    continue
                st["nonmissing"] += 1
                if len(st["distinct"]) < 1001:
                    st["distinct"].add(val)
                if st["numeric"]:
                    try:
                        float(val.replace(",", ""))
                    except Exception:
                        st["numeric"] = False
                if st["date"] and not looks_date(val):
                    st["date"] = False
    return {
        c: {
            "sampled_nonmissing": st["nonmissing"],
            "sampled_missing": st["missing"],
            "sampled_distinct_capped": len(st["distinct"]),
            "sampled_maybe_numeric": bool(st["numeric"] and st["nonmissing"]),
            "sampled_maybe_date": bool(st["date"] and st["nonmissing"]),
        }
        for c, st in stats.items()
    }


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def audit_one(path: Path, args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    members: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            files = [i for i in infos if not i.is_dir()]
            csv_like = [i for i in files if Path(i.filename).suffix.lower() in TEXT_EXTS]
            archive = {
                "archive_path": str(path), "archive_name": path.name,
                "archive_size_bytes": path.stat().st_size, "n_members": len(infos),
                "n_dirs": len(infos) - len(files), "n_files": len(files),
                "n_csv_like_files": len(csv_like), "n_other_files": len(files) - len(csv_like),
                "uncompressed_size_bytes": sum(i.file_size for i in files),
                "compressed_size_bytes": sum(i.compress_size for i in files),
                "audit_error": None,
            }
            parsed = 0
            for info in infos:
                suffix = Path(info.filename).suffix.lower()
                is_csv = (not info.is_dir()) and suffix in TEXT_EXTS
                m = {
                    "archive_name": path.name, "member_path": info.filename,
                    "member_name": Path(info.filename).name, "extension": suffix,
                    "compressed_size_bytes": info.compress_size,
                    "uncompressed_size_bytes": info.file_size,
                    "modified_time": zip_time(info), "is_dir": info.is_dir(),
                    "is_csv_like": is_csv, "inferred_table": infer_table(info.filename) if is_csv else None,
                    "row_count": None, "column_count": None, "delimiter": None, "encoding": None,
                    "parse_status": "not_parsed", "parse_error": None,
                }
                if is_csv and (args.max_files is None or parsed < args.max_files):
                    try:
                        header, enc, delim = read_header(zf, info)
                        m.update({"encoding": enc, "delimiter": delim, "column_count": len(header)})
                        if not args.skip_row_counts:
                            m["row_count"] = count_rows(zf, info, enc)
                        prof = sample_profiles(zf, info, header, enc, delim, args.sample_rows)
                        for pos, col in enumerate(header, start=1):
                            p = prof.get(col, {})
                            columns.append({
                                "archive_name": path.name, "member_path": info.filename,
                                "inferred_table": m["inferred_table"], "column_position": pos,
                                "column_name": col, "normalized_column_name": norm(col),
                                "inferred_role": infer_role(col), **p,
                            })
                        m["parse_status"] = "parsed_header_profiled"
                        parsed += 1
                    except Exception as e:
                        m["parse_status"] = "parse_failed"
                        m["parse_error"] = f"{type(e).__name__}: {e}"
                elif is_csv:
                    m["parse_status"] = "skipped_by_max_files"
                members.append(m)
            return archive, members, columns
    except Exception as e:
        return {
            "archive_path": str(path), "archive_name": path.name,
            "archive_size_bytes": path.stat().st_size if path.exists() else 0,
            "n_members": 0, "n_dirs": 0, "n_files": 0, "n_csv_like_files": 0,
            "n_other_files": 0, "uncompressed_size_bytes": 0, "compressed_size_bytes": 0,
            "audit_error": f"{type(e).__name__}: {e}",
        }, members, columns


def write_report(out: Path, archives: list[dict[str, Any]], members: list[dict[str, Any]], columns: list[dict[str, Any]], started: str, elapsed: float) -> None:
    parsed = [m for m in members if m.get("parse_status") == "parsed_header_profiled"]
    roles = Counter(c.get("inferred_role", "unknown") for c in columns)
    tables = Counter(c.get("inferred_table") or "unknown" for c in columns)
    lines = [
        "# TriNetX archive audit report", "", f"Started: `{started}`", f"Elapsed seconds: `{elapsed:.1f}`", "",
        "This report contains aggregate metadata only. It does not contain raw rows or patient-level identifiers.", "",
        "## Archives", "", "| Archive | Files | CSV-like files | Parsed CSV-like files | Size GB | Audit error |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for a in archives:
        n_parsed = sum(1 for m in parsed if m["archive_name"] == a["archive_name"])
        lines.append(f"| `{a['archive_name']}` | {a['n_files']} | {a['n_csv_like_files']} | {n_parsed} | {a['archive_size_bytes']/1024**3:.2f} | {a.get('audit_error') or ''} |")
    lines += ["", "## Parsed table-like files", "", "| Archive | Member | Inferred table | Rows | Columns | Delimiter | Status |", "|---|---|---|---:|---:|---|---|"]
    for m in parsed:
        delim = "tab" if m.get("delimiter") == "\t" else (m.get("delimiter") or "")
        lines.append(f"| `{m['archive_name']}` | `{m['member_path']}` | `{m.get('inferred_table') or ''}` | {m.get('row_count') or ''} | {m.get('column_count') or ''} | `{delim}` | {m['parse_status']} |")
    lines += ["", "## Column-role screen", "", "| Inferred role | Number of columns |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(roles.items())]
    lines += ["", "## Inferred table screen", "", "| Inferred table | Number of columns |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(tables.items())]
    lines += ["", "Send back the ZIP created by `--make-zip`. Do not send raw TriNetX CSV files."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def zip_output(out: Path) -> Path:
    zpath = out.with_suffix(".zip")
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(out))
    return zpath


def main() -> int:
    args = parse_args()
    t0 = time.time()
    started = dt.datetime.now().isoformat(timespec="seconds")
    paths = [Path(p) for p in sorted(glob.glob(os.path.expanduser(args.input_glob))) if p.endswith(".zip")]
    if not paths:
        print(f"No ZIP files found for pattern: {args.input_glob}", file=sys.stderr)
        return 2
    out = Path(args.output_dir) / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    archives: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    for p in paths:
        print(f"Auditing {p}")
        a, m, c = audit_one(p, args)
        archives.append(a); members.extend(m); columns.extend(c)

    archive_fields = ["archive_path", "archive_name", "archive_size_bytes", "n_members", "n_dirs", "n_files", "n_csv_like_files", "n_other_files", "uncompressed_size_bytes", "compressed_size_bytes", "audit_error"]
    member_fields = ["archive_name", "member_path", "member_name", "extension", "compressed_size_bytes", "uncompressed_size_bytes", "modified_time", "is_dir", "is_csv_like", "inferred_table", "row_count", "column_count", "delimiter", "encoding", "parse_status", "parse_error"]
    column_fields = ["archive_name", "member_path", "inferred_table", "column_position", "column_name", "normalized_column_name", "inferred_role", "sampled_nonmissing", "sampled_missing", "sampled_distinct_capped", "sampled_maybe_numeric", "sampled_maybe_date"]
    write_csv(out / "archives.csv", archives, archive_fields)
    write_csv(out / "members.csv", members, member_fields)
    write_csv(out / "schema_catalog.csv", columns, column_fields)

    manifest = {
        "started_at": started,
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - t0, 3),
        "input_glob": args.input_glob,
        "output_dir": str(out),
        "n_archives": len(archives), "n_members": len(members), "n_columns": len(columns),
        "skip_row_counts": args.skip_row_counts, "sample_rows": args.sample_rows, "max_files": args.max_files,
        "privacy_note": "Aggregate metadata only. Raw rows are not written.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(out, archives, members, columns, started, time.time() - t0)
    if args.make_zip:
        print(f"Wrote audit ZIP: {zip_output(out)}")
    print(f"Wrote audit outputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
