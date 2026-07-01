#!/usr/bin/env python3
"""Convert selected TriNetX ZIP export members to partitioned Parquet.

This converter streams CSV-like files from ZIP archives in chunks. It does not
extract full CSV files to disk. It writes a conversion catalog so the next step
can build DuckDB views and dashboard pages over Parquet.

Default tables are intentionally conservative. Add large tables explicitly only
after confirming storage and runtime.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile
from typing import Any

import pandas as pd

DEFAULT_TABLES = [
    "patient.csv",
    "patient_cohort.csv",
    "cohort_details.csv",
    "dataset_details.csv",
    "manifest.csv",
    "standardized_terminology.csv",
    "diagnosis.csv",
    "procedure.csv",
]

CSV_EXTS = {".csv", ".tsv", ".txt"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert selected TriNetX ZIP members to Parquet.")
    p.add_argument("--input-glob", default="~/datasets/trinetx/*.zip")
    p.add_argument("--output-dir", default="data/trinetx_parquet")
    p.add_argument("--catalog-dir", default="outputs/trinetx_parquet_catalog")
    p.add_argument("--tables", default=",".join(DEFAULT_TABLES),
                   help="Comma-separated member filenames or table names. Example: patient.csv,diagnosis.csv")
    p.add_argument("--archives", default="all",
                   help="Comma-separated archive labels to include, or all. Labels: control_20240514,stroke_diamond,stroke_research")
    p.add_argument("--chunksize", type=int, default=250000)
    p.add_argument("--compression", default="snappy", choices=["snappy", "gzip", "brotli", "zstd", "none"])
    p.add_argument("--max-chunks-per-file", type=int, default=None,
                   help="Debug option. Convert only the first N chunks per matched member.")
    p.add_argument("--overwrite", action="store_true",
                   help="Remove existing archive/table output before converting it again.")
    p.add_argument("--dry-run", action="store_true",
                   help="List matched ZIP members without writing Parquet.")
    return p.parse_args()


def archive_label(name: str) -> str:
    if name.startswith("66350692"):
        return "control_20240514"
    if name.startswith("stroke_diamond"):
        return "stroke_diamond"
    if name.startswith("stroke_research"):
        return "stroke_research"
    return Path(name).stem[:80]


def table_name(member_name: str) -> str:
    return Path(member_name).stem.lower()


def normalize_table_token(token: str) -> str:
    token = token.strip()
    if not token:
        return token
    if not token.lower().endswith(tuple(CSV_EXTS)):
        return f"{token}.csv"
    return token


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


def member_format(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[str, str]:
    with zf.open(info, "r") as fh:
        raw = fh.read(65536)
    return detect_format(raw, Path(info.filename).suffix.lower())


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def convert_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    archive_short: str,
    archive_name: str,
    out_base: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    member_name = Path(info.filename).name
    tname = table_name(member_name)
    out_dir = out_base / f"archive={archive_short}" / f"table={tname}"
    started = time.time()

    base_record: dict[str, Any] = {
        "archive_name": archive_name,
        "archive_short": archive_short,
        "member_path": info.filename,
        "member_name": member_name,
        "table": tname,
        "output_dir": str(out_dir),
        "status": None,
        "rows_written": 0,
        "chunks_written": 0,
        "columns": None,
        "elapsed_seconds": None,
        "error": None,
    }

    if args.dry_run:
        base_record["status"] = "dry_run_matched"
        return base_record

    if out_dir.exists() and not args.overwrite:
        base_record["status"] = "skipped_exists"
        base_record["error"] = "Output exists. Use --overwrite to regenerate."
        return base_record

    if args.overwrite:
        safe_rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    compression = None if args.compression == "none" else args.compression
    encoding, sep = member_format(zf, info)

    try:
        with zf.open(info, "r") as raw:
            reader = pd.read_csv(
                raw,
                sep=sep,
                encoding=encoding,
                dtype="string",
                chunksize=args.chunksize,
                low_memory=False,
                keep_default_na=False,
            )
            for chunk_idx, chunk in enumerate(reader):
                if args.max_chunks_per_file is not None and chunk_idx >= args.max_chunks_per_file:
                    break
                # Keep original TriNetX column names, but add source columns for partition-independent traceability.
                chunk.insert(0, "__archive_short", archive_short)
                chunk.insert(1, "__source_archive", archive_name)
                chunk.insert(2, "__source_member", info.filename)
                part_path = out_dir / f"part-{chunk_idx:05d}.parquet"
                chunk.to_parquet(part_path, index=False, engine="pyarrow", compression=compression)
                base_record["rows_written"] += int(len(chunk))
                base_record["chunks_written"] += 1
                base_record["columns"] = int(len(chunk.columns))
                print(f"    wrote {part_path} rows={len(chunk):,}")
        base_record["status"] = "converted"
    except Exception as exc:
        base_record["status"] = "failed"
        base_record["error"] = f"{type(exc).__name__}: {exc}"
        if base_record["chunks_written"] == 0:
            safe_rmtree(out_dir)
    finally:
        base_record["elapsed_seconds"] = round(time.time() - started, 3)
    return base_record


def main() -> int:
    args = parse_args()
    selected_tables = {normalize_table_token(t).lower() for t in args.tables.split(",") if t.strip()}
    selected_archives = {a.strip() for a in args.archives.split(",") if a.strip() and a.strip().lower() != "all"}

    zip_paths = [Path(p) for p in sorted(glob.glob(os.path.expanduser(args.input_glob))) if p.endswith(".zip")]
    if not zip_paths:
        print(f"No ZIP files found for pattern: {args.input_glob}", file=sys.stderr)
        return 2

    out_base = Path(args.output_dir)
    catalog_root = Path(args.catalog_dir) / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    catalog_root.mkdir(parents=True, exist_ok=True)

    print("Selected tables:", ", ".join(sorted(selected_tables)))
    print("Output directory:", out_base)
    print("Catalog directory:", catalog_root)

    records: list[dict[str, Any]] = []
    started = time.time()

    for zpath in zip_paths:
        archive_name = zpath.name
        archive_short = archive_label(archive_name)
        if selected_archives and archive_short not in selected_archives:
            continue
        print(f"\nArchive: {archive_short} ({archive_name})")
        with zipfile.ZipFile(zpath, "r") as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            for info in infos:
                member_name = Path(info.filename).name.lower()
                if Path(member_name).suffix.lower() not in CSV_EXTS:
                    continue
                if member_name not in selected_tables:
                    continue
                print(f"  Converting {info.filename}")
                rec = convert_member(zf, info, archive_short, archive_name, out_base, args)
                print(f"    status={rec['status']} rows={rec['rows_written']:,} chunks={rec['chunks_written']} elapsed={rec['elapsed_seconds']}")
                records.append(rec)

    fields = [
        "archive_name", "archive_short", "member_path", "member_name", "table", "output_dir",
        "status", "rows_written", "chunks_written", "columns", "elapsed_seconds", "error",
    ]
    write_csv(catalog_root / "conversion_catalog.csv", records, fields)
    manifest = {
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - started, 3),
        "input_glob": args.input_glob,
        "output_dir": str(out_base),
        "catalog_dir": str(catalog_root),
        "tables": sorted(selected_tables),
        "archives": sorted(selected_archives) if selected_archives else "all",
        "chunksize": args.chunksize,
        "compression": args.compression,
        "dry_run": args.dry_run,
        "overwrite": args.overwrite,
        "n_records": len(records),
        "n_converted": sum(1 for r in records if r.get("status") == "converted"),
        "n_failed": sum(1 for r in records if r.get("status") == "failed"),
    }
    (catalog_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nWrote conversion catalog: {catalog_root / 'conversion_catalog.csv'}")
    if manifest["n_failed"]:
        print(f"Failures: {manifest['n_failed']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
