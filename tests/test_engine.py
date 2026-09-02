from pathlib import Path

import ifcopenshell.guid
import pytest
from ifc_factory import make_door_model

from bim_preflight import engine
from bim_preflight.engine import IfcLoadError, analyse_ifc
from bim_preflight.models import DoorFact, EngineStatus, RuleResult
from bim_preflight.rules import RuleConfigurationError


def _write_model(path: Path, *, fire_exit: bool, name: str) -> str:
    model, door = make_door_model(
        name=name,
        overall_width=1000.0,
        occurrence_properties={
            "FireExit": fire_exit,
            "FireRating": "60 min",
            "SelfClosing": True,
        },
    )
    model.write(str(path))
    return door.GlobalId


def _add_egress_door(model: object, *, name: str) -> str:
    """Add a second occurrence to the same temporary project and units context."""
    door = model.create_entity(
        "IfcDoor",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        OverallWidth=1000.0,
    )
    properties = tuple(
        model.create_entity("IfcPropertySingleValue", Name=key, NominalValue=value)
        for key, value in (
            ("FireExit", model.create_entity("IfcBoolean", True)),
            ("FireRating", model.create_entity("IfcLabel", "60 min")),
            ("SelfClosing", model.create_entity("IfcBoolean", True)),
        )
    )
    property_set = model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name="Pset_DoorCommon",
        HasProperties=properties,
    )
    model.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=(door,),
        RelatingPropertyDefinition=property_set,
    )
    return door.GlobalId


def test_analyse_ifc_returns_sorted_two_rule_results_and_project_metadata(tmp_path: Path) -> None:
    """Catches nondeterministic result order or report metadata derived from only one rule."""
    path = tmp_path / "door.ifc"
    global_id = _write_model(path, fire_exit=True, name="Test Door")

    report = analyse_ifc(path, threshold_m=0.9)

    assert report.model_info.schema == "IFC4"
    assert report.model_info.length_unit == "MILLIMETRE"
    assert report.model_info.door_count == 1
    assert [fact.element_global_id for fact in report.door_facts] == [global_id]
    assert [(result.element_global_id, result.rule_id) for result in report.results] == [
        (global_id, "R1_EGRESS_DOOR_OPENING_WIDTH"),
        (global_id, "R2_EGRESS_DOOR_METADATA_COMPLETENESS"),
    ]
    assert [result.status for result in report.results] == [EngineStatus.PASS, EngineStatus.PASS]


def test_analyse_ifc_wraps_whole_file_open_failures(tmp_path: Path) -> None:
    """Catches leaking parser-specific exceptions across the application boundary."""
    missing_path = tmp_path / "does-not-exist.ifc"
    with pytest.raises(IfcLoadError, match="Unable to load IFC file"):
        analyse_ifc(missing_path, threshold_m=0.9)


@pytest.mark.parametrize("failing_step", ["resolve_length_unit", "extract_door_facts"])
def test_analyse_ifc_wraps_preprocessing_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_step: str
) -> None:
    """Catches leaking failures after opening but before per-door evaluation."""
    path = tmp_path / "door.ifc"
    _write_model(path, fire_exit=True, name="Test Door")

    def fail_preprocessing(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"{failing_step} failed")

    monkeypatch.setattr(engine, failing_step, fail_preprocessing)

    with pytest.raises(IfcLoadError, match="Unable to load IFC file") as caught:
        analyse_ifc(path, threshold_m=0.9)
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_analyse_ifc_propagates_invalid_threshold_as_configuration_error(tmp_path: Path) -> None:
    """Catches converting an invalid user configuration into a per-door ERROR finding."""
    path = tmp_path / "door.ifc"
    _write_model(path, fire_exit=True, name="Test Door")

    with pytest.raises(RuleConfigurationError, match="threshold"):
        analyse_ifc(path, threshold_m=0.0)


def test_width_rule_error_does_not_abort_metadata_or_other_doors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches one unexpected door failure preventing later doors from receiving results."""
    path = tmp_path / "doors.ifc"
    first_id = _write_model(path, fire_exit=True, name="First Door")
    model = engine.open_ifc(path)
    second_id = _add_egress_door(model, name="Second Door")
    model.write(str(path))

    real_evaluate_width_rule = engine.evaluate_width_rule

    def fail_first_width_rule(door: DoorFact, threshold_m: float) -> RuleResult:
        if door.element_global_id == first_id:
            raise RuntimeError("unexpected per-door failure")
        return real_evaluate_width_rule(door, threshold_m)

    monkeypatch.setattr(engine, "evaluate_width_rule", fail_first_width_rule)

    report = analyse_ifc(path, threshold_m=0.9)

    first_results = {result.rule_id: result for result in report.results if result.element_global_id == first_id}
    second_results = {result.rule_id: result for result in report.results if result.element_global_id == second_id}
    assert first_results["R1_EGRESS_DOOR_OPENING_WIDTH"].status is EngineStatus.ERROR
    assert first_results["R2_EGRESS_DOOR_METADATA_COMPLETENESS"].status is EngineStatus.PASS
    assert second_results["R1_EGRESS_DOOR_OPENING_WIDTH"].status is EngineStatus.PASS
    assert second_results["R2_EGRESS_DOOR_METADATA_COMPLETENESS"].status is EngineStatus.PASS
    first_fact = next(fact for fact in report.door_facts if fact.element_global_id == first_id)
    width_error = first_results["R1_EGRESS_DOOR_OPENING_WIDTH"]
    assert width_error.finding_code == "WIDTH_RULE_EVALUATION_ERROR"
    assert width_error.evidence_refs == (
        *first_fact.fire_exit.evidence_refs,
        *(item.ref for item in first_fact.evidence if item.label in {"LENGTHUNIT", "OverallWidth"}),
    )
    assert width_error.inputs_used == (("overall_width_m", 1.0), ("threshold_m", 0.9))
    assert [(result.element_global_id, result.rule_id) for result in report.results] == sorted(
        (result.element_global_id, result.rule_id) for result in report.results
    )
