from dataclasses import FrozenInstanceError

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
    to_primitive,
)


def make_rule_result(status: EngineStatus) -> RuleResult:
    return RuleResult(
        rule_id="R1_EGRESS_DOOR_OPENING_WIDTH",
        rule_version="1.0.0",
        element_global_id="d1",
        element_name="Door 1",
        status=status,
        finding_code="WIDTH_MISSING",
        message="The opening-width proxy cannot be evaluated.",
        evidence_refs=("door.d1.attribute.OverallWidth",),
        inputs_used=(("threshold_m", 0.9),),
    )


def test_shared_enums_expose_exact_engine_values() -> None:
    assert [status.value for status in EngineStatus] == [
        "PASS",
        "FAIL",
        "NOT_EVALUABLE",
        "NOT_APPLICABLE",
        "ERROR",
    ]
    assert [state.value for state in ValueState] == ["PRESENT", "MISSING", "INVALID"]
    assert [source.value for source in PropertySource] == ["OCCURRENCE", "TYPE", "NONE"]


def test_rule_result_is_immutable() -> None:
    result = make_rule_result(status=EngineStatus.FAIL)
    with pytest.raises(FrozenInstanceError):
        result.status = EngineStatus.PASS


def test_domain_evidence_and_inputs_are_ordered_tuples() -> None:
    evidence = Evidence(
        ref="door.d1.attribute.OverallWidth",
        label="OverallWidth",
        raw_value=900.0,
        normalized_value=0.9,
        unit="MILLIMETRE",
        source="occurrence",
    )
    resolved = ResolvedValue(
        key="FireExit",
        state=ValueState.PRESENT,
        value=True,
        source=PropertySource.OCCURRENCE,
        evidence_refs=("door.d1.pset.FireExit",),
    )
    door = DoorFact(
        element_global_id="d1",
        display_name="Door 1",
        ifc_schema="IFC4",
        fire_exit=resolved,
        fire_rating=resolved,
        self_closing=resolved,
        overall_width_raw=900.0,
        overall_width_m=0.9,
        evidence=(evidence,),
    )
    assert isinstance(door.evidence, tuple)
    assert isinstance(make_rule_result(EngineStatus.PASS).inputs_used, tuple)
    assert door.evidence[0] is evidence


def test_to_primitive_preserves_engine_values() -> None:
    result = make_rule_result(status=EngineStatus.NOT_EVALUABLE)
    assert to_primitive(result)["status"] == "NOT_EVALUABLE"
    assert to_primitive(result)["evidence_refs"] == ["door.d1.attribute.OverallWidth"]
    assert to_primitive(result)["inputs_used"] == [["threshold_m", 0.9]]


def test_report_models_convert_recursively_to_json_safe_values() -> None:
    info = ModelInfo(
        schema="IFC4",
        length_unit="MILLIMETRE",
        door_count=1,
        length_unit_issue="LENGTHUNIT_UNSUPPORTED",
    )
    report = AnalysisReport(model_info=info, door_facts=(), results=(make_rule_result(EngineStatus.PASS),))
    primitive = to_primitive(report)
    assert primitive["model_info"]["schema"] == "IFC4"
    assert primitive["model_info"]["length_unit_issue"] == "LENGTHUNIT_UNSUPPORTED"
    assert primitive["results"][0]["status"] == "PASS"
