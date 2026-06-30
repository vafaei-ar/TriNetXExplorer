# Running the first TriNetX data audit

Run this from the repository root after pulling the branch.

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "~/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 5000 \
  --make-zip
```

For a faster first test, skip full row counts:

```bash
python scripts/audit_trinetx_archives.py \
  --input-glob "~/datasets/trinetx/*.zip" \
  --output-dir outputs/trinetx_audit \
  --sample-rows 1000 \
  --skip-row-counts \
  --make-zip
```

Send back only the generated audit ZIP from `outputs/`, for example:

```text
outputs/trinetx_audit/YYYYMMDD_HHMMSS.zip
```

Do not send raw TriNetX data files.

## What the audit writes

The script writes aggregate metadata only:

- `archives.csv`: one row per ZIP archive
- `members.csv`: one row per file inside each ZIP
- `schema_catalog.csv`: one row per detected column in CSV-like files
- `manifest.json`: run settings and counts
- `report.md`: human-readable summary

It does not extract the archives and does not write raw patient-level rows.
