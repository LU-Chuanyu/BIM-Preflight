"""Streamlit entry point for deterministic BIM preflight screening."""

import os
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from bim_preflight.engine import IfcLoadError, analyse_ifc
from bim_preflight.explain import ExplanationDraft, ExplanationUnavailable, request_explanation
from bim_preflight.models import AnalysisReport, EngineStatus, RuleResult
from bim_preflight.presentation import STATUS_COLORS, evidence_rows, result_rows, width_plot
from bim_preflight.rules import RuleConfigurationError

SCREENING_NOTICE = (
    "Screening only. IfcDoor.OverallWidth is a model-declared door-opening width proxy, not a "
    "certified clear-opening measurement or a statutory compliance conclusion."
)
DEMO_PATH = Path(__file__).parent / "samples" / "demo-egress-doors.ifc"
DEMO_PROFILE = "Demo project screening profile"
_AI_UNAVAILABLE = "AI actions are unavailable because OPENAI_API_KEY is not configured."


@contextmanager
def temporary_ifc_path(data: bytes):
    """Write uploaded bytes to one named IFC path and remove it on every exit."""
    with NamedTemporaryFile(suffix=".ifc", delete=False) as temporary_file:
        temporary_file.write(data)
        path = Path(temporary_file.name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def analyse_uploaded_bytes(
    data: bytes,
    threshold_m: float,
    analyser: Callable[[Path, float], AnalysisReport] = analyse_ifc,
) -> AnalysisReport:
    """Analyse one upload while guaranteeing the temporary IFC is unlinked."""
    with temporary_ifc_path(data) as path:
        return analyser(path, threshold_m)


def _finding_label(result: RuleResult) -> str:
    return f"{result.rule_id} | GlobalId={result.element_global_id} | {result.element_name}"


def _status_count(report: AnalysisReport, status: EngineStatus) -> int:
    return sum(result.status is status for result in report.results)


def _display_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """Keep mixed IFC evidence values readable in Streamlit's tabular transport."""
    return [
        {key: "Unavailable" if value is None else str(value) for key, value in row.items()}
        for row in rows
    ]


def _clear_analysis() -> None:
    st.session_state.pop("analysis_report", None)
    st.session_state.pop("analysis_threshold_m", None)
    st.session_state.pop("explanation_draft", None)


def _show_explanation(draft: ExplanationDraft) -> None:
    st.markdown("#### AI explanation (separate from deterministic finding)")
    st.write(draft.summary)
    if draft.evidence_refs:
        st.caption("Referenced evidence: " + ", ".join(draft.evidence_refs))
    if draft.missing_information:
        st.write("Missing information: " + "; ".join(draft.missing_information))
    st.write("Next manual check: " + draft.next_action)


def _render_ai_panel(result: RuleResult) -> None:
    st.subheader("Optional AI explanation")
    has_api_key = bool(os.environ.get("OPENAI_API_KEY"))
    if not has_api_key:
        st.caption(_AI_UNAVAILABLE)
    actions = (
        ("Explain result", "EXPLAIN_RESULT"),
        ("Explain missing evidence", "EXPLAIN_MISSING_EVIDENCE"),
        ("Recommend next manual check", "RECOMMEND_NEXT_MANUAL_CHECK"),
    )
    columns = st.columns(3)
    for column, (label, mode) in zip(columns, actions):
        with column:
            if st.button(label, key=f"ai_{mode}", disabled=not has_api_key):
                try:
                    st.session_state.explanation_draft = request_explanation(result, mode)
                except ExplanationUnavailable as error:
                    st.error(str(error))
                    st.session_state.pop("explanation_draft", None)
    draft = st.session_state.get("explanation_draft")
    if isinstance(draft, ExplanationDraft):
        _show_explanation(draft)


def _render_report(report: AnalysisReport, threshold_m: float) -> None:
    st.subheader("Model summary")
    st.write(
        {
            "schema": report.model_info.schema,
            "project_length_unit": report.model_info.length_unit or "Unavailable",
            "door_count": report.model_info.door_count,
            "screening_profile": f"{DEMO_PROFILE}: {threshold_m * 1000:g} mm",
        }
    )

    metrics = st.columns(4)
    for column, status in zip(metrics, EngineStatus):
        if status is EngineStatus.ERROR:
            continue
        with column:
            st.metric(status.value, _status_count(report, status))

    st.subheader("Deterministic findings")
    st.dataframe(result_rows(report), hide_index=True, key="result_rows")

    st.subheader("Opening-width evidence")
    st.plotly_chart(width_plot(report, threshold_m), width="stretch")

    labels = [_finding_label(result) for result in report.results]
    selected_label = st.selectbox("Select finding", labels, key="finding_selector")
    selected_result = next(result for result in report.results if _finding_label(result) == selected_label)
    st.markdown(
        f"<span style='color:{STATUS_COLORS[selected_result.status]};font-weight:700'>"
        f"{selected_result.status.value}</span> · {selected_result.finding_code}",
        unsafe_allow_html=True,
    )
    st.write(selected_result.message)

    st.subheader("Selected-finding evidence")
    st.dataframe(
        _display_rows(evidence_rows(report, selected_result)), hide_index=True, key="evidence_rows"
    )
    _render_ai_panel(selected_result)


def _render_methods() -> None:
    with st.expander("Methods and limitations"):
        st.markdown(
            "R1 screens only the model-declared `IfcDoor.OverallWidth` opening-width proxy against "
            "the selected project profile. R2 checks metadata presence only: `FireRating` must be a "
            "readable label and `SelfClosing` a valid boolean; `SelfClosing=false counts as present`. "
            "No legal, fire-code, or installed-performance conclusion is made."
        )


def main() -> None:
    st.set_page_config(page_title="BIM Preflight", layout="wide")
    st.title("BIM Preflight")
    st.info(SCREENING_NOTICE)
    st.caption("Deterministic IFC door screening with evidence-first review.")

    source = st.radio(
        "IFC source",
        ("Upload IFC", "Bundled synthetic demo"),
        key="input_source",
        horizontal=True,
    )
    upload = st.file_uploader(
        "Upload IFC",
        type=["ifc"],
        key="ifc_upload",
        disabled=source != "Upload IFC",
    )
    threshold_mm = st.number_input(
        "Minimum opening-width threshold (mm)",
        min_value=1,
        value=900,
        step=1,
        key="threshold_mm",
    )
    st.caption(DEMO_PROFILE)

    if st.button("Run preflight", type="primary", key="run_preflight"):
        threshold_m = float(threshold_mm) / 1000
        try:
            if source == "Upload IFC":
                if upload is None:
                    _clear_analysis()
                    st.info("Upload an IFC file before running preflight.")
                else:
                    report = analyse_uploaded_bytes(upload.getvalue(), threshold_m)
                    st.session_state.analysis_report = report
                    st.session_state.analysis_threshold_m = threshold_m
                    st.session_state.pop("explanation_draft", None)
            elif not DEMO_PATH.is_file():
                _clear_analysis()
                st.info("Bundled synthetic demo is not available yet.")
            else:
                report = analyse_ifc(DEMO_PATH, threshold_m)
                st.session_state.analysis_report = report
                st.session_state.analysis_threshold_m = threshold_m
                st.session_state.pop("explanation_draft", None)
        except IfcLoadError as error:
            _clear_analysis()
            st.error(str(error))
        except RuleConfigurationError as error:
            _clear_analysis()
            st.error(f"Screening configuration error: {error}")

    report = st.session_state.get("analysis_report")
    threshold_m = st.session_state.get("analysis_threshold_m")
    if isinstance(report, AnalysisReport) and isinstance(threshold_m, float):
        _render_report(report, threshold_m)
    else:
        st.info("Upload an IFC file and select Run preflight to start.")
    _render_methods()


main()
