"""Explicit IFC project-length-unit resolution."""

from dataclasses import dataclass
from math import isfinite

import ifcopenshell

_SI_PREFIX_SCALE = {
    None: 1.0,
    "EXA": 1e18,
    "PETA": 1e15,
    "TERA": 1e12,
    "GIGA": 1e9,
    "MEGA": 1e6,
    "KILO": 1e3,
    "HECTO": 1e2,
    "DECA": 1e1,
    "DECI": 1e-1,
    "CENTI": 1e-2,
    "MILLI": 1e-3,
    "MICRO": 1e-6,
    "NANO": 1e-9,
    "PICO": 1e-12,
    "FEMTO": 1e-15,
    "ATTO": 1e-18,
}


@dataclass(frozen=True, slots=True)
class UnitResolution:
    available: bool
    label: str | None
    scale_to_m: float | None
    evidence_ref: str | None
    error_code: str | None


def _unavailable(error_code: str) -> UnitResolution:
    return UnitResolution(
        available=False,
        label=None,
        scale_to_m=None,
        evidence_ref=None,
        error_code=error_code,
    )


def _unit_label(unit: ifcopenshell.entity_instance) -> str:
    if unit.is_a("IfcSIUnit"):
        return f"{unit.Prefix or ''}{unit.Name}"
    return str(unit.Name)


def _verified_scale_to_m(unit: ifcopenshell.entity_instance) -> float | None:
    """Return a scale only for a scale-only length chain ending at SI metre."""
    scale = 1.0
    seen: set[int] = set()
    current = unit

    while True:
        entity_id = current.id()
        if entity_id in seen:
            return None
        seen.add(entity_id)

        representation = current.is_a()
        if representation == "IfcSIUnit":
            if current.UnitType != "LENGTHUNIT" or current.Name != "METRE":
                return None
            prefix_scale = _SI_PREFIX_SCALE.get(current.Prefix)
            if prefix_scale is None:
                return None
            scale *= prefix_scale
            return scale if isfinite(scale) and scale > 0 else None

        # IfcConversionBasedUnitWithOffset is a subtype according to is_a(name),
        # so the exact representation check is required to reject affine units.
        if representation != "IfcConversionBasedUnit" or current.UnitType != "LENGTHUNIT":
            return None
        conversion = current.ConversionFactor
        if conversion is None:
            return None
        value_component = conversion.ValueComponent
        raw_factor = getattr(value_component, "wrappedValue", None)
        if type(raw_factor) not in {int, float}:
            return None
        factor = float(raw_factor)
        if not isfinite(factor) or factor <= 0:
            return None
        scale *= factor
        if not isfinite(scale) or scale <= 0:
            return None
        current = conversion.UnitComponent
        if not isinstance(current, ifcopenshell.entity_instance):
            return None


def resolve_length_unit(model: ifcopenshell.file) -> UnitResolution:
    """Resolve exactly one declared project length unit, without defaults."""
    projects = model.by_type("IfcProject")
    if len(projects) != 1:
        return _unavailable("PROJECT_MISSING" if not projects else "PROJECT_AMBIGUOUS")

    assignment = projects[0].UnitsInContext
    if assignment is None:
        return _unavailable("LENGTHUNIT_MISSING")
    length_units = tuple(
        unit for unit in assignment.Units if getattr(unit, "UnitType", None) == "LENGTHUNIT"
    )
    if len(length_units) != 1:
        return _unavailable("LENGTHUNIT_MISSING" if not length_units else "LENGTHUNIT_AMBIGUOUS")

    unit = length_units[0]
    try:
        scale_to_m = _verified_scale_to_m(unit)
    except (AttributeError, RuntimeError, TypeError):
        scale_to_m = None
    if scale_to_m is None:
        return _unavailable("LENGTHUNIT_UNSUPPORTED")

    return UnitResolution(
        available=True,
        label=_unit_label(unit),
        scale_to_m=scale_to_m,
        evidence_ref=f"project.{projects[0].GlobalId}.UnitsInContext.Units[{unit.id()}]",
        error_code=None,
    )
