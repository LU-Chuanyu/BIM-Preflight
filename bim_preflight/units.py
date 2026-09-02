"""Explicit IFC project-length-unit resolution."""

from dataclasses import dataclass
from math import isfinite

import ifcopenshell
import ifcopenshell.util.unit


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
        scale_to_m = float(ifcopenshell.util.unit.calculate_unit_scale(model, "LENGTHUNIT"))
    except (TypeError, ValueError, RuntimeError):
        return _unavailable("LENGTHUNIT_UNSUPPORTED")
    if not isfinite(scale_to_m) or scale_to_m <= 0:
        return _unavailable("LENGTHUNIT_UNSUPPORTED")

    return UnitResolution(
        available=True,
        label=_unit_label(unit),
        scale_to_m=scale_to_m,
        evidence_ref=f"project.{projects[0].GlobalId}.UnitsInContext.Units[{unit.id()}]",
        error_code=None,
    )
