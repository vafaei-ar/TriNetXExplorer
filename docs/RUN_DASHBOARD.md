# Running the TriNetXExplorer dashboard v0.1

The dashboard reads aggregate profile outputs and can optionally query local DuckDB views over local Parquet files. It does not open raw TriNetX ZIP exports and does not display raw rows.

## Create and activate a virtual environment

From the repository root:

```bash
bash scripts/setup_venv.sh
source .venv/bin/activate
```

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

The `.venv/` directory is ignored by Git.

## Generate profile outputs

If you have not generated the profile ZIP yet:

```bash
python scripts/profile_trinetx_archives.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_profile \
  --max-rows-per-file 250000 \
  --small-cell-threshold 11 \
  --make-zip
```

The script writes a timestamped output directory and a ZIP under `outputs/trinetx_profile/`.

## Optional: build Parquet and DuckDB layers

The DuckDB aggregate tab and the faculty-facing Research Workspace appear after local Parquet conversion and DuckDB view creation.

For the current core-table layer:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --tables patient.csv,patient_cohort.csv,standardized_terminology.csv \
  --chunksize 250000 \
  --compression snappy \
  --overwrite

python scripts/build_duckdb_views.py \
  --parquet-dir data/trinetx_parquet \
  --duckdb-path data/trinetx.duckdb \
  --catalog-dir outputs/trinetx_duckdb_catalog \
  --count-rows \
  --overwrite
```

## Start dashboard

```bash
source .venv/bin/activate
streamlit run dashboard/app.py
```

Streamlit will show two pages in the left sidebar:

```text
TriNetXExplorer
Research Workspace
```

Use **TriNetXExplorer** for technical profile/audit review.

Use **Research Workspace** for faculty-facing exploration:

- data guide
- what can I study?
- network differences
- concept/code browser
- cohort feasibility placeholder
- example research recipes

In the main TriNetXExplorer page sidebar, set **Profile output directory or ZIP** to either:

```text
outputs/trinetx_profile/YYYYMMDD_HHMMSS
```

or:

```text
outputs/trinetx_profile/YYYYMMDD_HHMMSS.zip
```

Example:

```text
outputs/trinetx_profile/20260630_193653.zip
```

Set **DuckDB database** to:

```text
data/trinetx.duckdb
```

## What v0.1 shows

- profiled tables
- manifest row counts
- dataset and cohort metadata
- code-system summaries
- top codes, suppressed and sample-based
- demographics, suppressed and sample-based
- date ranges
- numeric and cost summaries
- DuckDB aggregate counts over converted Parquet views
- Research Workspace for faculty-facing idea exploration
- privacy rules

## What v0.1 does not do

- It does not display `patient_id`, `encounter_id`, `unique_id`, or `source_id`.
- It does not display raw TriNetX rows.
- It does not download patient-level data.
- It does not query the raw ZIP files interactively.
- It does not produce final epidemiologic estimates.

The profile outputs are sample-based unless the profile script was run with `--full-scan`. DuckDB counts are exact for converted Parquet tables, but they are still aggregate infrastructure checks unless paired with validated concept definitions.
