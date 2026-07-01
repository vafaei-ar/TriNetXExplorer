# Running the TriNetXExplorer dashboard v0.1

The first dashboard reads aggregate profile outputs only. It does not open raw TriNetX ZIP exports.

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

## Start dashboard

```bash
source .venv/bin/activate
streamlit run dashboard/app.py
```

In the sidebar, set **Profile output directory or ZIP** to either:

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

## What v0.1 shows

- profiled tables
- manifest row counts
- dataset and cohort metadata
- code-system summaries
- top codes, suppressed and sample-based
- demographics, suppressed and sample-based
- date ranges
- numeric and cost summaries
- privacy rules

## What v0.1 does not do

- It does not display `patient_id`, `encounter_id`, `unique_id`, or `source_id`.
- It does not display raw TriNetX rows.
- It does not download patient-level data.
- It does not query the raw ZIP files interactively.
- It does not produce final epidemiologic estimates.

The profile outputs are sample-based unless the profile script was run with `--full-scan`. Treat dashboard v0.1 as a structural review tool, not as the final analytic interface.
