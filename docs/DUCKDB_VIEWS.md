# DuckDB views over TriNetX Parquet

After converting selected TriNetX tables to Parquet, build DuckDB views over the partitioned Parquet directory.

## Build views

```bash
source .venv/bin/activate

python scripts/build_duckdb_views.py \
  --parquet-dir data/trinetx_parquet \
  --duckdb-path data/trinetx.duckdb \
  --catalog-dir outputs/trinetx_duckdb_catalog \
  --overwrite
```

This creates views such as:

```text
v_cohort_details
v_dataset_details
v_manifest
v_patient
v_diagnosis
v_procedure
```

depending on which Parquet tables exist locally.

## Optional row counts

For small metadata tables, row counts are safe:

```bash
python scripts/build_duckdb_views.py \
  --parquet-dir data/trinetx_parquet \
  --duckdb-path data/trinetx.duckdb \
  --catalog-dir outputs/trinetx_duckdb_catalog \
  --count-rows \
  --overwrite
```

Do not use `--count-rows` casually after converting very large event tables unless you are comfortable with the runtime.

## Open DuckDB shell

```bash
duckdb data/trinetx.duckdb
```

Example SQL:

```sql
show tables;
select * from v_dataset_details;
select archive_short, file, row_count, unique_patient_count from v_manifest order by archive_short, file;
```

## What to send back

Send only the DuckDB catalog ZIP, not the DuckDB database and not Parquet files:

```bash
latest=$(ls -td outputs/trinetx_duckdb_catalog/* | head -1)
zip -r "${latest}.zip" "$latest"
echo "${latest}.zip"
```

The catalog confirms which views were created and how many Parquet files each view covers.
