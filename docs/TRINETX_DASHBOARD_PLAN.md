# TriNetXExplorer dashboard plan

This plan is based on the 2026-06-30 audit outputs. It should replace any MarketScan-specific assumptions.

## Design principle

TriNetXExplorer should be a secure aggregate exploration dashboard for TriNetX exports. It should not be a raw patient-level browser.

The dashboard must be source-aware because the three archives have different schemas:

- Control and Diamond have cost tables but no encounter table.
- Research Network has encounter IDs and source IDs but no cost tables.
- Patient geography and death variables differ by archive.

## Recommended stack

Use the same first-version stack as the MarketScan plan, but with a TriNetX-specific backend:

```text
Streamlit + DuckDB + Parquet + YAML/JSON data registry
```

Do not run dashboard queries directly against the ZIP files. The audit run took more than 3 hours only to count rows and sample headers. Interactive dashboard queries must use either Parquet files or precomputed aggregate catalogs.

## Required data layer before dashboard v0.1

### Stage A. Audit catalogs

Already started. Keep these outputs:

- `archives.csv`
- `members.csv`
- `schema_catalog.csv`
- `manifest.json`
- `report.md`

Use them as the initial dashboard inventory.

### Stage B. Safe content profiles

Add a second profiling pass that writes aggregate metadata only:

- `dataset_details_profile.csv`
- `cohort_details_profile.csv`
- `manifest_profile.csv`
- `date_ranges.csv`
- `code_system_counts.csv`
- `top_codes_suppressed.csv`
- `patient_demographics_suppressed.csv`
- `source_summary.csv` for Research Network, without raw source labels by default

This stage should not write raw rows. It should suppress small cells.

### Stage C. Parquet conversion

Convert selected CSV files from ZIP to partitioned Parquet before using the dashboard for real analyses.

Recommended target layout:

```text
data/trinetx_parquet/
  archive=control_20240514/table=patient/*.parquet
  archive=control_20240514/table=diagnosis/*.parquet
  archive=stroke_diamond/table=patient/*.parquet
  archive=stroke_diamond/table=diagnosis/*.parquet
  archive=stroke_research/table=encounter/*.parquet
  archive=stroke_research/table=diagnosis/*.parquet
```

Do not try to load everything into memory. Convert one ZIP member at a time and write row groups/chunks.

## Dashboard v0.1 pages

### 1. Data Inventory

Purpose: show what exists and what is usable.

Inputs:

- archive selector
- table selector

Outputs:

- archive size
- uncompressed size
- table list
- row counts
- column counts
- schema differences
- files unavailable or not parsed
- Research-only and Control/Diamond-only flags

### 2. Dataset and Cohort Overview

Purpose: show the TriNetX export-level cohort context.

Inputs:

- archive selector

Outputs:

- network name
- date created
- total unique patients
- HCO count if available
- cohort names
- cohort numbers
- total patient records

Use `dataset_details.csv`, `cohort_details.csv`, `manifest.csv`, and `patient_cohort.csv`.

### 3. Schema Explorer

Purpose: let users inspect schemas without touching raw data.

Outputs:

- table columns
- inferred roles: identifier-like, code-like, date-like, demographic-like, measure-like
- optional column flags by archive
- Research-specific `encounter_id`/`source_id` fields
- Control/Diamond cost fields

### 4. Terminology Lookup

Purpose: code search and concept review.

Use `standardized_terminology.csv`.

Inputs:

- code system
- code prefix
- description search
- table context if known

Outputs:

- code
- code system
- code description
- path
- unit

Do not join terminology searches to patient-level data in v0.1. Use precomputed code frequencies only.

### 5. Clinical Event Explorer

Purpose: aggregate event trends and code-system summaries.

Tables:

- `diagnosis.csv`
- `procedure.csv`
- `medication_ingredient.csv`
- `medication_drug.csv`
- `lab_result.csv`
- `vitals_signs.csv`

Outputs:

- row counts by table
- date ranges
- code-system counts
- top codes after suppression
- derived-by-TriNetX distributions if safe

### 6. Demographics Explorer

Purpose: describe the exported cohorts.

Tables:

- `patient.csv`
- `patient_cohort.csv`

Outputs:

- sex distribution
- race distribution
- ethnicity distribution
- marital status distribution
- year-of-birth bands, not exact dates
- death availability indicators, not patient-level death dates
- geographic summaries only after review, because Control/Diamond have postal code and Research has patient regional location

### 7. Encounter Explorer, Research Network only

Purpose: use `encounter.csv` and encounter-linked clinical event tables.

Outputs:

- encounter counts
- date ranges
- encounter type distribution
- patient-per-encounter summaries only as aggregate distributions

Do not show raw `encounter_id`.

### 8. Cost Explorer, Control/Diamond only

Purpose: inspect cost availability.

Tables:

- `cost_medical.csv`
- `cost_pharmacy.csv`

Outputs:

- claim type/status summaries
- payer type summaries
- allowed/charge/payer/patient amount distributions
- pharmacy days supply and quantity summaries

Suppress small cells. Consider winsorized or binned summaries for dollar amounts.

### 9. Data Quality

Purpose: detect structural problems before research use.

Checks:

- schema drift by archive
- missing optional columns
- zero-row tables
- date-range anomalies
- high missingness variables
- row count mismatches against `manifest.csv`
- duplicate terminology rows
- unexpected code systems

## Security rules

Default rules:

- Do not display `patient_id`.
- Do not display `encounter_id`.
- Do not display `unique_id`.
- Do not display raw `source_id` values.
- Do not show raw rows.
- Do not allow patient-level download.
- Apply small-cell suppression, default `n < 11`.
- Keep the app internal-only.
- Keep real paths, raw data, and local outputs outside Git.

## Dashboard architecture

Suggested repository layout:

```text
TriNetXExplorer/
  scripts/
    audit_trinetx_archives.py
    profile_trinetx_archives.py
    convert_trinetx_zip_to_parquet.py
    build_dashboard_catalog.py
  dashboard/
    app.py
    config.py
    safety.py
    data_catalog.py
    duckdb_client.py
    pages/
      01_Data_Inventory.py
      02_Dataset_Cohort_Overview.py
      03_Schema_Explorer.py
      04_Terminology_Lookup.py
      05_Clinical_Event_Explorer.py
      06_Demographics_Explorer.py
      07_Encounter_Explorer.py
      08_Cost_Explorer.py
      09_Data_Quality.py
    config/
      dashboard_settings.yaml
      data_sources.yaml
      table_registry.yaml
      users.example.yaml
  docs/
    TRINETX_AUDIT_FINDINGS_20260630.md
    TRINETX_DASHBOARD_PLAN.md
    RUN_AUDIT.md
```

## Near-term implementation sequence

1. Merge the audit scaffold.
2. Add safe profiling script.
3. Run the profiling script on the three local ZIP files.
4. Review profiles and parse Research Network data dictionary files.
5. Build a dashboard v0.1 that reads audit/profile outputs only.
6. Add Parquet conversion.
7. Connect dashboard pages to Parquet for larger aggregate queries.
8. Add concept/cohort modules later.

## Hard recommendation

Do not start with a full cohort builder. That would be premature. The data are too large and the schemas differ too much. Build inventory, schema, terminology, profile, and quality pages first. Then add cohort logic after the Parquet layer and content profiles are stable.
