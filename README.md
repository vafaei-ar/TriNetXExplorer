# TriNetXExplorer

Local tools for inspecting TriNetX export archives and building a secure aggregate dashboard.

## Current status

The repository now has four layers:

1. A conservative ZIP audit script.
2. A safe aggregate profiling script.
3. A dashboard v0.1 that reads only audit/profile outputs.
4. A Parquet conversion scaffold for selected event-level tables.

The dashboard does **not** open raw TriNetX ZIP exports and does **not** display patient-level rows.

## Data location assumed for local runs

```text
~/datasets/trinetx/*.zip
```

Known local files:

```text
~/datasets/trinetx/66350692f55db9228fba3206_20240514_224202103_Control.zip
~/datasets/trinetx/stroke_diamond_network_dataset_64b01b62c6dca15375ae9828.zip
~/datasets/trinetx/stroke_research_network_dataset_68b1a0575a2bf16052a523ef.zip
```

## Set up a virtual environment

Do not install dashboard dependencies into the base environment.

From the repository root:

```bash
bash scripts/setup_venv.sh
source .venv/bin/activate
```

Equivalent manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

The `.venv/` directory is ignored by Git.

## Run the structural audit

Activate the virtual environment first:

```bash
source .venv/bin/activate
```

Then run:

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 5000 \
  --make-zip
```

For a faster structural pass:

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 1000 \
  --skip-row-counts \
  --make-zip
```

## Run the aggregate profile

```bash
python scripts/profile_trinetx_archives.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_profile \
  --max-rows-per-file 250000 \
  --small-cell-threshold 11 \
  --make-zip
```

This writes aggregate profile files only. It does not write raw patient-level rows.

## Run dashboard v0.1

```bash
source .venv/bin/activate
streamlit run dashboard/app.py
```

In the sidebar, point the dashboard to either a generated profile directory or profile ZIP, for example:

```text
outputs/trinetx_profile/20260630_193653.zip
```

## Convert selected tables to Parquet

Start with a dry run:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --dry-run
```

Then run a tiny smoke test:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --tables dataset_details.csv,cohort_details.csv,manifest.csv \
  --max-chunks-per-file 1 \
  --overwrite
```

See `docs/PARQUET_CONVERSION.md` before converting large event tables.

## Why profile before final dashboard

The MarketScan dashboard plan is a useful precedent for security and aggregate-first design. TriNetX exports have different table structure, naming, coding systems, date handling, cohort files, and network-specific schemas. The dashboard must be driven by observed schemas, not guessed assumptions.

Current findings show:

- Control and Diamond exports have cost tables.
- Research Network has an encounter layer and source IDs.
- Clinical event files are too large for direct interactive ZIP queries.
- Dashboard v0.1 should use precomputed aggregate catalogs.
- Parquet conversion should come before larger interactive event-level exploration.

## Safety defaults

- Do not display `patient_id`, `encounter_id`, `unique_id`, or `source_id`.
- Do not show raw TriNetX rows.
- Do not allow patient-level download.
- Apply small-cell suppression, default `n < 11`.
- Treat the app as internal-only.
