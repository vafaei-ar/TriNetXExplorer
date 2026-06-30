# TriNetXExplorer

Local tools for inspecting TriNetX export archives and, later, building a secure aggregate dashboard.

## Current status

The repository starts with a conservative audit scaffold. We need to learn the ZIP contents before designing the dashboard. The first script inventories archives, detects CSV-like files, records schemas, counts rows when feasible, and writes aggregate metadata only.

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

## Run the first audit

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "~/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 5000 \
  --make-zip
```

If this is too slow, use a fast structural pass:

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "~/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 1000 \
  --skip-row-counts \
  --make-zip
```

Then send back only the generated ZIP under `outputs/trinetx_audit/`. Do not send raw TriNetX CSV files.

## Why audit before dashboard

The MarketScan dashboard plan is a useful precedent, but TriNetX exports may have different table structure, naming, coding systems, date handling, and cohort files. The dashboard should be driven by observed schemas, not guessed assumptions.

The first dashboard design will use these audit outputs to decide:

- available tables and files
- patient, encounter, diagnosis, procedure, medication, lab, and demographic fields
- date and code fields
- feasible aggregate views
- privacy rules and suppression logic
- whether Streamlit plus DuckDB is sufficient for the first version
