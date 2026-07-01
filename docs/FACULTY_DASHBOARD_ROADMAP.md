# Faculty-facing TriNetXExplorer dashboard roadmap

This roadmap translates the dashboard review into implementation steps.

## Product goal

TriNetXExplorer should help faculty and researchers quickly answer:

- What TriNetX data do we have?
- What can I study with it?
- Which networks support my idea?
- Which tables/codes are needed?
- How many patients might be available?
- What are the limitations before I write a proposal or analysis plan?

The dashboard must remain aggregate-only. It should never display raw patient rows or identifiers.

## Current state

The current system has a strong data-engineering foundation:

```text
TriNetX ZIP -> audit/profile -> Parquet -> DuckDB -> dashboard
```

Validated so far:

- Metadata tables converted to Parquet successfully.
- Core tables converted to Parquet successfully: `patient`, `patient_cohort`, `standardized_terminology`.
- DuckDB views created successfully: `v_patient`, `v_patient_cohort`, `v_standardized_terminology`, `v_manifest`, `v_dataset_details`, `v_cohort_details`.
- Dashboard can show profile-derived structural summaries and DuckDB-derived aggregate counts.

## Main usability gaps

The current dashboard is still mostly an infrastructure dashboard. Faculty users need a research-facing dashboard.

Major gaps:

1. Landing page starts with technical table inventory rather than a data guide.
2. No simple “what can I study?” page.
3. No concept/code search workflow.
4. No cohort feasibility page.
5. Network differences are not prominent enough.
6. No example research recipes.
7. No exportable aggregate feasibility report yet.

## Implementation plan

### Phase 1: Researcher-facing wrapper around current data

Status: in progress.

Add dashboard tabs/pages for:

- Data guide / landing page
- What can I study?
- Network differences
- Concept browser
- Feasibility explorer placeholder
- Example research recipes

These features can use the already converted `patient`, `patient_cohort`, and `standardized_terminology` tables.

### Phase 2: Diagnosis-backed feasibility

Next conversion target:

```text
diagnosis.csv
```

Recommended approach:

Convert archive-by-archive rather than all archives at once:

```bash
python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --archives stroke_research \
  --tables diagnosis.csv \
  --chunksize 250000 \
  --compression snappy \
  --overwrite
```

After diagnosis conversion:

- rebuild DuckDB views
- add diagnosis code prefix query
- add distinct patient counts by archive
- add date/year summaries if date fields exist
- add feasibility report output

Initial concepts:

- ischemic stroke: ICD-10-CM `I63`, `I65`, `I66`; ICD-9-CM `433`, `434`
- TIA: ICD-10-CM `G45`; ICD-9-CM `435`
- hemorrhagic stroke: ICD-10-CM `I60`, `I61`, `I62`; ICD-9-CM `430`, `431`, `432`
- atrial fibrillation/flutter: ICD-10-CM `I48`; ICD-9-CM `427.31`, `427.32`
- hypertension
- diabetes

### Phase 3: Procedure-backed acute stroke treatment

Convert:

```text
procedure.csv
```

Add:

- thrombolysis/thrombectomy concept search
- procedure count by archive and date
- acute stroke treatment feasibility recipe

### Phase 4: Medication-backed exposure research

Convert:

```text
medication_ingredient.csv
medication_drug.csv
```

Add:

- anticoagulant concept explorer
- antiplatelet concept explorer
- statin concept explorer
- medication availability by archive

### Phase 5: Lab/vitals/cost/encounter modules

Convert only as needed:

```text
lab_result.csv
vitals_signs.csv
encounter.csv
cost_medical.csv
cost_pharmacy.csv
```

Add modules:

- lab availability and LOINC search
- BP/vitals feasibility
- utilization and encounter counts for Research Network
- cost summaries for Control/Diamond

## Faculty-facing design principles

1. Start with research questions, not files.
2. Show what is available now versus what requires conversion.
3. Separate networks clearly: Control/Diamond and Research Network are not interchangeable.
4. Every count shown to users should be aggregate and small-cell suppressed.
5. Every concept definition should be labeled as preliminary until clinically validated.
6. Every dashboard output should state whether it is sample-based, manifest-based, or DuckDB exact over converted Parquet.

## Minimum useful faculty version

The dashboard becomes broadly useful when a researcher can:

1. Search a concept such as “ischemic stroke” or “AFib.”
2. See candidate code systems/codes.
3. Get aggregate patient counts by archive.
4. See available years/date range.
5. See table requirements and limitations.
6. Export a small aggregate feasibility report.

That should be the near-term target.
