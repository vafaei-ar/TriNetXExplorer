"""Streamlit dashboard for aggregate TriNetX profile and DuckDB outputs.

Run:
    streamlit run dashboard/app.py

This page is the technical profile/dashboard view. It uses friendly dataset names
(Control, Stroke Diamond, Stroke Research) and hides raw ZIP/archive filenames by
default. It does not display raw TriNetX rows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import zipfile

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

EXPECTED_PROFILE_FILES = [
    "table_profiles.csv",
    "metadata_tables.csv",
    "code_system_counts.csv",
    "top_codes_suppressed.csv",
    "patient_demographics_suppressed.csv",
    "date_ranges.csv",
    "numeric_summaries.csv",
]

DATASET_LABELS = {
    "control_20240514": "Control",
    "stroke_diamond": "Stroke Diamond",
    "stroke_research": "Stroke Research",
}
DATASET_KEYS = {v: k for k, v in DATASET_LABELS.items()}
ALL_DATASETS = "All datasets"
ALL_TABLES = "All tables"
SMALL_CELL_THRESHOLD_DEFAULT = 11
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

st.set_page_config(page_title="TriNetXExplorer", layout="wide")


def dataset_label(value: str) -> str:
    return DATASET_LABELS.get(str(value), str(value))


def selected_dataset_key(label: str) -> str:
    if label == ALL_DATASETS:
        return "All"
    return DATASET_KEYS[label]


def table_label(value: str) -> str:
    text = str(value)
    return text[:-4] if text.endswith(".csv") else text


def selected_table_name(label: str, mapping: dict[str, str]) -> str:
    if label == ALL_TABLES:
        return "All"
    return mapping[label]


def _read_csv_from_zip(zf: zipfile.ZipFile, name: str) -> pd.DataFrame:
    try:
        with zf.open(name) as fh:
            return pd.read_csv(fh)
    except KeyError:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_profile(path_text: str) -> tuple[dict[str, pd.DataFrame], dict]:
    path = Path(os.path.expanduser(path_text)).resolve()
    data: dict[str, pd.DataFrame] = {}
    manifest: dict = {}

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            for name in EXPECTED_PROFILE_FILES:
                data[name] = _read_csv_from_zip(zf, name)
            if "manifest.json" in zf.namelist():
                with zf.open("manifest.json") as fh:
                    manifest = json.load(fh)
    elif path.is_dir():
        for name in EXPECTED_PROFILE_FILES:
            f = path / name
            data[name] = pd.read_csv(f) if f.exists() else pd.DataFrame()
        m = path / "manifest.json"
        if m.exists():
            manifest = json.loads(m.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(f"Profile catalog not found: {path}")

    return data, manifest


def latest_profile_path(base: str = "outputs/trinetx_profile") -> str:
    base_path = Path(base)
    fixed_zip = base_path / "latest.zip"
    fixed_dir = base_path / "latest"
    if fixed_zip.exists():
        return str(fixed_zip)
    if fixed_dir.exists():
        return str(fixed_dir)
    if not base_path.exists():
        return str(fixed_zip)
    candidates = [p for p in base_path.iterdir() if p.is_dir()]
    zips = [p for p in base_path.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
    all_candidates = [p for p in candidates + zips if p.name != "latest.zip"]
    if not all_candidates:
        return str(fixed_zip)
    return str(max(all_candidates, key=lambda p: p.stat().st_mtime))


def filter_frame(df: pd.DataFrame, dataset_key: str, table: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if dataset_key != "All" and "archive_short" in out.columns:
        out = out[out["archive_short"] == dataset_key]
    if table and table != "All" and "member_path" in out.columns:
        out = out[out["member_path"] == table]
    return out


def display_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "archive_short" in out.columns:
        out.insert(0, "dataset", out["archive_short"].map(dataset_label))
    # Hide long raw ZIP names by default. The stable short key and friendly dataset name are enough.
    hide_cols = [c for c in ["archive_name"] if c in out.columns]
    out = out.drop(columns=hide_cols)
    if "member_path" in out.columns:
        out = out.rename(columns={"member_path": "table"})
        out["table"] = out["table"].map(table_label)
    if "archive_short" in out.columns:
        out = out.drop(columns=["archive_short"])
    return out


def show_dataframe(df: pd.DataFrame, height: int = 380) -> None:
    if df.empty:
        st.info("No rows available for the selected filters.")
    else:
        st.dataframe(display_frame(df), use_container_width=True, height=height)


def metric_int(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{int(float(value)):,}"
    except Exception:
        return str(value)


def available_dataset_labels(data: dict[str, pd.DataFrame]) -> list[str]:
    vals: set[str] = set()
    for df in data.values():
        if not df.empty and "archive_short" in df.columns:
            vals.update(str(x) for x in df["archive_short"].dropna().unique())
    labels = [dataset_label(x) for x in sorted(vals)]
    preferred = ["Control", "Stroke Diamond", "Stroke Research"]
    ordered = [x for x in preferred if x in labels] + [x for x in labels if x not in preferred]
    return [ALL_DATASETS] + ordered


def available_tables(data: dict[str, pd.DataFrame], dataset_key: str) -> tuple[list[str], dict[str, str]]:
    vals: set[str] = set()
    for df in data.values():
        if df.empty or "member_path" not in df.columns:
            continue
        tmp = filter_frame(df, dataset_key)
        vals.update(str(x) for x in tmp["member_path"].dropna().unique())
    mapping = {table_label(x): x for x in sorted(vals)}
    return [ALL_TABLES] + list(mapping.keys()), mapping


def metadata_manifest(metadata: pd.DataFrame) -> pd.DataFrame:
    if metadata.empty or "member_path" not in metadata.columns:
        return pd.DataFrame()
    out = metadata[metadata["member_path"].eq("manifest.csv")].copy()
    wanted = ["archive_short", "file", "row_count", "unique_patient_count", "column_count"]
    wanted = [c for c in wanted if c in out.columns]
    return out[wanted].sort_values([c for c in ["archive_short", "file"] if c in wanted])


def quote_ident(name: str) -> str:
    if not SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f'"{name}"'


@st.cache_data(show_spinner=False)
def duckdb_query(db_path_text: str, sql: str) -> pd.DataFrame:
    db_path = Path(os.path.expanduser(db_path_text)).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB database not found: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def duckdb_views(db_path_text: str) -> pd.DataFrame:
    return duckdb_query(
        db_path_text,
        """
        select table_name as view_name
        from information_schema.tables
        where table_type = 'VIEW'
        order by table_name
        """,
    )


@st.cache_data(show_spinner=False)
def duckdb_columns(db_path_text: str, view_name: str) -> list[str]:
    df = duckdb_query(db_path_text, f"describe {quote_ident(view_name)}")
    return [str(x) for x in df["column_name"].tolist()] if "column_name" in df.columns else []


def view_exists(views: pd.DataFrame, view_name: str) -> bool:
    return not views.empty and view_name in set(views["view_name"].astype(str))


def archive_column(cols: list[str]) -> str | None:
    for c in ["archive", "archive_short", "__archive_short"]:
        if c in cols:
            return c
    return None


def count_by_dataset_sql(view_name: str, cols: list[str], dataset_key: str) -> str:
    qview = quote_ident(view_name)
    acol = archive_column(cols)
    if acol:
        qarchive = quote_ident(acol)
        archive_expr = f"cast({qarchive} as varchar)"
        where = ""
        if dataset_key != "All":
            escaped = dataset_key.replace("'", "''")
            where = f"where {archive_expr} = '{escaped}'"
        return f"""
            select {archive_expr} as archive_short, count(*) as n
            from {qview}
            {where}
            group by 1
            order by archive_short
        """
    return f"select 'all' as archive_short, count(*) as n from {qview}"


def filtered_aggregate_sql(
    view_name: str,
    cols: list[str],
    group_col: str,
    dataset_key: str,
    threshold: int,
    limit: int = 500,
) -> str:
    qview = quote_ident(view_name)
    qgroup = quote_ident(group_col)
    acol = archive_column(cols)
    if acol:
        qarchive = quote_ident(acol)
        archive_expr = f"cast({qarchive} as varchar)"
        where = ""
        if dataset_key != "All":
            escaped = dataset_key.replace("'", "''")
            where = f"where {archive_expr} = '{escaped}'"
        return f"""
            select
              {archive_expr} as archive_short,
              cast({qgroup} as varchar) as value,
              count(*) as n
            from {qview}
            {where}
            group by 1, 2
            having count(*) >= {int(threshold)}
            order by archive_short, n desc
            limit {int(limit)}
        """
    return f"""
        select 'all' as archive_short, cast({qgroup} as varchar) as value, count(*) as n
        from {qview}
        group by 1, 2
        having count(*) >= {int(threshold)}
        order by n desc
        limit {int(limit)}
    """


def duckdb_aggregate_tab(db_path: str, dataset_key: str, threshold: int) -> None:
    st.subheader("Parquet/DuckDB aggregate explorer")
    st.markdown("Queries local DuckDB views over local Parquet files. Aggregate counts only; no raw rows.")

    try:
        views = duckdb_views(db_path)
    except Exception as exc:
        st.info(f"DuckDB is not available yet: {exc}")
        return
    if views.empty:
        st.info("No DuckDB views found. Run `scripts/build_duckdb_views.py` first.")
        return

    views_display = views.copy()
    show_dataframe(views_display, height=220)

    summary_rows: list[pd.DataFrame] = []
    for view_name in views["view_name"].astype(str):
        try:
            cols = duckdb_columns(db_path, view_name)
            counts = duckdb_query(db_path, count_by_dataset_sql(view_name, cols, dataset_key))
            counts.insert(0, "view_name", view_name)
            summary_rows.append(counts)
        except Exception as exc:
            st.warning(f"Could not count {view_name}: {exc}")
    if summary_rows:
        st.write("Aggregate row counts by dataset")
        show_dataframe(pd.concat(summary_rows, ignore_index=True), height=320)

    st.divider()
    st.subheader("Patient aggregates")
    if view_exists(views, "v_patient"):
        patient_cols = duckdb_columns(db_path, "v_patient")
        candidate_fields = [
            c for c in ["sex", "race", "ethnicity", "marital_status", "patient_regional_location", "reason_yob_missing"]
            if c in patient_cols
        ]
        if candidate_fields:
            field = st.selectbox("Patient aggregate field", candidate_fields)
            demo_df = duckdb_query(db_path, filtered_aggregate_sql("v_patient", patient_cols, field, dataset_key, threshold))
            if not demo_df.empty:
                plot_df = display_frame(demo_df)
                fig = px.bar(plot_df, x="value", y="n", color="dataset" if "dataset" in plot_df.columns else None, title=f"Patient counts by {field}")
                st.plotly_chart(fig, use_container_width=True)
            show_dataframe(demo_df, height=420)
        else:
            st.info("`v_patient` exists, but no known demographic aggregate fields were found.")
    else:
        st.info("`v_patient` is not available yet. Convert `patient.csv` and rebuild DuckDB views.")

    st.divider()
    st.subheader("Patient-cohort aggregates")
    if view_exists(views, "v_patient_cohort"):
        cohort_cols = duckdb_columns(db_path, "v_patient_cohort")
        hidden = {"patient_id", "encounter_id", "unique_id", "source_id", "__source_archive", "__source_member", "archive", "table"}
        group_options = [c for c in cohort_cols if c not in hidden and c != archive_column(cohort_cols)]
        if group_options:
            field = st.selectbox("Patient-cohort aggregate field", group_options)
            cohort_df = duckdb_query(db_path, filtered_aggregate_sql("v_patient_cohort", cohort_cols, field, dataset_key, threshold))
            show_dataframe(cohort_df, height=420)
        else:
            counts = duckdb_query(db_path, count_by_dataset_sql("v_patient_cohort", cohort_cols, dataset_key))
            show_dataframe(counts, height=220)
    else:
        st.info("`v_patient_cohort` is not available yet. Convert `patient_cohort.csv` and rebuild DuckDB views.")

    st.divider()
    st.subheader("Terminology aggregates")
    if view_exists(views, "v_standardized_terminology"):
        term_cols = duckdb_columns(db_path, "v_standardized_terminology")
        term_fields = [c for c in ["code_system", "category", "type", "domain", "vocabulary"] if c in term_cols]
        if term_fields:
            field = st.selectbox("Terminology aggregate field", term_fields)
            term_df = duckdb_query(db_path, filtered_aggregate_sql("v_standardized_terminology", term_cols, field, dataset_key, threshold))
            show_dataframe(term_df, height=420)
        else:
            counts = duckdb_query(db_path, count_by_dataset_sql("v_standardized_terminology", term_cols, dataset_key))
            show_dataframe(counts, height=220)
    else:
        st.info("`v_standardized_terminology` is not available yet. Convert `standardized_terminology.csv` and rebuild DuckDB views.")


def main() -> None:
    st.title("TriNetXExplorer")
    st.caption("Aggregate profile and DuckDB dashboard. It uses friendly dataset names and never displays raw patient-level rows.")

    with st.sidebar:
        st.header("Dataset")
        default_profile = latest_profile_path()
        with st.expander("Profile catalog", expanded=False):
            profile_path = st.text_input("Profile catalog path", value=default_profile)
            st.caption("Recommended fixed path: `outputs/trinetx_profile/latest.zip`. Timestamped ZIPs are still supported but should not be shown to most users.")
        with st.expander("DuckDB source", expanded=False):
            duckdb_path = st.text_input("DuckDB database", value="data/trinetx.duckdb")
        small_cell_threshold = st.number_input("Small-cell threshold", min_value=1, max_value=1000, value=SMALL_CELL_THRESHOLD_DEFAULT, step=1)

    try:
        data, manifest = load_profile(profile_path)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    dataset_options = available_dataset_labels(data)
    with st.sidebar:
        dataset_choice = st.selectbox("Dataset", dataset_options)
        dataset_key = selected_dataset_key(dataset_choice)
        table_options, table_mapping = available_tables(data, dataset_key)
        table_choice = st.selectbox("Table", table_options)
        table = selected_table_name(table_choice, table_mapping)

    table_profiles = filter_frame(data.get("table_profiles.csv", pd.DataFrame()), dataset_key, table)
    metadata = filter_frame(data.get("metadata_tables.csv", pd.DataFrame()), dataset_key, table)
    code_systems = filter_frame(data.get("code_system_counts.csv", pd.DataFrame()), dataset_key, table)
    top_codes = filter_frame(data.get("top_codes_suppressed.csv", pd.DataFrame()), dataset_key, table)
    demographics = filter_frame(data.get("patient_demographics_suppressed.csv", pd.DataFrame()), dataset_key, table)
    dates = filter_frame(data.get("date_ranges.csv", pd.DataFrame()), dataset_key, table)
    numeric = filter_frame(data.get("numeric_summaries.csv", pd.DataFrame()), dataset_key, table)

    st.warning(
        "Profile-derived counts are sample-based unless `scan_mode` says full. "
        "DuckDB-derived counts are aggregate queries over locally converted Parquet. No raw rows are displayed."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Selected dataset", dataset_choice)
    c2.metric("Profile scan mode", manifest.get("scan_mode", "-"))
    c3.metric("Rows per file", metric_int(manifest.get("max_rows_per_file")))
    c4.metric("Small-cell threshold", metric_int(small_cell_threshold))

    tabs = st.tabs([
        "Inventory",
        "Dataset and cohorts",
        "Code systems",
        "Top codes",
        "Demographics",
        "Dates",
        "Numeric and cost",
        "DuckDB aggregates",
        "Privacy rules",
    ])

    with tabs[0]:
        st.subheader("Profiled tables")
        show_dataframe(table_profiles)
        manifest_rows = metadata_manifest(filter_frame(data.get("metadata_tables.csv", pd.DataFrame()), dataset_key))
        if not manifest_rows.empty:
            st.subheader("Manifest row counts")
            total_rows = pd.to_numeric(manifest_rows["row_count"], errors="coerce").sum()
            st.metric("Rows across selected dataset/table manifest", metric_int(total_rows))
            show_dataframe(manifest_rows, height=500)

    with tabs[1]:
        st.subheader("Dataset and cohort metadata")
        md = metadata[metadata["member_path"].isin(["dataset_details.csv", "cohort_details.csv"])].copy() if not metadata.empty else pd.DataFrame()
        show_dataframe(md)

    with tabs[2]:
        st.subheader("Code-system counts")
        if not code_systems.empty and {"value_1", "n"}.issubset(code_systems.columns):
            plot_df = code_systems[code_systems["suppressed"].fillna(False).eq(False)].copy()
            plot_df["n"] = pd.to_numeric(plot_df["n"], errors="coerce")
            if not plot_df.empty:
                display_plot = display_frame(plot_df)
                fig = px.bar(display_plot, x="value_1", y="n", color="table" if "table" in display_plot.columns else None, facet_col="dataset" if dataset_key == "All" and "dataset" in display_plot.columns else None, title="Sampled code-system counts")
                st.plotly_chart(fig, use_container_width=True)
        show_dataframe(code_systems)

    with tabs[3]:
        st.subheader("Top codes, suppressed and sample-based")
        if not top_codes.empty:
            systems = ["All"] + sorted(str(x) for x in top_codes.get("value_1", pd.Series(dtype=str)).dropna().unique())
            selected_system = st.selectbox("Code system", systems)
            tc = top_codes.copy()
            if selected_system != "All":
                tc = tc[tc["value_1"].astype(str).eq(selected_system)]
            tc["n"] = pd.to_numeric(tc["n"], errors="coerce")
            show_dataframe(tc.sort_values("n", ascending=False, na_position="last"), height=600)
        else:
            st.info("No top-code rows available.")

    with tabs[4]:
        st.subheader("Patient demographics, suppressed and sample-based")
        if not demographics.empty:
            fields = ["All"] + sorted(str(x) for x in demographics.get("field", pd.Series(dtype=str)).dropna().unique())
            selected_field = st.selectbox("Demographic field", fields)
            dd = demographics.copy()
            if selected_field != "All":
                dd = dd[dd["field"].astype(str).eq(selected_field)]
            dd["n"] = pd.to_numeric(dd["n"], errors="coerce")
            if not dd.empty:
                display_plot = display_frame(dd[dd["suppressed"].fillna(False).eq(False)])
                fig = px.bar(display_plot, x="value_1", y="n", color="field", facet_col="dataset" if dataset_key == "All" and "dataset" in display_plot.columns else None, title="Sampled demographic counts")
                st.plotly_chart(fig, use_container_width=True)
            show_dataframe(dd)
        else:
            st.info("No demographic rows available.")

    with tabs[5]:
        st.subheader("Date ranges, sample-based")
        st.markdown("Date ranges come from the profile sample. Very early minimum dates may reflect deidentified shifts or historical records.")
        show_dataframe(dates)

    with tabs[6]:
        st.subheader("Numeric and cost summaries, sample-based")
        st.markdown("Use cost summaries only for structural review. Negative values likely represent reversals, refunds, or adjustment rows.")
        show_dataframe(numeric)

    with tabs[7]:
        duckdb_aggregate_tab(duckdb_path, dataset_key, int(small_cell_threshold))

    with tabs[8]:
        st.subheader("Default privacy rules")
        st.markdown(
            """
- Use friendly dataset names: Control, Stroke Diamond, Stroke Research.
- Do not display raw ZIP filenames, `patient_id`, `encounter_id`, `unique_id`, or `source_id` in normal user views.
- Do not show raw rows from TriNetX exports, Parquet files, or DuckDB views.
- Do not allow patient-level downloads from the dashboard.
- Apply small-cell suppression, default `n < 11`.
- Treat this dashboard as internal-only.
            """.strip()
        )


if __name__ == "__main__":
    main()
