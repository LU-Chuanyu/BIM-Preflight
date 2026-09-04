"""Pure rendering-data tests for the evidence dashboard."""

from math import nan

import pytest

from bim_preflight.models import (
    AnalysisReport,
    DoorFact,
    EngineStatus,
    Evidence,
    ModelInfo,
    PropertySource,
    ResolvedValue,
    RuleResult,
    ValueState,
)
from bim_preflight.presentation import (
    STATUS_COLORS,
    evidence_rows,
    finding_action_summary,
    ordered_results,
    result_rows,
    width_plot,
)
from bim_preflight.rules import METADATA_RULE_ID, WIDTH_RULE_ID


def _resolved(key: str, value: object) -> ResolvedValue:
    return ResolvedValue(
        key=key,
        state=ValueState.PRESENT,
        value=value,
        source=PropertySource.OCCURRENCE,
        evidence_refs=(f"door.d1.occurrence.{key}",),
    )


def _door(global_id: str, width_m: float | None) -> DoorFact:
    return DoorFact(
        element_global_id=global_id,
        display_name=f"Door {global_id}",
        ifc_schema="IFC4",
        fire_exit=_resolved("FireExit", True),
        fire_rating=_resolved("FireRating", "60 min"),
        self_closing=_resolved("SelfClosing", False),
        overall_width_raw=None if width_m is None else width_m * 1000,
        overall_width_m=width_m,
        evidence=(
            Evidence(
                ref=f"door.{global_id}.fire_exit",
                label="Pset_DoorCommon.FireExit",
                raw_value=True,
                normalized_value=True,
                unit=None,
                source="occurrence",
            ),
            Evidence(
                ref=f"door.{global_id}.width",
                label="OverallWidth",
                raw_value=None if width_m is None else width_m * 1000,
                normalized_value=width_m,
                unit="MILLIMETRE",
                source="occurrence",
            ),
        ),
    )


def _result(
    global_id: str,
    status: EngineStatus,
    *,
    rule_id: str = WIDTH_RULE_ID,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version="1.0.0",
        element_global_id=global_id,
        element_name=f"Door {global_id}",
        status=status,
        finding_code=f"{status.value}_CODE",
        message=f"{status.value} engine message.",
        evidence_refs=(f"door.{global_id}.fire_exit", f"door.{global_id}.width", "rule.threshold"),
        inputs_used=(("overall_width_m", 1.0), ("threshold_m", 0.9)),
    )


@pytest.fixture
def report() -> AnalysisReport:
    statuses = tuple(EngineStatus)
    doors = tuple(_door(f"d{index}", 1.0 if status is EngineStatus.PASS else None) for index, status in enumerate(statuses, 1))
    results = tuple(_result(door.element_global_id, status) for door, status in zip(doors, statuses))
    return AnalysisReport(
        model_info=ModelInfo(schema="IFC4", length_unit="MILLIMETRE", door_count=len(doors)),
        door_facts=doors,
        results=results,
    )


def test_result_rows_keep_all_engine_owned_fields_for_every_status(report: AnalysisReport) -> None:
    """Catches table code dropping error or non-verdict engine outcomes."""
    rows = result_rows(report)

    assert {row["status"] for row in rows} == {status.value for status in EngineStatus}
    assert rows[0] == {
        "check": "Opening width",
        "rule_id": WIDTH_RULE_ID,
        "status": "PASS",
        "finding_code": "PASS_CODE",
        "element_name": "Door d1",
        "global_id": "d1",
        "message": "PASS engine message.",
    }


def test_ordered_results_prioritise_findings_that_need_attention(report: AnalysisReport) -> None:
    """Catches review order drifting back to alphabetical status or source order."""
    assert [result.status for result in ordered_results(report)] == [
        EngineStatus.ERROR,
        EngineStatus.FAIL,
        EngineStatus.NOT_EVALUABLE,
        EngineStatus.PASS,
        EngineStatus.NOT_APPLICABLE,
    ]


def test_finding_action_summary_counts_failed_and_not_evaluable_checks(report: AnalysisReport) -> None:
    """Catches a demo summary that hides either remediation or missing-information work."""
    assert (
        finding_action_summary(report)
        == "Action summary: 1 failed check requires resolution; 1 needs additional information; "
        "1 check encountered an internal error."
    )


def test_result_rows_add_a_friendly_check_label_without_losing_audit_identifiers(
    report: AnalysisReport,
) -> None:
    """Catches a table that asks reviewers to memorise rule IDs or drops traceability."""
    rows = result_rows(report)

    assert rows[0]["check"] == "Opening width"
    assert {"rule_id", "finding_code", "global_id"} <= rows[0].keys()

    metadata_result = _result("d1", EngineStatus.PASS, rule_id=METADATA_RULE_ID)
    metadata_report = AnalysisReport(report.model_info, report.door_facts, (metadata_result,))
    assert result_rows(metadata_report)[0]["check"] == "Metadata completeness"


def test_width_plot_contains_only_finite_positive_r1_pass_fail_measurements(
    report: AnalysisReport,
) -> None:
    """Catches non-evaluable outcomes leaking into the measured-width plot."""
    altered_results = list(report.results)
    altered_results[1] = _result("d2", EngineStatus.FAIL)
    altered_doors = list(report.door_facts)
    altered_doors[1] = _door("d2", 0.8)
    altered_doors[2] = _door("d3", nan)
    figure = width_plot(
        AnalysisReport(report.model_info, tuple(altered_doors), tuple(altered_results)), threshold_m=0.9
    )

    assert figure.layout.xaxis.title.text == "Model-declared opening width (m)"
    assert sorted(value for trace in figure.data for value in trace.x) == [0.8, 1.0]
    assert sorted(value for trace in figure.data for value in trace.y) == ["Door d1", "Door d2"]
    assert sorted(value for trace in figure.data for value in trace.customdata) == ["d1", "d2"]
    assert all("GlobalId: %{customdata}" in trace.hovertemplate for trace in figure.data)
    assert len(figure.layout.shapes) == 1
    assert figure.layout.shapes[0].x0 == 0.9
    assert figure.layout.annotations[0].text == "Project threshold: 0.900 m"


def test_width_plot_ignores_r2_results_even_when_their_door_has_a_width(report: AnalysisReport) -> None:
    """Catches duplicated dots when both rules are rendered as measurements."""
    report = AnalysisReport(
        report.model_info,
        report.door_facts,
        (
            _result("d1", EngineStatus.PASS),
            _result("d1", EngineStatus.FAIL, rule_id=METADATA_RULE_ID),
        ),
    )

    figure = width_plot(report, threshold_m=0.9)

    assert [value for trace in figure.data for value in trace.x] == [1.0]


def test_evidence_rows_preserve_selected_door_order_and_do_not_leak_other_door(
    report: AnalysisReport,
) -> None:
    """Catches evidence lookup by shared property name instead of GlobalId and result references."""
    selected = _result("d2", EngineStatus.FAIL)

    rows = evidence_rows(report, selected)

    assert [row["ref"] for row in rows[:2]] == ["door.d2.fire_exit", "door.d2.width"]
    assert all(row["ref"] is None or "d1" not in row["ref"] for row in rows)
    assert rows[1] == {
        "ref": "door.d2.width",
        "property": "OverallWidth",
        "source": "occurrence",
        "raw": None,
        "unit": "MILLIMETRE",
        "normalized": None,
    }
    assert rows[-2] == {
        "ref": None,
        "property": "Authoritative rule input: overall_width_m",
        "source": "authoritative rule input",
        "raw": 1.0,
        "unit": "m",
        "normalized": 1.0,
    }
    assert rows[-1] == {
        "ref": "rule.threshold",
        "property": "Rule configuration: threshold_m",
        "source": "rule configuration",
        "raw": 0.9,
        "unit": "m",
        "normalized": 0.9,
    }


def test_evidence_rows_follow_result_reference_order_and_keep_r2_inputs_out_of_configuration(
    report: AnalysisReport,
) -> None:
    """Catches set-based evidence ordering and treating every rule input as project configuration."""
    selected = RuleResult(
        rule_id=METADATA_RULE_ID,
        rule_version="1.0.0",
        element_global_id="d2",
        element_name="Door d2",
        status=EngineStatus.FAIL,
        finding_code="FIRE_RATING_MISSING",
        message="Required FireRating metadata is missing.",
        evidence_refs=("door.d2.width", "door.d2.fire_exit"),
        inputs_used=(("fire_rating", None), ("self_closing", False)),
    )

    rows = evidence_rows(report, selected)

    assert [row["ref"] for row in rows[:2]] == ["door.d2.width", "door.d2.fire_exit"]
    assert [row["source"] for row in rows[-2:]] == [
        "authoritative rule input",
        "authoritative rule input",
    ]
    assert all(row["ref"] is None for row in rows[-2:])


def test_applicability_inputs_are_not_fabricated_as_door_evidence(report: AnalysisReport) -> None:
    """Catches FireExit branch inputs being mislabeled as project configuration evidence."""
    selected = RuleResult(
        rule_id=WIDTH_RULE_ID,
        rule_version="1.0.0",
        element_global_id="d2",
        element_name="Door d2",
        status=EngineStatus.NOT_EVALUABLE,
        finding_code="FIRE_EXIT_UNRESOLVED",
        message="The door's FireExit classification is missing or invalid.",
        evidence_refs=("door.d2.fire_exit",),
        inputs_used=(
            ("fire_exit_value", None),
            ("fire_exit_state", "MISSING"),
            ("fire_exit_source", "NONE"),
        ),
    )

    rows = evidence_rows(report, selected)

    assert [row["ref"] for row in rows] == ["door.d2.fire_exit", None, None, None]
    assert all(row["source"] == "authoritative rule input" for row in rows[1:])


def test_status_colors_cover_one_consistent_color_for_each_engine_status() -> None:
    """Catches a new status rendering without a documented visual treatment."""
    assert set(STATUS_COLORS) == set(EngineStatus)
    assert STATUS_COLORS[EngineStatus.PASS] == "#2E7D32"
    assert STATUS_COLORS[EngineStatus.FAIL] == "#C62828"
    assert STATUS_COLORS[EngineStatus.NOT_EVALUABLE] == "#B26A00"
    assert STATUS_COLORS[EngineStatus.NOT_APPLICABLE] == "#6B7280"
    assert STATUS_COLORS[EngineStatus.ERROR] == "#7E22CE"
