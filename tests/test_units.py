import pytest
from ifc_factory import make_ifc_model

from bim_preflight.units import resolve_length_unit


def test_millimetres_resolve_to_si_scale() -> None:
    """Catches treating all IFC length values as metres."""
    unit = resolve_length_unit(make_ifc_model(length_prefix="MILLI"))
    assert unit.available is True
    assert unit.label == "MILLIMETRE"
    assert unit.scale_to_m == pytest.approx(0.001)
    assert unit.error_code is None


def test_metres_resolve_to_si_scale() -> None:
    """Catches applying millimetre conversion to metre-authored data."""
    unit = resolve_length_unit(make_ifc_model(length_prefix="METRE"))
    assert unit.available is True
    assert unit.label == "METRE"
    assert unit.scale_to_m == pytest.approx(1.0)
    assert unit.error_code is None


def test_model_without_project_units_is_unavailable() -> None:
    """Catches accepting IfcOpenShell's default scale without project units."""
    unit = resolve_length_unit(make_ifc_model(length_prefix=None))
    assert unit.available is False
    assert unit.label is None
    assert unit.scale_to_m is None
    assert unit.error_code == "LENGTHUNIT_MISSING"


def test_conversion_based_foot_length_unit_resolves_without_si_prefix() -> None:
    """Catches assuming every usable LENGTHUNIT has an IfcSIUnit Prefix attribute."""
    model = make_ifc_model(length_prefix=None)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    conversion_factor = model.create_entity(
        "IfcMeasureWithUnit",
        ValueComponent=model.create_entity("IfcLengthMeasure", 0.3048),
        UnitComponent=metre,
    )
    foot = model.create_entity(
        "IfcConversionBasedUnit",
        UnitType="LENGTHUNIT",
        Name="FOOT",
        ConversionFactor=conversion_factor,
    )
    model.by_type("IfcProject")[0].UnitsInContext = model.create_entity(
        "IfcUnitAssignment", Units=(foot,)
    )

    unit = resolve_length_unit(model)

    assert unit.available is True
    assert unit.label == "FOOT"
    assert unit.scale_to_m == pytest.approx(0.3048)


def test_duplicate_declared_length_units_are_unavailable() -> None:
    """Catches taking the library scale when project LENGTHUNIT evidence is ambiguous."""
    model = make_ifc_model(length_prefix="METRE")
    millimetre = model.create_entity(
        "IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE"
    )
    assignment = model.by_type("IfcProject")[0].UnitsInContext
    assignment.Units = (*assignment.Units, millimetre)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.label is None
    assert unit.scale_to_m is None
    assert unit.error_code == "LENGTHUNIT_AMBIGUOUS"
