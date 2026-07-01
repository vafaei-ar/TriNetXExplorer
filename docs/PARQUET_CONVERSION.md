# TriNetX Parquet conversion

This is the next layer after audit/profile/dashboard v0.1.

The goal is to convert selected TriNetX CSV files inside ZIP exports into partitioned Parquet so DuckDB and the dashboard can query them efficiently.

## Safety model

The converter:

- streams CSV-like files directly from ZIP archives
- processes one chunk at a time
- does not extract full CSV files to disk
- writes partitioned Parquet under `data/trinetx_parquet/`
- writes a conversion catalog under `outputs/trinetx_parquet_catalog/`
- preserves TriNetX column names
- adds source-trace columns: `__archive_short`, `__source_archive`, `__source_member`

The converter does not apply privacy suppression. Parquet files are still event-level data. Keep them in secure local storage. Do not expose them through the dashboard as raw rows.

## Install dependencies

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Dry run

First verify which files would be converted:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --dry-run
```

## Tiny smoke test

Convert only the first chunk of low-risk metadata tables:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --tables dataset_details.csv,cohort_details.csv,manifest.csv \
  --max-chunks-per-file 1 \
  --overwrite
```

Review the generated catalog:

```bash
ls outputs/trinetx_parquet_catalog
cat outputs/trinetx_parquet_catalog/*/conversion_catalog.csv | head
```

## First real conversion

Start with metadata, patient, terminology, diagnosis, and procedure. This may still take time because diagnosis and procedure are large.

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --tables patient.csv,patient_cohort.csv,cohort_details.csv,dataset_details.csv,manifest.csv,standardized_terminology.csv,diagnosis.csv,procedure.csv \
  --chunksize 250000 \
  --compression snappy \
  --overwrite
```

## Convert one archive only

For safer stepwise testing:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --archives stroke_research \
  --tables patient.csv,patient_cohort.csv,cohort_details.csv,dataset_details.csv,manifest.csv,standardized_terminology.csv \
  --chunksize 250000 \
  --compression snappy \
  --overwrite
```

Allowed archive labels:

```text
control_20240514
stroke_diamond
stroke_research
```

## Expected output layout

```text
data/trinetx_parquet/
  archive=control_20240514/table=patient/part-00000.parquet
  archive=control_20240514/table=diagnosis/part-00000.parquet
  archive=stroke_diamond/table=patient/part-00000.parquet
  archive=stroke_research/table=diagnosis/part-00000.parquet
```

## What to send back

Send only the conversion catalog, not Parquet files and not raw TriNetX ZIPs.

Useful command:

```bash
latest=$(ls -td outputs/trinetx_parquet_catalog/* | head -1)
zip -r "${latest}.zip" "$latest"
echo "${latest}.zip"
```

Send the generated ZIP.

## Next step after conversion

After the first Parquet conversion succeeds, the next script should build DuckDB views over:

```text
data/trinetx_parquet/archive=*/table=*/*.parquet
```

Then the dashboard can move from profile-only pages to Parquet-backed aggregate query pages.
