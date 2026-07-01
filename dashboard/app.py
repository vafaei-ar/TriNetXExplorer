"""Streamlit dashboard for aggregate TriNetX profile and DuckDB outputs.

Run:
    streamlit run dashboard/app.py

The dashboard reads aggregate profile outputs and, optionally, aggregate queries
from a local DuckDB database built over local Parquet files. It is not a raw
TriNetX data browser.
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

SMALL_CELL_THRESHOLD_DEFAULT = 11
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


st.set_page_config(
    page_title="TriNetXExplorer",
    page_icon="TNX",
    layout="wide",
)


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
        raise FileNotFoundError(f"Profile path not found: {path}")

    return data, manifest


def latest_profile_path(base: str = "outputs/trinetx_profile") -> str:
    base_path = Path(base)
    if not base_path.exists():
        return base
    candidates = [p for p in base_path.iterdir() if p.is_dir()]
    zips = [p for p in base_path.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
    all_candidates = candidates + zips
    if not all_candidates:
        return base
    return str(max(all_candidates, key=lambda p: p.stat().st_mtime))


def filter_frame(df: pd.DataFrame, archive: str, table: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if archive != "All" and "archive_short" in out.columns:
        out = out[out["archive_short"] == archive]
    if table and table != "All" and "member_path" in out.columns:
        out = out[out["member_path"] == table]
    return out


def show_dataframe(df: pd.DataFrame, height: int = 380) -> None:
    if df.empty:
        st.info("No rows available for the selected filters.")
    else:
        st.dataframe(df, use_container_width=True, height=height)


def metric_int(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{int(float(value)):,}"
    except Exception:
        return str(value)


def available_archives(data: dict[str, pd.DataFrame]) -> list[str]:
    vals: set[str] = set()
    for df in data.values():
        if not df.empty and "archive_short" in df.columns:
            vals.update(str(x) for x in df["archive_short"].dropna().unique())
    return ["All"] + sorted(vals)


def available_tables(data: dict[str, pd.DataFrame], archive: str) -> list[str]:
    vals: set[str] = set()
    for df in data.values():
        if df.empty or "member_path" not in df.columns:
            continue
        tmp = filter_frame(df, archive)
        vals.update(str(x) for x in tmp["member_path"].dropna().unique())
    return ["All"] + sorted(vals)


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
    qview = quote_ident(view_name)
    df = duckdb_query(db_path_text, f"describe {qview}")
    if "column_name" not in df.columns:
        return []
    return [str(x) for x in df["column_name"].tolist()]


def view_exists(views: pd.DataFrame, view_name: str) -> bool:
    return not views.empty and view_name in set(views["view_name"].astype(str))


def archive_column(cols: list[str]) -> str | None:
    for c in ["archive", "archive_short", "__archive_short"]:
        if c in cols:
            return c
    return None


def filtered_aggregate_sql(
    view_name: str,
    cols: list[str],
    group_col: str,
    selected_archive: str,
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
        if selected_archive != "All":
            escaped = selected_archive.replace("'", "''")
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
        select
          'all' as archive_short,
          cast({qgroup} as varchar) as value,
          count(*) as n
        from {qview}
        group by 1, 2
        having count(*) >= {int(threshold)}
        order by n desc
        limit {int(limit)}
    """


def count_by_archive_sql(view_name: str, cols: list[str], selected_archive: str) -> str:
    qview = quote_ident(view_name)
    acol = archive_column(cols)
    if acol:
        qarchive = quote_ident(acol)
        archive_expr = f"cast({qarchive} as varchar)"
        where = ""
        if selected_archive != "All":
            escaped = selected_archive.replace("'", "''")
            where = f"where {archive_expr} = '{escaped}'"
        return f"""
            select {archive_expr} as archive_short, count(*) as n
            from {qview}
            {where}
            group by 1
            order by archive_short
        """
    return f"select 'all' as archive_short, count(*) as n from {qview}"


def duckdb_aggregate_tab(db_path: str, selected_archive: str, threshold: int) -> None:
    st.subheader("Parquet/DuckDB aggregate explorer")
    st.markdown(
        "This tab queries local DuckDB views over local Parquet files. It shows aggregate counts only; it does not show raw rows."
    )

    try:
        views = duckdb_views(db_path)
    except Exception as exc:
        st.info(f"DuckDB is not available yet: {exc}")
        return

    if views.empty:
        st.info("No DuckDB views found. Run `scripts/build_duckdb_views.py` first.")
        return

    st.write("Available views")
    show_dataframe(views, height=220)

    summary_rows: list[pd.DataFrame] = []
    for view_name in views["view_name"].astype(str):
        try:
            cols = duckdb_columns(db_path, view_name)
            counts = duckdb_query(db_path, count_by_archive_sql(view_name, cols, selected_archive))
            counts.insert(0, "view_name", view_name)
            summary_rows.append(counts)
        except Exception as exc:
            st.warning(f"Could not count {view_name}: {exc}")
    if summary_rows:
        st.write("Aggregate row counts by archive")
        row_counts = pd.concat(summary_rows, ignore_index=True)
        show_dataframe(row_counts, height=320)

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
            demo_df = duckdb_query(
                db_path,
                filtered_aggregate_sql("v_patient", patient_cols, field, selected_archive, threshold),
            )
            if not demo_df.empty:
                fig = px.bar(
                    demo_df,
                    x="value",
                    y="n",
                    color="archive_short",
                    title=f"Patient counts by {field}",
                )
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
        visible_cols = [c for c in cohort_cols if c not in {"patient_id", "encounter_id", "unique_id", "source_id"}]
        group_options = [c for c in visible_cols if c not in {"__source_archive", "__source_member", "archive", "table"}]
        group_options = [c for c in group_options if c != archive_column(cohort_cols)]
        if group_options:
            field = st.selectbox("Patient-cohort aggregate field", group_options)
            cohort_df = duckdb_query(
                db_path,
                filtered_aggregate_sql("v_patient_cohort", cohort_cols, field, selected_archive, threshold),
            )
            show_dataframe(cohort_df, height=420)
        else:
            counts = duckdb_query(db_path, count_by_archive_sql("v_patient_cohort", cohort_cols, selected_archive))
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
            term_df = duckdb_query(
                db_path,
                filtered_aggregate_sql("v_standardized_terminology", term_cols, field, selected_archive, threshold),
            )
            show_dataframe(term_df, height=420)
        else:
            counts = duckdb_query(db_path, count_by_archive_sql("v_standardized_terminology", term_cols, selected_archive))
            show_dataframe(counts, height=220)
    else:
        st.info("`v_standardized_terminology` is not available yet. Convert `standardized_terminology.csv` and rebuild DuckDB views.")


def main() -> None:
    st.title("TriNetXExplorer")
    st.caption("Aggregate profile and DuckDB dashboard. It does not open raw TriNetX exports or display patient-level rows.")

    with st.sidebar:
        st.header("Profile source")
        default_path = latest_profile_path()
        profile_path = st.text_input("Profile output directory or ZIP", value=default_path)
        st.markdown(
            "Run `scripts/profile_trinetx_archives.py` first. "
            "Point this dashboard to the generated output directory or ZIP."
        )
        st.header("DuckDB source")
        duckdb_path = st.text_input("DuckDB database", value="data/trinetx.duckdb")
        small_cell_threshold = st.number_input(
            "Small-cell threshold",
            min_value=1,
            max_value=1000,
            value=SMALL_CELL_THRESHOLD_DEFAULT,
            step=1,
        )

    try:
        data, manifest = load_profile(profile_path)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    archives = available_archives(data)
    with st.sidebar:
        archive = st.selectbox("Archive", archives)
        tables = available_tables(data, archive)
        table = st.selectbox("Profile table", tables)

    table_profiles = filter_frame(data.get("table_profiles.csv", pd.DataFrame()), archive, table)
    metadata = filter_frame(data.get("metadata_tables.csv", pd.DataFrame()), archive, table)
    code_systems = filter_frame(data.get("code_system_counts.csv", pd.DataFrame()), archive, table)
    top_codes = filter_frame(data.get("top_codes_suppressed.csv", pd.DataFrame()), archive, table)
    demographics = filter_frame(data.get("patient_demographics_suppressed.csv", pd.DataFrame()), archive, table)
    dates = filter_frame(data.get("date_ranges.csv", pd.DataFrame()), archive, table)
    numeric = filter_frame(data.get("numeric_summaries.csv", pd.DataFrame()), archive, table)

    st.warning(
        "Profile-derived counts are sample-based unless `scan_mode` says full. "
        "DuckDB-derived counts are aggregate queries over locally converted Parquet. "
        "Neither should expose raw TriNetX rows."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Profile scan mode", manifest.get("scan_mode", "-"))
    c2.metric("Rows per file", metric_int(manifest.get("max_rows_per_file")))
    c3.metric("Small-cell threshold", metric_int(small_cell_threshold))
    c4.metric("Elapsed seconds", metric_int(manifest.get("elapsed_seconds")))

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

        manifest_rows = metadata_manifest(filter_frame(data.get("metadata_tables.csv", pd.DataFrame()), archive))
        if not manifest_rows.empty:
            st.subheader("Manifest row counts")
            total_rows = pd.to_numeric(manifest_rows["row_count"], errors="coerce").sum()
            st.metric("Rows across manifest-selected tables", metric_int(total_rows))
            show_dataframe(manifest_rows, height=500)

    with tabs[1]:
        st.subheader("Dataset and cohort metadata")
        if metadata.empty:
            st.info("No metadata rows available.")
        else:
            md = metadata[metadata["member_path"].isin(["dataset_details.csv", "cohort_details.csv"])].copy()
            if md.empty:
                st.info("No dataset/cohort metadata for current filters.")
            else:
                show_dataframe(md)

    with tabs[2]:
        st.subheader("Code-system counts")
        if not code_systems.empty and {"value_1", "n"}.issubset(code_systems.columns):
            plot_df = code_systems[code_systems["suppressed"].fillna(False).eq(False)].copy()
            plot_df["n"] = pd.to_numeric(plot_df["n"], errors="coerce")
            if not plot_df.empty:
                fig = px.bar(
                    plot_df,
                    x="value_1",
                    y="n",
                    color="member_path",
                    facet_col="archive_short" if archive == "All" else None,
                    title="Sampled code-system counts",
                )
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
            tc = tc.sort_values("n", ascending=False, na_position="last")
            show_dataframe(tc, height=600)
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
                fig = px.bar(
                    dd[dd["suppressed"].fillna(False).eq(False)],
                    x="value_1",
                    y="n",
                    color="field",
                    facet_col="archive_short" if archive == "All" else None,
                    title="Sampled demographic counts",
                )
                st.plotly_chart(fig, use_container_width=True)
            show_dataframe(dd)
        else:
            st.info("No demographic rows available.")

    with tabs[5]:
        st.subheader("Date ranges, sample-based")
        st.markdown(
            "Date ranges are calculated from the profiled sample. "
            "Very early minimum dates may reflect shifted/deidentified dates or historical records."
        )
        show_dataframe(dates)

    with tabs[6]:
        st.subheader("Numeric and cost summaries, sample-based")
        st.markdown(
            "Use cost summaries only for structural review. Negative values likely represent reversals, refunds, or adjustment rows."
        )
        show_dataframe(numeric)

    with tabs[7]:
        duckdb_aggregate_tab(duckdb_path, archive, int(small_cell_threshold))

    with tabs[8]:
        st.subheader("Default privacy rules")
        st.markdown(
            """
- Do not display raw `patient_id`, `encounter_id`, `unique_id`, or `source_id`.
- Do not show raw rows from TriNetX exports, Parquet files, or DuckDB views.
- Do not allow patient-level downloads from the dashboard.
- Apply small-cell suppression, default `n < 11`.
- Treat this dashboard as internal-only. Do not expose it publicly.
- Use profile outputs for structural review and DuckDB only for aggregate queries.
            """.strip()
        )


if __name__ == "__main__":
    main()
