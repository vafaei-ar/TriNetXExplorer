# TriNetX audit findings, 2026-06-30

Source audit ZIP: `20260630_160045.zip`.

## Executive finding

The TriNetX exports are not MarketScan-like claims tables. They are TriNetX table exports organized around patients, clinical events, terminology, cohorts, and, for two archives, cost tables. The dashboard therefore needs a TriNetX-specific data model. Do not copy the MarketScan dashboard structure directly.

The first dashboard should be source-aware because the three archives are not identical.

## Audit run

The audit scanned 3 ZIP archives, 62 ZIP members, and 446 detected columns. It completed full row counts with `sample_rows=5000` and `skip_row_counts=false`.

Elapsed time was about 12,182 seconds, or 3.38 hours. That is already a useful warning: repeated full scans of the ZIP exports will be too slow for an interactive dashboard.

## Archive-level inventory

| Archive label | ZIP size, GiB | Uncompressed CSV/text size, GiB | CSV-like files | Total rows across parsed files |
|---|---:|---:|---:|---:|
| `control_20240514` | 21.61 | 241.70 | 20 | 3,623,152,391 |
| `stroke_diamond` | 30.42 | 370.73 | 20 | 5,722,574,551 |
| `stroke_research` | 66.09 | 976.01 | 19 | 12,595,330,959 |

Total compressed size is about 118 GiB. Total uncompressed CSV/text size is about 1.59 TiB. Total row count across parsed files is about 21.94 billion rows. These totals include event-level rows and metadata rows, not unique patients.

## Core tables detected

Common table names across the exports include:

- `patient.csv`
- `patient_cohort.csv`
- `cohort_details.csv`
- `dataset_details.csv`
- `diagnosis.csv`
- `procedure.csv`
- `medication_ingredient.csv`
- `medication_drug.csv`
- `lab_result.csv`
- `vitals_signs.csv`
- `genomic.csv`
- `tumor.csv`
- `tumor_properties.csv`
- `oncology_treatment.csv`
- `chemo_lines.csv`
- `standardized_terminology.csv`
- `manifest.csv`

Tables detected only in Control/Diamond:

- `cost_medical.csv`
- `cost_pharmacy.csv`

Tables/documents detected only in Research Network:

- `encounter.csv`
- `datadictionary.xlsx`
- `datadictionary.pdf`
- `FAQ.pdf`

## Major row counts by archive

### `control_20240514`

| Table | Rows | Columns |
|---|---:|---:|
| `patient.csv` | 8,000,003 | 9 |
| `diagnosis.csv` | 738,753,874 | 8 |
| `procedure.csv` | 689,287,034 | 6 |
| `medication_ingredient.csv` | 576,749,027 | 9 |
| `medication_drug.csv` | 389,036,008 | 11 |
| `lab_result.csv` | 71,779,343 | 8 |
| `vitals_signs.csv` | 155,763,960 | 8 |
| `cost_medical.csv` | 629,526,202 | 12 |
| `cost_pharmacy.csv` | 352,695,742 | 15 |
| `patient_cohort.csv` | 8,000,003 | 3 |
| `standardized_terminology.csv` | 2,221,132 | 5 |

### `stroke_diamond`

| Table | Rows | Columns |
|---|---:|---:|
| `patient.csv` | 4,285,214 | 9 |
| `diagnosis.csv` | 1,425,659,024 | 8 |
| `procedure.csv` | 1,166,493,611 | 6 |
| `medication_ingredient.csv` | 700,554,296 | 9 |
| `medication_drug.csv` | 502,422,665 | 11 |
| `lab_result.csv` | 85,961,406 | 8 |
| `vitals_signs.csv` | 174,771,325 | 8 |
| `cost_medical.csv` | 1,220,429,269 | 12 |
| `cost_pharmacy.csv` | 434,669,265 | 15 |
| `patient_cohort.csv` | 4,285,214 | 3 |
| `standardized_terminology.csv` | 1,641,119 | 5 |

### `stroke_research`

| Table | Rows | Columns |
|---|---:|---:|
| `patient.csv` | 3,301,153 | 11 |
| `encounter.csv` | 557,665,953 | 9 |
| `diagnosis.csv` | 1,376,280,235 | 10 |
| `procedure.csv` | 993,025,015 | 8 |
| `medication_ingredient.csv` | 3,487,321,565 | 11 |
| `medication_drug.csv` | 1,269,907,327 | 13 |
| `lab_result.csv` | 3,279,520,421 | 10 |
| `vitals_signs.csv` | 1,619,036,985 | 10 |
| `patient_cohort.csv` | 3,301,153 | 4 |
| `standardized_terminology.csv` | 2,315,206 | 5 |

## Schema differences that matter

Research Network has an encounter layer. `encounter_id` appears in `diagnosis.csv`, `procedure.csv`, `medication_ingredient.csv`, `medication_drug.csv`, `lab_result.csv`, `vitals_signs.csv`, and `encounter.csv`. Control and Diamond do not have `encounter_id` in these files.

Research Network has `source_id` in most clinical/event files and in `patient.csv`. Control and Diamond do not. This implies multi-source or site-level origin information exists in Research Network, but the dashboard should not expose raw source identifiers by default.

The patient table differs. Control/Diamond include `age_at_death` and `postal_code`. Research Network includes `month_year_death`, `death_date_source_id`, `patient_regional_location`, and `source_id`, but not `postal_code` or `age_at_death`.

Control/Diamond include `cost_medical.csv` and `cost_pharmacy.csv`. Research Network does not. Therefore cost pages must be conditional.

Research Network includes data dictionary and FAQ documents. These were detected but not parsed in the first audit.

## Immediate dashboard implications

1. Do not build a single fixed schema. Build a source-aware registry with optional columns.
2. Use the common columns for cross-archive comparison.
3. Use Research-only pages for encounter-level analyses.
4. Use Control/Diamond-only pages for cost analyses.
5. Do not query the ZIP files interactively. Convert to Parquet or create precomputed aggregate catalogs first.
6. Keep the dashboard aggregate-only at v0.1. Do not expose `patient_id`, `encounter_id`, `unique_id`, or `source_id` values in the UI.
7. Use `standardized_terminology.csv` as the terminology lookup backbone.

## What the first audit did not answer

The first audit did not extract actual code-system distributions, date ranges, common codes, demographic distributions, cohort labels, or data dictionary contents. It also did not parse the Research Network `datadictionary.xlsx`, `datadictionary.pdf`, or `FAQ.pdf`.

A second, safe profiling pass should compute:

- cohort labels and cohort sizes from `cohort_details.csv`
- dataset metadata from `dataset_details.csv`
- manifest row counts and unique patient counts from `manifest.csv`
- date ranges by table
- code-system frequencies
- top diagnosis/procedure/medication/lab/vital codes after small-cell suppression
- demographic distributions after small-cell suppression
- distinct source count for Research Network, without exposing raw source IDs by default

## Bottom line

We have enough information to design the dashboard architecture. We do not yet have enough content-level profiling to design the final pages. The correct next step is a safe profiling pass plus a dashboard scaffold that reads precomputed catalogs, not raw ZIP files.
