# TriNetX profile findings, 2026-06-30

Source profile ZIP: `20260630_193653.zip`.

## Run status

The second profiling pass completed successfully.

- Scan mode: sample
- Maximum rows scanned per selected file: 250,000
- Small-cell threshold: 11
- Runtime: 307 seconds
- Output files: `table_profiles.csv`, `metadata_tables.csv`, `code_system_counts.csv`, `top_codes_suppressed.csv`, `patient_demographics_suppressed.csv`, `date_ranges.csv`, `numeric_summaries.csv`, `manifest.json`

The profile output is safe to use for dashboard v0.1 because it contains aggregate metadata only. It does not contain raw TriNetX rows or patient-level IDs.

## Dataset and cohort metadata

| Archive | Network | Date created | HCOs | Unique patients | Cohort name |
|---|---|---:|---:|---:|---|
| `control_20240514` | Diamond Network | 20240514 | 92 | 8,000,003 | Control |
| `stroke_diamond` | Diamond Network | 20230801 | 92 | 4,285,214 | Diamond Data |
| `stroke_research` | Research | 20250829 | 107 | 3,301,153 | Research-Stroke-ICDs |

## Manifest-level table sizes

The manifest confirms that the exports are extremely large and must not be queried from ZIP files in the dashboard.

| Archive | Largest tables |
|---|---|
| `control_20240514` | diagnosis 738.8M, procedure 689.3M, cost_medical 629.5M, medication_ingredient 576.7M, medication_drug 389.0M |
| `stroke_diamond` | diagnosis 1.43B, cost_medical 1.22B, procedure 1.17B, medication_ingredient 700.6M, medication_drug 502.4M |
| `stroke_research` | medication_ingredient 3.49B, lab_result 3.28B, vitals_signs 1.62B, diagnosis 1.38B, medication_drug 1.27B |

Research Network also includes `encounter.csv` with 557.7M rows and 3.30M unique patients.

## Code-system findings

Clinical event tables use standard code systems, but the mix differs by archive.

Common findings:

- Diagnosis uses ICD-10-CM and ICD-9-CM.
- Procedure uses CPT, HCPCS, ICD-10-PCS, and in Research Network also SNOMED, CVX, VA, and RxNorm_drug.
- Medication ingredient uses RxNorm.
- Medication drug uses NDC in Control/Diamond, but Research Network uses mostly RxNorm_drug plus NDC.
- Lab and vitals use LOINC, with some TNX lab codes in Control/Diamond.
- Standardized terminology includes ATC, CPT, CVX, Encounter Type, HCPCS, and HGVS in the first sampled block.

## Date-range findings

The sampled date ranges show two different time horizons:

| Archive | Approximate sampled clinical date range |
|---|---|
| `control_20240514` | mostly through 2020-04 |
| `stroke_diamond` | mostly through 2020-04 |
| `stroke_research` | through 2025-08 |

This matters. Do not compare Research Network and Diamond/Control as if they cover the same observation window.

Some early dates are implausibly old for modern clinical events. These may reflect shifted dates, historical records, data quality issues, or export-specific deidentification. The dashboard should show date ranges but warn users not to interpret them as final without validation.

## Demographic-profile findings

The sampled `patient.csv` rows confirm usable demographic fields:

- sex
- race
- ethnicity
- marital_status
- reason_yob_missing
- patient_regional_location only in Research Network

Control and Diamond have marital status as Unknown in the sampled rows. Research Network has Single, Married, and Unknown.

Research Network has regional location categories, including Ex-US and US Census-style regions. Control/Diamond have postal-code structure in the schema, but the profile dashboard should not expose postal codes by default.

## Cost-profile findings

Only Control and Diamond have cost tables.

The sampled cost fields include:

- charge_amount
- allowed_amount
- payer_amount
- patient_amount
- coupon_value
- quantity_dispensed
- days_supply
- refills_authorized
- fill_number

Negative cost values appear in medical and pharmacy cost fields. These likely represent adjustments, reversals, refunds, or data-specific accounting rows. The dashboard should not hide them, but should label cost summaries as exploratory until validated.

## Script issues found from this profile output

The first version of `profile_trinetx_archives.py` worked, but two fixes were needed:

1. `top_codes_suppressed.csv` was not sorted by descending count before applying `top_n`.
2. Fields such as `age_at_death`, `death_date_source_id`, and `*_derived_by_TriNetX` were incorrectly treated as date-like.

The script has been updated to fix both problems.

## Dashboard implication

We now have enough to build dashboard v0.1.

The correct v0.1 should read the audit/profile outputs and provide:

- inventory
- dataset/cohort overview
- code-system summaries
- top-code review
- demographics
- date ranges
- cost/numeric summaries
- privacy-rule display

It should not yet query raw TriNetX ZIP files. The next real data-engineering step is CSV-to-Parquet conversion for selected tables.
