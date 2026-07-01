"""Faculty-facing TriNetXExplorer research workspace.

This page is intentionally research-question oriented. It queries only aggregate
DuckDB results over local Parquet views and never displays raw patient-level
rows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SMALL_CELL_THRESHOLD_DEFAULT = 11
CONCEPT_REGISTRY_PATH = Path("config/research_concepts.json")

st.set_page_config(page_title="TriNetX Research Workspace", layout="wide")


def quote_ident(name: str) -> str:
    if not SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f'"{name}"'


def sql_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@st.cache_data(show_spinner=False)
def query_duckdb(db_path_text: str, sql: str) -> pd.DataFrame:
    db_path = Path(os.path.expanduser(db_path_text)).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB database not found: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def views(db_path_text: str) -> pd.DataFrame:
    return query_duckdb(
        db_path_text,
        """
        select table_name as view_name
        from information_schema.tables
        where table_type = 'VIEW'
        order by table_name
        """,
    )


@st.cache_data(show_spinner=False)
def columns(db_path_text: str, view_name: str) -> list[str]:
    df = query_duckdb(db_path_text, f"describe {quote_ident(view_name)}")
    return [str(x) for x in df["column_name"].tolist()] if "column_name" in df.columns else []


@st.cache_data(show_spinner=False)
def load_concepts() -> pd.DataFrame:
    if not CONCEPT_REGISTRY_PATH.exists():
        return pd.DataFrame()
    payload = json.loads(CONCEPT_REGISTRY_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("concepts", []):
        row = dict(item)
        for field in ["code_systems", "code_prefixes", "search_terms"]:
            if isinstance(row.get(field), list):
                row[field] = ", ".join(str(x) for x in row[field])
        rows.append(row)
    return pd.DataFrame(rows)


def show_df(df: pd.DataFrame, height: int = 380) -> None:
    if df.empty:
        st.info("No rows available.")
    else:
        st.dataframe(df, use_container_width=True, height=height)


def view_set(view_df: pd.DataFrame) -> set[str]:
    if view_df.empty or "view_name" not in view_df.columns:
        return set()
    return set(view_df["view_name"].astype(str))


def archive_column(colnames: list[str]) -> str | None:
    for c in ["archive", "archive_short", "__archive_short"]:
        if c in colnames:
            return c
    return None


def count_by_archive_sql(view_name: str, colnames: list[str], selected_archive: str) -> str:
    qview = quote_ident(view_name)
    acol = archive_column(colnames)
    if acol:
        archive_expr = f"cast({quote_ident(acol)} as varchar)"
        where = ""
        if selected_archive != "All":
            where = f"where {archive_expr} = {sql_string(selected_archive)}"
        return f"""
        select {archive_expr} as archive_short, count(*) as n
        from {qview}
        {where}
        group by 1
        order by archive_short
        """
    return f"select 'all' as archive_short, count(*) as n from {qview}"


def aggregate_text_search_sql(view_name: str, colnames: list[str], term: str, limit: int = 500) -> str:
    qview = quote_ident(view_name)
    safe_term = term.replace("'", "''").lower()
    excluded = {"patient_id", "encounter_id", "unique_id", "source_id"}
    text_cols = [c for c in colnames if c not in excluded]
    predicates = [f"lower(cast({quote_ident(c)} as varchar)) like '%{safe_term}%'" for c in text_cols]
    selected_cols = ", ".join(quote_ident(c) for c in text_cols[:20]) or "*"
    return f"""
    select {selected_cols}
    from {qview}
    where {' or '.join(predicates) if predicates else '1=0'}
    limit {int(limit)}
    """


def diagnosis_feasibility_sql(
    colnames: list[str],
    selected_archive: str,
    code_system: str,
    code_prefix: str,
    threshold: int,
) -> str:
    qview = quote_ident("v_diagnosis")
    code_col = "code" if "code" in colnames else None
    code_system_col = "code_system" if "code_system" in colnames else None
    patient_col = "patient_id" if "patient_id" in colnames else None
    acol = archive_column(colnames)
    if not code_col:
        raise ValueError("v_diagnosis does not contain a `code` column.")

    where_parts: list[str] = []
    if acol and selected_archive != "All":
        where_parts.append(f"cast({quote_ident(acol)} as varchar) = {sql_string(selected_archive)}")
    if code_system_col and code_system and code_system != "All":
        where_parts.append(f"cast({quote_ident(code_system_col)} as varchar) = {sql_string(code_system)}")
    if code_prefix:
        where_parts.append(f"starts_with(cast({quote_ident(code_col)} as varchar), {sql_string(code_prefix)})")
    where_sql = "where " + " and ".join(where_parts) if where_parts else ""
    archive_expr = f"cast({quote_ident(acol)} as varchar)" if acol else "'all'"
    patient_expr = f"count(distinct {quote_ident(patient_col)})" if patient_col else "NULL"
    return f"""
    with agg as (
      select
        {archive_expr} as archive_short,
        count(*) as diagnosis_records,
        {patient_expr} as patients
      from {qview}
      {where_sql}
      group by 1
    )
    select
      archive_short,
      case when diagnosis_records >= {int(threshold)} then diagnosis_records else NULL end as diagnosis_records,
      case when patients is NULL or patients >= {int(threshold)} then patients else NULL end as patients,
      diagnosis_records < {int(threshold)} or (patients is not NULL and patients < {int(threshold)}) as suppressed
    from agg
    order by archive_short
    """


def render_data_guide(db_path: str, vdf: pd.DataFrame, selected_archive: str) -> None:
    st.subheader("Data guide")
    st.markdown(
        """
TriNetXExplorer currently organizes three local TriNetX exports into a safe exploration workflow.

**Confirmed exports**

- Control cohort: approximately 8.0M patients
- Stroke Diamond cohort: approximately 4.3M patients
- Stroke Research Network cohort: approximately 3.3M patients

Use this workspace to learn what is available, identify candidate concepts, and estimate feasibility before building a formal analysis plan.
        """.strip()
    )
    current_views = view_set(vdf)
    core = ["v_patient", "v_patient_cohort", "v_standardized_terminology", "v_manifest"]
    show_df(pd.DataFrame([{"component": v, "available": v in current_views} for v in core]), height=180)
    if "v_patient" in current_views:
        cols = columns(db_path, "v_patient")
        counts = query_duckdb(db_path, count_by_archive_sql("v_patient", cols, selected_archive))
        st.write("Converted patient rows by archive")
        show_df(counts, height=180)


def render_study_areas(vdf: pd.DataFrame) -> None:
    st.subheader("What can I study?")
    current = view_set(vdf)
    areas = [
        {"research_area": "Stroke/TIA diagnosis cohorts", "status": "Available now" if "v_diagnosis" in current else "Available after diagnosis conversion", "needed_views": "v_diagnosis, v_patient"},
        {"research_area": "AFib, hypertension, diabetes comorbidities", "status": "Available now" if "v_diagnosis" in current else "Available after diagnosis conversion", "needed_views": "v_diagnosis, v_patient"},
        {"research_area": "Demographics and cohort composition", "status": "Available now" if "v_patient" in current else "Needs patient conversion", "needed_views": "v_patient, v_patient_cohort"},
        {"research_area": "Terminology/code search", "status": "Available now" if "v_standardized_terminology" in current else "Needs terminology conversion", "needed_views": "v_standardized_terminology"},
        {"research_area": "Acute stroke procedures", "status": "Available now" if "v_procedure" in current else "Available after procedure conversion", "needed_views": "v_procedure"},
        {"research_area": "Medication exposure", "status": "Available after medication conversion", "needed_views": "v_medication_ingredient, v_medication_drug"},
        {"research_area": "Labs and vitals", "status": "Available after lab/vitals conversion", "needed_views": "v_lab_result, v_vitals_signs"},
        {"research_area": "Cost/utilization", "status": "Control/Diamond only after cost conversion", "needed_views": "v_cost_medical, v_cost_pharmacy"},
        {"research_area": "Encounter-based analyses", "status": "Research Network only after encounter conversion", "needed_views": "v_encounter"},
    ]
    show_df(pd.DataFrame(areas), height=430)


def render_network_differences() -> None:
    st.subheader("Network differences")
    df = pd.DataFrame([
        {"feature": "Approximate patient count", "Control/Diamond": "8.0M control; 4.3M stroke Diamond", "Research Network": "3.3M stroke Research"},
        {"feature": "Observation window", "Control/Diamond": "Sampled profile mostly through 2020-04", "Research Network": "Sampled profile extends to 2025-08"},
        {"feature": "Cost tables", "Control/Diamond": "Available", "Research Network": "Not available in current export"},
        {"feature": "Encounter table", "Control/Diamond": "Not available in current export", "Research Network": "Available"},
        {"feature": "Encounter/source IDs", "Control/Diamond": "Less encounter detail", "Research Network": "Encounter/source layer present"},
        {"feature": "Interpretation", "Control/Diamond": "Useful for cost-enabled and older-window comparisons", "Research Network": "Useful for recent and encounter-enabled analyses"},
    ])
    show_df(df, height=330)
    st.warning("Do not treat the three exports as interchangeable. Study design should explicitly choose which network(s) are appropriate.")


def render_concept_browser(db_path: str, vdf: pd.DataFrame) -> None:
    st.subheader("Concept and code browser")
    concepts = load_concepts()
    if not concepts.empty:
        st.write("Initial concept registry. These definitions are for feasibility only and require clinical validation.")
        show_df(concepts, height=360)
    st.divider()
    st.write("Search standardized terminology")
    if "v_standardized_terminology" not in view_set(vdf):
        st.info("Convert `standardized_terminology.csv` and rebuild DuckDB views to enable terminology search.")
        return
    term = st.text_input("Search term", value="stroke")
    if term.strip():
        cols = columns(db_path, "v_standardized_terminology")
        results = query_duckdb(db_path, aggregate_text_search_sql("v_standardized_terminology", cols, term.strip()))
        show_df(results, height=460)


def render_feasibility(db_path: str, vdf: pd.DataFrame, selected_archive: str, threshold: int) -> None:
    st.subheader("Cohort feasibility")
    st.markdown("This page answers: **How many patients might match my idea?** It becomes active when the relevant event table has been converted.")
    current = view_set(vdf)
    if "v_diagnosis" not in current:
        st.info("Diagnosis-backed feasibility is not active yet. Convert `diagnosis.csv` archive-by-archive and rebuild DuckDB views.")
        st.code(
            """python scripts/convert_trinetx_zip_to_parquet.py \
  --input-glob "$HOME/datasets/trinetx/*.zip" \
  --output-dir data/trinetx_parquet \
  --catalog-dir outputs/trinetx_parquet_catalog \
  --archives stroke_research \
  --tables diagnosis.csv \
  --chunksize 250000 \
  --compression snappy \
  --overwrite""",
            language="bash",
        )
        return

    diag_cols = columns(db_path, "v_diagnosis")
    code_system = "All"
    if "code_system" in diag_cols:
        systems_df = query_duckdb(db_path, "select distinct cast(code_system as varchar) as code_system from v_diagnosis order by 1 limit 100")
        systems = ["All"] + [str(x) for x in systems_df["code_system"].dropna().tolist()]
        code_system = st.selectbox("Code system", systems)
    code_prefix = st.text_input("Code prefix", value="I63")
    if st.button("Run diagnosis feasibility query"):
        sql = diagnosis_feasibility_sql(diag_cols, selected_archive, code_system, code_prefix.strip(), threshold)
        result = query_duckdb(db_path, sql)
        show_df(result, height=260)
        if not result.empty and "patients" in result.columns:
            fig = px.bar(result, x="archive_short", y="patients", title="Aggregate patient feasibility count")
            st.plotly_chart(fig, use_container_width=True)


def render_recipes() -> None:
    st.subheader("Example research recipes")
    recipes = pd.DataFrame([
        {"recipe": "Ischemic stroke cohort feasibility", "question": "How many patients have ICD stroke codes?", "needs": "diagnosis.csv", "status": "Next priority"},
        {"recipe": "AFib before/with stroke", "question": "Can we find AFib among stroke patients?", "needs": "diagnosis.csv plus temporal logic", "status": "After diagnosis conversion"},
        {"recipe": "Thrombolysis/thrombectomy utilization", "question": "Are acute stroke treatment procedure codes present?", "needs": "procedure.csv", "status": "After procedure conversion"},
        {"recipe": "Anticoagulant exposure", "question": "Can we study DOAC/warfarin exposure?", "needs": "medication_ingredient.csv, medication_drug.csv", "status": "After medication conversion"},
        {"recipe": "LDL availability after stroke", "question": "Do we have enough lipid lab data?", "needs": "lab_result.csv", "status": "After lab conversion"},
        {"recipe": "BP follow-up", "question": "Are BP/vital measurements available?", "needs": "vitals_signs.csv", "status": "After vitals conversion"},
        {"recipe": "Cost after stroke", "question": "Can we study cost/utilization?", "needs": "cost_medical.csv, cost_pharmacy.csv", "status": "Control/Diamond only"},
    ])
    show_df(recipes, height=390)


def main() -> None:
    st.title("TriNetX Research Workspace")
    st.caption("A faculty-facing workspace for learning, exploring, and testing research ideas using aggregate-only views.")
    with st.sidebar:
        db_path = st.text_input("DuckDB database", value="data/trinetx.duckdb")
        selected_archive = st.selectbox("Archive/network", ["All", "control_20240514", "stroke_diamond", "stroke_research"])
        threshold = st.number_input("Small-cell threshold", min_value=1, max_value=1000, value=SMALL_CELL_THRESHOLD_DEFAULT, step=1)

    try:
        vdf = views(db_path)
    except Exception as exc:
        st.error(f"DuckDB not available yet: {exc}")
        st.info("Run Parquet conversion and `scripts/build_duckdb_views.py`, then reload this page.")
        return

    st.warning("Aggregate-only. Do not display raw patient rows or identifiers. Concept definitions are preliminary until clinically validated.")
    tabs = st.tabs(["Data guide", "What can I study?", "Network differences", "Concept browser", "Feasibility", "Recipes"])
    with tabs[0]:
        render_data_guide(db_path, vdf, selected_archive)
    with tabs[1]:
        render_study_areas(vdf)
    with tabs[2]:
        render_network_differences()
    with tabs[3]:
        render_concept_browser(db_path, vdf)
    with tabs[4]:
        render_feasibility(db_path, vdf, selected_archive, int(threshold))
    with tabs[5]:
        render_recipes()


if __name__ == "__main__":
    main()
