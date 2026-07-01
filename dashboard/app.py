"""Streamlit dashboard for aggregate TriNetX profile outputs.

Run:
    streamlit run dashboard/app.py

The dashboard reads only outputs created by scripts/audit_trinetx_archives.py
and scripts/profile_trinetx_archives.py. It is not a raw TriNetX data browser.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import zipfile

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


def main() -> None:
    st.title("TriNetXExplorer")
    st.caption("Aggregate profile dashboard. It reads audit/profile outputs only. It does not open raw TriNetX exports.")

    with st.sidebar:
        st.header("Profile source")
        default_path = latest_profile_path()
        profile_path = st.text_input("Profile output directory or ZIP", value=default_path)
        st.markdown(
            "Run `scripts/profile_trinetx_archives.py` first. "
            "Point this dashboard to the generated output directory or ZIP."
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
        table = st.selectbox("Table", tables)

    table_profiles = filter_frame(data.get("table_profiles.csv", pd.DataFrame()), archive, table)
    metadata = filter_frame(data.get("metadata_tables.csv", pd.DataFrame()), archive, table)
    code_systems = filter_frame(data.get("code_system_counts.csv", pd.DataFrame()), archive, table)
    top_codes = filter_frame(data.get("top_codes_suppressed.csv", pd.DataFrame()), archive, table)
    demographics = filter_frame(data.get("patient_demographics_suppressed.csv", pd.DataFrame()), archive, table)
    dates = filter_frame(data.get("date_ranges.csv", pd.DataFrame()), archive, table)
    numeric = filter_frame(data.get("numeric_summaries.csv", pd.DataFrame()), archive, table)

    st.warning(
        "Counts in profile-derived tables are sample-based unless `scan_mode` says full. "
        "Use them to design the dashboard and detect structure, not as final epidemiologic estimates."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Profile scan mode", manifest.get("scan_mode", "-"))
    c2.metric("Rows per file", metric_int(manifest.get("max_rows_per_file")))
    c3.metric("Small-cell threshold", metric_int(manifest.get("small_cell_threshold")))
    c4.metric("Elapsed seconds", metric_int(manifest.get("elapsed_seconds")))

    tabs = st.tabs([
        "Inventory",
        "Dataset and cohorts",
        "Code systems",
        "Top codes",
        "Demographics",
        "Dates",
        "Numeric and cost",
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
        st.subheader("Default privacy rules")
        st.markdown(
            """
- Do not display raw `patient_id`, `encounter_id`, `unique_id`, or `source_id`.
- Do not show raw rows from TriNetX exports.
- Do not allow patient-level downloads from the dashboard.
- Apply small-cell suppression, default `n < 11`.
- Treat this dashboard as internal-only. Do not expose it publicly.
- Use profile and catalog outputs for dashboard v0.1. Convert raw CSV exports to Parquet before interactive event-level queries.
            """.strip()
        )


if __name__ == "__main__":
    main()
