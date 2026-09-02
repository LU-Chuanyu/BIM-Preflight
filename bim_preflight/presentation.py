"""Pure view models for the Streamlit evidence dashboard."""

from math import isfinite

import plotly.graph_objects as go

from bim_preflight.models import AnalysisReport, EngineStatus, RuleResult
from bim_preflight.rules import WIDTH_RULE_ID

STATUS_COLORS: dict[EngineStatus, str] = {
    EngineStatus.PASS: "#2E7D32",
    EngineStatus.FAIL: "#C62828",
    EngineStatus.NOT_EVALUABLE: "#B26A00",
    EngineStatus.NOT_APPLICABLE: "#6B7280",
    EngineStatus.ERROR: "#7E22CE",
}

STATUS_MARKERS: dict[EngineStatus, str] = {
    EngineStatus.PASS: "🟢",
    EngineStatus.FAIL: "🔴",
    EngineStatus.NOT_EVALUABLE: "🟠",
    EngineStatus.NOT_APPLICABLE: "⚪",
    EngineStatus.ERROR: "🟣",
}


def result_rows(report: AnalysisReport) -> list[dict[str, str]]:
    """Return direct projections of every authoritative engine finding."""
    return [
        {
            "rule_id": result.rule_id,
            "status": result.status.value,
            "finding_code": result.finding_code,
            "element_name": result.element_name,
            "global_id": result.element_global_id,
            "message": result.message,
        }
        for result in report.results
    ]


def _plot_points(report: AnalysisReport) -> dict[EngineStatus, tuple[list[float], list[str]]]:
    doors = {door.element_global_id: door for door in report.door_facts}
    points: dict[EngineStatus, tuple[list[float], list[str]]] = {
        EngineStatus.PASS: ([], []),
        EngineStatus.FAIL: ([], []),
    }
    for result in report.results:
        if result.rule_id != WIDTH_RULE_ID or result.status not in points:
            continue
        door = doors.get(result.element_global_id)
        width_m = None if door is None else door.overall_width_m
        if type(width_m) not in {int, float} or not isfinite(width_m) or width_m <= 0:
            continue
        values, labels = points[result.status]
        values.append(float(width_m))
        labels.append(f"{result.element_name} ({result.element_global_id})")
    return points


def width_plot(report: AnalysisReport, threshold_m: float) -> go.Figure:
    """Plot eligible R1 measurements once each against the project threshold."""
    figure = go.Figure()
    for status, (widths, labels) in _plot_points(report).items():
        if widths:
            figure.add_trace(
                go.Scatter(
                    x=widths,
                    y=labels,
                    mode="markers",
                    name=status.value,
                    marker={"color": STATUS_COLORS[status], "size": 10},
                    hovertemplate="%{y}<br>%{x:.3f} m<extra></extra>",
                )
            )
    figure.add_vline(x=threshold_m, line_dash="dash", line_color="#1F2937")
    figure.add_annotation(
        x=threshold_m,
        y=1,
        yref="paper",
        text=f"Project threshold: {threshold_m:.3f} m",
        showarrow=False,
        yanchor="bottom",
    )
    figure.update_layout(
        xaxis_title="Model-declared opening width (m)",
        yaxis_title="Door",
        margin={"l": 10, "r": 10, "t": 35, "b": 50},
        legend_title_text="R1 status",
    )
    return figure


def _input_unit(name: str) -> str | None:
    return "m" if name.endswith("_m") else None


def evidence_rows(report: AnalysisReport, result: RuleResult) -> list[dict[str, object]]:
    """Return only the selected result's referenced evidence, then immutable rule inputs."""
    door = next(
        (fact for fact in report.door_facts if fact.element_global_id == result.element_global_id), None
    )
    rows: list[dict[str, object]] = []
    if door is not None:
        evidence_by_ref = {evidence.ref: evidence for evidence in door.evidence}
        for reference in result.evidence_refs:
            evidence = evidence_by_ref.get(reference)
            if evidence is not None:
                rows.append(
                    {
                        "ref": evidence.ref,
                        "property": evidence.label,
                        "source": evidence.source,
                        "raw": evidence.raw_value,
                        "unit": evidence.unit,
                        "normalized": evidence.normalized_value,
                    }
                )
    for name, value in result.inputs_used:
        threshold_ref = next(
            (reference for reference in result.evidence_refs if name == "threshold_m" and "threshold" in reference),
            None,
        )
        is_threshold = name == "threshold_m"
        rows.append(
            {
                "ref": threshold_ref if is_threshold else None,
                "property": (
                    f"Rule configuration: {name}"
                    if is_threshold
                    else f"Authoritative rule input: {name}"
                ),
                "source": "rule configuration" if is_threshold else "authoritative rule input",
                "raw": value,
                "unit": _input_unit(name),
                "normalized": value,
            }
        )
    return rows
