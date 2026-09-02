from pathlib import Path

import ifcopenshell.guid
import pytest
from ifc_factory import make_door_model

from bim_preflight import engine
from bim_preflight.engine import IfcLoadError, analyse_ifc
from bim_preflight.models import DoorFact, EngineStatus, RuleResult


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


def test_one_door_evaluation_error_does_not_abort_other_doors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches one unexpected door failure preventing later doors from receiving results."""
    path = tmp_path / "doors.ifc"
    first_id = _write_model(path, fire_exit=True, name="First Door")
    model = engine.open_ifc(path)
    second_id = _add_egress_door(model, name="Second Door")
    model.write(str(path))

    real_evaluate_door = engine.evaluate_door

    def fail_first_door(door: DoorFact, threshold_m: float) -> tuple[RuleResult, RuleResult]:
        if door.element_global_id == first_id:
            raise RuntimeError("unexpected per-door failure")
        return real_evaluate_door(door, threshold_m)

    monkeypatch.setattr(engine, "evaluate_door", fail_first_door)

    report = analyse_ifc(path, threshold_m=0.9)

    results_by_door = {
        global_id: tuple(result.status for result in report.results if result.element_global_id == global_id)
        for global_id in {first_id, second_id}
    }
    assert results_by_door[first_id] == (EngineStatus.ERROR, EngineStatus.ERROR)
    assert results_by_door[second_id] == (EngineStatus.PASS, EngineStatus.PASS)
    assert [(result.element_global_id, result.rule_id) for result in report.results] == sorted(
        (result.element_global_id, result.rule_id) for result in report.results
    )
