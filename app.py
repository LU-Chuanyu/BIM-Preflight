"""Streamlit entry point for deterministic BIM preflight screening."""

import os
from collections.abc import Callable
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from bim_preflight.engine import IfcLoadError, analyse_ifc
from bim_preflight.explain import ExplanationDraft, ExplanationUnavailable, request_explanation
from bim_preflight.models import AnalysisReport, EngineStatus, RuleResult
from bim_preflight.presentation import (
    STATUS_MARKERS,
    evidence_rows,
    result_rows,
    width_plot,
)
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
    path: Path | None = None
    try:
        with NamedTemporaryFile(suffix=".ifc", delete=False) as temporary_file:
            path = Path(temporary_file.name)
            temporary_file.write(data)
        yield path
    finally:
        if path is not None:
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


def _ordered_results(report: AnalysisReport) -> tuple[RuleResult, ...]:
    """Order findings for human review without changing the engine report."""
    return tuple(
        sorted(
            report.results,
            key=lambda result: (
                result.element_name.casefold(),
                result.rule_id,
                result.element_global_id,
            ),
        )
    )


def _display_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """Keep mixed IFC evidence values readable in Streamlit's tabular transport."""
    return [
        {key: "Unavailable" if value is None else str(value) for key, value in row.items()}
        for row in rows
    ]


def _result_display_rows(report: AnalysisReport) -> list[dict[str, str]]:
    """Add a trusted, accessible status marker without changing engine-owned rows."""
    rows_by_result = {
        (row["global_id"], row["rule_id"]): row for row in result_rows(report)
    }
    rows: list[dict[str, str]] = []
    for result in _ordered_results(report):
        row = rows_by_result[(result.element_global_id, result.rule_id)]
        status = EngineStatus(row["status"])
        rows.append({"status_indicator": STATUS_MARKERS[status], **row})
    return rows


def _clear_analysis() -> None:
    st.session_state.pop("analysis_report", None)
    st.session_state.pop("analysis_threshold_m", None)
    st.session_state.pop("analysis_source", None)
    st.session_state.pop("analysis_source_kind", None)
    st.session_state.pop("analysis_fingerprint", None)
    st.session_state.pop("explanation_state", None)
    st.session_state.pop("selected_finding", None)
    st.session_state.pop("finding_selector", None)


def _input_fingerprint(source: str, threshold_mm: float, upload: object) -> tuple[object, ...]:
    """Identify exactly the inputs that would make a stored report stale."""
    if source == "Upload IFC":
        content = b"" if upload is None else upload.getvalue()
        name = "" if upload is None else upload.name
        return source, float(threshold_mm), name, sha256(content).hexdigest()
    try:
        demo_digest = sha256(DEMO_PATH.read_bytes()).hexdigest()
    except OSError:
        demo_digest = "unavailable"
    return source, float(threshold_mm), str(DEMO_PATH), demo_digest


def _threshold_label(source: str, threshold_m: float) -> str:
    threshold_mm = threshold_m * 1000
    if source == "Bundled synthetic demo" and threshold_mm == 900:
        return f"{DEMO_PROFILE}: 900 mm"
    return f"Selected project screening threshold: {threshold_mm:g} mm"


def _store_analysis(
    report: AnalysisReport,
    *,
    source: str,
    source_label: str,
    fingerprint: tuple[object, ...],
    threshold_m: float,
) -> None:
    st.session_state.analysis_report = report
    st.session_state.analysis_source = source_label
    st.session_state.analysis_source_kind = source
    st.session_state.analysis_fingerprint = fingerprint
    st.session_state.analysis_threshold_m = threshold_m
    st.session_state.pop("explanation_state", None)
    st.session_state.pop("selected_finding", None)
    st.session_state.pop("finding_selector", None)


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
                    st.session_state.explanation_state = (
                        (result.rule_id, result.element_global_id, mode),
                        request_explanation(result, mode),
                    )
                except ExplanationUnavailable as error:
                    st.error(str(error))
                    st.session_state.pop("explanation_state", None)
    explanation_state = st.session_state.get("explanation_state")
    if (
        isinstance(explanation_state, tuple)
        and len(explanation_state) == 2
        and isinstance(explanation_state[0], tuple)
        and len(explanation_state[0]) == 3
        and explanation_state[0][:2] == (result.rule_id, result.element_global_id)
        and isinstance(explanation_state[1], ExplanationDraft)
    ):
        draft = explanation_state[1]
        _show_explanation(draft)


def _render_report(
    report: AnalysisReport,
    threshold_m: float,
    source_kind: str,
    source_label: str,
) -> None:
    st.subheader("Model summary")
    st.write(
        {
            "schema": report.model_info.schema,
            "project_length_unit": report.model_info.length_unit or "Unavailable",
            "door_count": report.model_info.door_count,
            "analysed_source": source_label,
            "screening_threshold": _threshold_label(source_kind, threshold_m),
        }
    )

    metrics = st.columns(5)
    for column, status in zip(metrics, EngineStatus):
        with column:
            st.metric(status.value, _status_count(report, status))

    if not report.results:
        st.info("No IfcDoor occurrences were found; no rules were evaluated.")
        return

    st.subheader("Deterministic findings")
    st.dataframe(_result_display_rows(report), hide_index=True, key="result_rows")

    st.subheader("Opening-width evidence")
    st.plotly_chart(width_plot(report, threshold_m), width="stretch")

    ordered_results = _ordered_results(report)
    labels = [_finding_label(result) for result in ordered_results]
    selected_label = st.selectbox("Select finding", labels, key="finding_selector")
    selected_result = next(
        result for result in ordered_results if _finding_label(result) == selected_label
    )
    selected_key = (selected_result.rule_id, selected_result.element_global_id)
    previous_key = st.session_state.get("selected_finding")
    if previous_key is not None and previous_key != selected_key:
        st.session_state.pop("explanation_state", None)
    st.session_state.selected_finding = selected_key
    st.markdown(
        f"{STATUS_MARKERS[selected_result.status]} **{selected_result.status.value}** · "
        f"`{selected_result.finding_code}`"
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
            "readable label and `SelfClosing` a valid boolean; SelfClosing = FALSE counts as present. "
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
    upload = None
    if source == "Upload IFC":
        upload = st.file_uploader("Upload IFC", type=["ifc"], key="ifc_upload")
    else:
        st.caption("Using the bundled candidate-authored synthetic IFC4 demo with six doors.")
    threshold_mm = st.number_input(
        "Minimum opening-width threshold (mm)",
        min_value=1,
        value=900,
        step=1,
        key="threshold_mm",
    )
    st.caption(
        "Default threshold: 900 mm. The bundled synthetic demo uses the Demo project screening profile."
    )

    fingerprint = _input_fingerprint(source, threshold_mm, upload)
    stored_fingerprint = st.session_state.get("analysis_fingerprint")
    if stored_fingerprint is not None and stored_fingerprint != fingerprint:
        _clear_analysis()

    if st.button("Run preflight", type="primary", key="run_preflight"):
        threshold_m = float(threshold_mm) / 1000
        try:
            if source == "Upload IFC":
                if upload is None:
                    _clear_analysis()
                    st.info("Upload an IFC file before running preflight.")
                else:
                    report = analyse_uploaded_bytes(upload.getvalue(), threshold_m)
                    _store_analysis(
                        report,
                        source=source,
                        source_label=f"Uploaded IFC: {upload.name}",
                        fingerprint=fingerprint,
                        threshold_m=threshold_m,
                    )
            elif not DEMO_PATH.is_file():
                _clear_analysis()
                st.info("Bundled synthetic demo is not available yet.")
            else:
                report = analyse_ifc(DEMO_PATH, threshold_m)
                _store_analysis(
                    report,
                    source=source,
                    source_label="Bundled synthetic demo",
                    fingerprint=fingerprint,
                    threshold_m=threshold_m,
                )
        except IfcLoadError as error:
            _clear_analysis()
            st.error(str(error))
        except RuleConfigurationError as error:
            _clear_analysis()
            st.error(f"Screening configuration error: {error}")

    report = st.session_state.get("analysis_report")
    threshold_m = st.session_state.get("analysis_threshold_m")
    analysed_source = st.session_state.get("analysis_source")
    analysed_source_kind = st.session_state.get("analysis_source_kind")
    if (
        isinstance(report, AnalysisReport)
        and isinstance(threshold_m, float)
        and isinstance(analysed_source, str)
        and isinstance(analysed_source_kind, str)
    ):
        _render_report(report, threshold_m, analysed_source_kind, analysed_source)
    else:
        st.info("Upload an IFC file and select Run preflight to start.")
    _render_methods()


main()
