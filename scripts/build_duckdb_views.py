#!/usr/bin/env python3
"""Build DuckDB views over partitioned TriNetX Parquet files.

The script discovers directories like:

    data/trinetx_parquet/archive=stroke_research/table=diagnosis/*.parquet

and creates one DuckDB view per table:

    v_diagnosis
    v_patient
    v_manifest

Views use DuckDB `read_parquet(..., union_by_name=true, hive_partitioning=true)`.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

import duckdb


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build DuckDB views over TriNetX Parquet output.")
    p.add_argument("--parquet-dir", default="data/trinetx_parquet")
    p.add_argument("--duckdb-path", default="data/trinetx.duckdb")
    p.add_argument("--catalog-dir", default="outputs/trinetx_duckdb_catalog")
    p.add_argument("--count-rows", action="store_true",
                   help="Run count(*) for each view. Can be expensive for large event tables.")
    p.add_argument("--overwrite", action="store_true",
                   help="Delete existing DuckDB file before building views.")
    return p.parse_args()


def clean_identifier(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "table"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned


def discover_tables(parquet_dir: Path) -> dict[str, list[Path]]:
    tables: dict[str, list[Path]] = {}
    for table_dir in sorted(parquet_dir.glob("archive=*/table=*")):
        if not table_dir.is_dir():
            continue
        table_label = table_dir.name.split("table=", 1)[-1]
        parquet_files = sorted(table_dir.glob("*.parquet"))
        if parquet_files:
            tables.setdefault(table_label, []).extend(parquet_files)
    return tables


def sql_quote_path(path: str) -> str:
    return path.replace("'", "''")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    started = time.time()
    parquet_dir = Path(args.parquet_dir)
    duckdb_path = Path(args.duckdb_path)
    catalog_root = Path(args.catalog_dir) / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    catalog_root.mkdir(parents=True, exist_ok=True)

    if not parquet_dir.exists():
        print(f"Parquet directory not found: {parquet_dir}", file=sys.stderr)
        return 2

    if args.overwrite and duckdb_path.exists():
        duckdb_path.unlink()
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    tables = discover_tables(parquet_dir)
    if not tables:
        print(f"No Parquet files found under: {parquet_dir}", file=sys.stderr)
        return 2

    records: list[dict[str, Any]] = []
    con = duckdb.connect(str(duckdb_path))
    try:
        for table_label, files in sorted(tables.items()):
            view_name = f"v_{clean_identifier(table_label)}"
            glob_pattern = str((parquet_dir / "archive=*" / f"table={table_label}" / "*.parquet").as_posix())
            sql = (
                f"create or replace view {view_name} as "
                f"select * from read_parquet('{sql_quote_path(glob_pattern)}', "
                "union_by_name=true, hive_partitioning=true)"
            )
            con.execute(sql)
            row_count = None
            if args.count_rows:
                row_count = con.execute(f"select count(*) from {view_name}").fetchone()[0]
            sample_cols = con.execute(f"describe {view_name}").fetchdf()
            records.append({
                "table": table_label,
                "view_name": view_name,
                "glob_pattern": glob_pattern,
                "n_parquet_files": len(files),
                "row_count": row_count,
                "n_columns": int(len(sample_cols)),
                "status": "created",
                "error": None,
            })
            print(f"created {view_name}: files={len(files)} columns={len(sample_cols)} rows={row_count if row_count is not None else 'not_counted'}")
    except Exception as exc:
        records.append({
            "table": None,
            "view_name": None,
            "glob_pattern": None,
            "n_parquet_files": None,
            "row_count": None,
            "n_columns": None,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise
    finally:
        con.close()

    fields = ["table", "view_name", "glob_pattern", "n_parquet_files", "row_count", "n_columns", "status", "error"]
    write_csv(catalog_root / "duckdb_views.csv", records, fields)
    manifest = {
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - started, 3),
        "parquet_dir": str(parquet_dir),
        "duckdb_path": str(duckdb_path),
        "catalog_dir": str(catalog_root),
        "count_rows": args.count_rows,
        "n_views": sum(1 for r in records if r.get("status") == "created"),
    }
    (catalog_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote DuckDB catalog: {catalog_root / 'duckdb_views.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
