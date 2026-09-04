import gc
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.validate
import pytest
from ifc_factory import make_door_model

from bim_preflight import engine
from bim_preflight.engine import IfcLoadError, analyse_ifc
from bim_preflight.ifc_extract import open_ifc
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
    assert report.model_info.length_unit_issue is None
    assert report.model_info.door_count == 1
    assert [fact.element_global_id for fact in report.door_facts] == [global_id]
    assert [(result.element_global_id, result.rule_id) for result in report.results] == [
        (global_id, "R1_EGRESS_DOOR_OPENING_WIDTH"),
        (global_id, "R2_EGRESS_DOOR_METADATA_COMPLETENESS"),
    ]
    assert [result.status for result in report.results] == [EngineStatus.PASS, EngineStatus.PASS]


def test_custom_length_unit_cannot_normalise_width_or_false_pass_r1(tmp_path: Path) -> None:
    """Catches treating an opaque custom LENGTHUNIT as metres in the R1 decision."""
    path = tmp_path / "custom-unit.ifc"
    model, door = make_door_model(
        overall_width=1.0,
        occurrence_properties={"FireExit": True, "FireRating": "60 min", "SelfClosing": True},
        length_prefix=None,
    )
    dimensions = model.create_entity(
        "IfcDimensionalExponents",
        LengthExponent=1,
        MassExponent=0,
        TimeExponent=0,
        ElectricCurrentExponent=0,
        ThermodynamicTemperatureExponent=0,
        AmountOfSubstanceExponent=0,
        LuminousIntensityExponent=0,
    )
    custom = model.create_entity(
        "IfcContextDependentUnit",
        Dimensions=dimensions,
        UnitType="LENGTHUNIT",
        Name="CUSTOM_LENGTH",
    )
    model.by_type("IfcProject")[0].UnitsInContext = model.create_entity(
        "IfcUnitAssignment", Units=(custom,)
    )
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert logger.statements == []
    model.write(str(path))

    report = analyse_ifc(path, threshold_m=0.9)

    fact = report.door_facts[0]
    width_result = next(result for result in report.results if result.rule_id.startswith("R1_"))
    assert fact.element_global_id == door.GlobalId
    assert report.model_info.length_unit is None
    assert report.model_info.length_unit_issue == "LENGTHUNIT_UNSUPPORTED"
    assert fact.overall_width_raw == pytest.approx(1.0)
    assert fact.overall_width_m is None
    assert width_result.status is EngineStatus.NOT_EVALUABLE
    assert width_result.finding_code == "WIDTH_NOT_EVALUABLE"


def test_analyse_ifc_wraps_whole_file_open_failures(tmp_path: Path) -> None:
    """Catches leaking parser-specific exceptions across the application boundary."""
    missing_path = tmp_path / "does-not-exist.ifc"
    with pytest.raises(IfcLoadError, match="Unable to load IFC file"):
        analyse_ifc(missing_path, threshold_m=0.9)


def test_open_ifc_preserves_file_not_found_error(tmp_path: Path) -> None:
    """Catches a preflight adapter that erases the local missing-file distinction."""
    with pytest.raises(FileNotFoundError):
        open_ifc(tmp_path / "missing.ifc")


@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.parametrize(
    ("name", "contents", "error_type"),
    [
        ("garbage.ifc", "this is not IFC", ifcopenshell.Error),
        (
            "truncated.ifc",
            """ISO-10303-21;
HEADER;
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0AAAAAAAAAAAAAAAAAAAAA',$,'P',$,$,$,$,$,$);
""",
            ifcopenshell.Error,
        ),
        (
            "unsupported.ifc",
            """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('unsupported.ifc','2026-09-03T00:00:00',(''),(''),'test','test','');
FILE_SCHEMA(('IFC999'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""",
            ifcopenshell.SchemaError,
        ),
    ],
)
def test_open_ifc_rejects_bad_step_without_unraisable_destructor_warning(
    tmp_path: Path, name: str, contents: str, error_type: type[Exception]
) -> None:
    """Catches constructing a high-level file around a failed low-level parse."""
    path = tmp_path / name
    path.write_text(contents)

    with pytest.raises(error_type):
        open_ifc(path)
    gc.collect()


def test_open_ifc_wraps_valid_synthetic_and_official_models(tmp_path: Path) -> None:
    """Catches bypassing the warning while breaking either accepted local-file path."""
    synthetic_path = tmp_path / "synthetic.ifc"
    _write_model(synthetic_path, fire_exit=True, name="Synthetic")
    official_path = Path(__file__).parents[1] / "samples" / "official" / "Building-Architecture.ifc"

    synthetic = open_ifc(synthetic_path)
    official = open_ifc(official_path)

    assert synthetic.schema == "IFC4"
    assert len(synthetic.by_type("IfcDoor")) == 1
    assert official.schema == "IFC4"
    assert len(official.by_type("IfcProject")) == 1


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
