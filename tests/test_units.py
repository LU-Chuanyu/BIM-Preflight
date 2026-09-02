import ifcopenshell
import ifcopenshell.validate
import pytest
from ifc_factory import make_ifc_model

from bim_preflight.units import resolve_length_unit


def _length_dimensions(model: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return model.create_entity(
        "IfcDimensionalExponents",
        LengthExponent=1,
        MassExponent=0,
        TimeExponent=0,
        ElectricCurrentExponent=0,
        ThermodynamicTemperatureExponent=0,
        AmountOfSubstanceExponent=0,
        LuminousIntensityExponent=0,
    )


def _assign_length_unit(
    model: ifcopenshell.file, unit: ifcopenshell.entity_instance
) -> None:
    model.by_type("IfcProject")[0].UnitsInContext = model.create_entity(
        "IfcUnitAssignment", Units=(unit,)
    )


def _assert_schema_and_express_valid(model: ifcopenshell.file) -> None:
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert logger.statements == []


def _conversion_unit(
    model: ifcopenshell.file,
    *,
    name: str,
    factor: object,
    terminal: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    conversion_factor = model.create_entity(
        "IfcMeasureWithUnit",
        ValueComponent=factor,
        UnitComponent=terminal,
    )
    return model.create_entity(
        "IfcConversionBasedUnit",
        Dimensions=_length_dimensions(model),
        UnitType="LENGTHUNIT",
        Name=name,
        ConversionFactor=conversion_factor,
    )


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


def test_schema_valid_context_dependent_length_unit_is_explicitly_unsupported() -> None:
    """Catches an opaque project-defined unit being silently treated as metres."""
    model = make_ifc_model(length_prefix=None)
    custom = model.create_entity(
        "IfcContextDependentUnit",
        Dimensions=_length_dimensions(model),
        UnitType="LENGTHUNIT",
        Name="CUSTOM_LENGTH",
    )
    _assign_length_unit(model, custom)
    _assert_schema_and_express_valid(model)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.scale_to_m is None
    assert unit.error_code == "LENGTHUNIT_UNSUPPORTED"


def test_schema_valid_offset_conversion_unit_is_not_treated_as_a_scale_only_unit() -> None:
    """Catches subtype matching accepting an affine unit as IfcConversionBasedUnit."""
    model = make_ifc_model(length_prefix=None)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    conversion_factor = model.create_entity(
        "IfcMeasureWithUnit",
        ValueComponent=model.create_entity("IfcLengthMeasure", 0.3048),
        UnitComponent=metre,
    )
    offset = model.create_entity(
        "IfcConversionBasedUnitWithOffset",
        Dimensions=_length_dimensions(model),
        UnitType="LENGTHUNIT",
        Name="OFFSET_LENGTH",
        ConversionFactor=conversion_factor,
        ConversionOffset=2.0,
    )
    assert offset.is_a("IfcConversionBasedUnit") is True
    assert offset.is_a() == "IfcConversionBasedUnitWithOffset"
    _assign_length_unit(model, offset)
    _assert_schema_and_express_valid(model)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.scale_to_m is None
    assert unit.error_code == "LENGTHUNIT_UNSUPPORTED"


def test_nested_finite_positive_conversion_chain_ending_at_metre_resolves() -> None:
    """Catches rejecting a valid scale-only chain instead of verifying its SI terminal."""
    model = make_ifc_model(length_prefix=None)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    foot = _conversion_unit(
        model,
        name="FOOT",
        factor=model.create_entity("IfcLengthMeasure", 0.3048),
        terminal=metre,
    )
    inch = _conversion_unit(
        model,
        name="INCH",
        factor=model.create_entity("IfcLengthMeasure", 1 / 12),
        terminal=foot,
    )
    _assign_length_unit(model, inch)
    _assert_schema_and_express_valid(model)

    unit = resolve_length_unit(model)

    assert unit.available is True
    assert unit.label == "INCH"
    assert unit.scale_to_m == pytest.approx(0.0254)


@pytest.mark.parametrize(
    "factor",
    [0.0, -1.0, "not numeric", True],
    ids=["zero", "negative", "text", "boolean"],
)
def test_conversion_factor_must_be_finite_positive_numeric(factor: object) -> None:
    """Catches accepting a factor that cannot define a safe length scale."""
    model = make_ifc_model(length_prefix=None)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    if isinstance(factor, str):
        value = model.create_entity("IfcLabel", factor)
    elif isinstance(factor, bool):
        value = model.create_entity("IfcBoolean", factor)
    else:
        value = model.create_entity("IfcLengthMeasure", factor)
    suspect = _conversion_unit(model, name="SUSPECT", factor=value, terminal=metre)
    _assign_length_unit(model, suspect)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.scale_to_m is None
    assert unit.error_code == "LENGTHUNIT_UNSUPPORTED"


def test_conversion_chain_must_end_at_length_metre() -> None:
    """Catches applying a numeric factor whose terminal is not the verified metre SI unit."""
    model = make_ifc_model(length_prefix=None)
    radian = model.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN")
    suspect = _conversion_unit(
        model,
        name="SUSPECT",
        factor=model.create_entity("IfcLengthMeasure", 1.0),
        terminal=radian,
    )
    _assign_length_unit(model, suspect)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.error_code == "LENGTHUNIT_UNSUPPORTED"


def test_conversion_unit_cycle_is_unsupported() -> None:
    """Catches recursive conversion chains looping instead of failing closed."""
    model = make_ifc_model(length_prefix=None)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    first = _conversion_unit(
        model,
        name="FIRST",
        factor=model.create_entity("IfcLengthMeasure", 2.0),
        terminal=metre,
    )
    second = _conversion_unit(
        model,
        name="SECOND",
        factor=model.create_entity("IfcLengthMeasure", 3.0),
        terminal=first,
    )
    first.ConversionFactor.UnitComponent = second
    _assign_length_unit(model, first)

    unit = resolve_length_unit(model)

    assert unit.available is False
    assert unit.error_code == "LENGTHUNIT_UNSUPPORTED"
