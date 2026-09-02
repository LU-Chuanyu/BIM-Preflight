"""Extract auditable door facts from IFC occurrence and type data."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import ifcopenshell
from ifcopenshell import ifcopenshell_wrapper

from bim_preflight.models import (
    DoorFact,
    Evidence,
    PropertySource,
    ResolvedValue,
    Scalar,
    ValueState,
)
from bim_preflight.units import UnitResolution, resolve_length_unit

_DOOR_COMMON = "Pset_DoorCommon"
_SUPPORTED_PROPERTIES = ("FireExit", "FireRating", "SelfClosing")


@dataclass(frozen=True, slots=True)
class _Observation:
    source: PropertySource
    ref: str
    raw_value: Scalar
    valid: bool
    normalized_value: Scalar


def open_ifc(path: str | Path) -> ifcopenshell.file:
    """Open an IFC file from a local path."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: '{path}'.")

    wrapped = ifcopenshell_wrapper.open(str(path.absolute()))
    status = wrapped.good().value()
    if status == ifcopenshell_wrapper.file_open_status.SUCCESS:
        return ifcopenshell.file(wrapped)
    if status == ifcopenshell_wrapper.file_open_status.READ_ERROR:
        raise OSError("Unable to open file for reading")
    if status == ifcopenshell_wrapper.file_open_status.NO_HEADER:
        raise ifcopenshell.Error("Unable to parse IFC SPF header")
    if status == ifcopenshell_wrapper.file_open_status.UNSUPPORTED_SCHEMA:
        identifiers = wrapped.header().file_schema_py().get_argument(0)
        raise ifcopenshell.SchemaError(f"Unsupported schema: {','.join(identifiers)}")
    if status == ifcopenshell_wrapper.file_open_status.INVALID_SYNTAX:
        raise ifcopenshell.Error("Syntax error during parse, check logs")
    raise ifcopenshell.Error("Unknown IFC parse failure")


def _property_ref(
    door: ifcopenshell.entity_instance,
    source: PropertySource,
    prop: ifcopenshell.entity_instance,
) -> str:
    return f"door.{door.GlobalId}.{source.value.lower()}.{_DOOR_COMMON}.{prop.Name}[{prop.id()}]"


def _raw_nominal_value(prop: ifcopenshell.entity_instance) -> Scalar:
    nominal = prop.NominalValue
    if nominal is None:
        return None
    raw = nominal.wrappedValue
    if isinstance(raw, (bool, int, float, str)) or raw is None:
        return raw
    return str(raw)


def _normalise_property_value(
    prop: ifcopenshell.entity_instance, property_name: str
) -> tuple[bool, Scalar]:
    nominal = prop.NominalValue
    if nominal is None:
        return False, None
    raw = _raw_nominal_value(prop)
    if property_name in {"FireExit", "SelfClosing"}:
        if nominal.is_a("IfcBoolean") and type(raw) is bool:
            return True, raw
        return False, None
    if property_name == "FireRating":
        if isinstance(raw, str) and raw.strip():
            return True, raw
        return False, None
    raise ValueError(f"Unsupported property: {property_name}")


def _properties_from_pset(
    door: ifcopenshell.entity_instance,
    source: PropertySource,
    pset: ifcopenshell.entity_instance,
    property_name: str,
) -> tuple[_Observation, ...]:
    if pset.is_a() != "IfcPropertySet" or pset.Name != _DOOR_COMMON:
        return ()
    observations: list[_Observation] = []
    for prop in pset.HasProperties:
        if prop.Name != property_name:
            continue
        if prop.is_a() != "IfcPropertySingleValue":
            observations.append(
                _Observation(
                    source=source,
                    ref=_property_ref(door, source, prop),
                    raw_value=prop.is_a(),
                    valid=False,
                    normalized_value=None,
                )
            )
            continue
        valid, normalized = _normalise_property_value(prop, property_name)
        observations.append(
            _Observation(
                source=source,
                ref=_property_ref(door, source, prop),
                raw_value=_raw_nominal_value(prop),
                valid=valid,
                normalized_value=normalized,
            )
        )
    return tuple(observations)


def _occurrence_observations(
    door: ifcopenshell.entity_instance, property_name: str
) -> tuple[_Observation, ...]:
    observations: list[_Observation] = []
    for relation in getattr(door, "IsDefinedBy", ()):
        if relation.is_a() != "IfcRelDefinesByProperties":
            continue
        definition = relation.RelatingPropertyDefinition
        property_sets = (
            definition.wrappedValue
            if definition.is_a() == "IfcPropertySetDefinitionSet"
            else (definition,)
        )
        for pset in property_sets:
            observations.extend(
                _properties_from_pset(
                    door, PropertySource.OCCURRENCE, pset, property_name
                )
            )
    return tuple(observations)


def _door_types(door: ifcopenshell.entity_instance) -> tuple[ifcopenshell.entity_instance, ...]:
    types: list[ifcopenshell.entity_instance] = []
    for relation in getattr(door, "IsTypedBy", ()):
        if relation.is_a() == "IfcRelDefinesByType":
            types.append(relation.RelatingType)
    for relation in getattr(door, "IsDefinedBy", ()):
        if relation.is_a() == "IfcRelDefinesByType":
            types.append(relation.RelatingType)
    return tuple(types)


def _type_observations(
    door: ifcopenshell.entity_instance, property_name: str
) -> tuple[_Observation, ...]:
    observations: list[_Observation] = []
    for door_type in _door_types(door):
        if not door_type.is_a("IfcDoorType") and not door_type.is_a("IfcDoorStyle"):
            continue
        for pset in getattr(door_type, "HasPropertySets", ()):
            observations.extend(
                _properties_from_pset(door, PropertySource.TYPE, pset, property_name)
            )
    return tuple(observations)


def _state_at_source(observations: tuple[_Observation, ...]) -> tuple[ValueState, Scalar]:
    if not observations:
        return ValueState.MISSING, None
    if not all(observation.valid for observation in observations):
        return ValueState.INVALID, None
    values = {observation.normalized_value for observation in observations}
    if len(values) != 1:
        return ValueState.INVALID, None
    return ValueState.PRESENT, observations[0].normalized_value


def _resolve_property_detail(
    door: ifcopenshell.entity_instance, property_name: str
) -> tuple[ResolvedValue, tuple[_Observation, ...]]:
    if property_name not in _SUPPORTED_PROPERTIES:
        raise ValueError(f"Unsupported property: {property_name}")
    occurrence = _occurrence_observations(door, property_name)
    type_level = _type_observations(door, property_name)
    occurrence_state, occurrence_value = _state_at_source(occurrence)
    type_state, type_value = _state_at_source(type_level)
    evidence_refs = tuple(item.ref for item in (*occurrence, *type_level))

    if occurrence_state is ValueState.PRESENT:
        return (
            ResolvedValue(
                key=property_name,
                state=ValueState.PRESENT,
                value=occurrence_value,
                source=PropertySource.OCCURRENCE,
                evidence_refs=evidence_refs,
            ),
            (*occurrence, *type_level),
        )
    if occurrence_state is ValueState.INVALID:
        return (
            ResolvedValue(
                key=property_name,
                state=ValueState.INVALID,
                value=None,
                source=PropertySource.OCCURRENCE,
                evidence_refs=evidence_refs,
            ),
            (*occurrence, *type_level),
        )
    if type_state is ValueState.PRESENT:
        return (
            ResolvedValue(
                key=property_name,
                state=ValueState.PRESENT,
                value=type_value,
                source=PropertySource.TYPE,
                evidence_refs=evidence_refs,
            ),
            (*occurrence, *type_level),
        )
    if type_state is ValueState.INVALID:
        return (
            ResolvedValue(
                key=property_name,
                state=ValueState.INVALID,
                value=None,
                source=PropertySource.TYPE,
                evidence_refs=evidence_refs,
            ),
            (*occurrence, *type_level),
        )
    return (
        ResolvedValue(
            key=property_name,
            state=ValueState.MISSING,
            value=None,
            source=PropertySource.NONE,
            evidence_refs=(),
        ),
        (),
    )


def resolve_property(door: ifcopenshell.entity_instance, property_name: str) -> ResolvedValue:
    """Resolve one Pset_DoorCommon property with occurrence/type provenance."""
    return _resolve_property_detail(door, property_name)[0]


def _property_evidence(observations: tuple[_Observation, ...], property_name: str) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            ref=observation.ref,
            label=f"{_DOOR_COMMON}.{property_name}",
            raw_value=observation.raw_value,
            normalized_value=observation.normalized_value,
            unit=None,
            source=observation.source.value.lower(),
        )
        for observation in observations
    )


def _width_values(door: ifcopenshell.entity_instance, unit: UnitResolution) -> tuple[float | None, float | None]:
    width = door.OverallWidth
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        return None, None
    raw_width = float(width)
    if not isfinite(raw_width) or raw_width <= 0 or not unit.available or unit.scale_to_m is None:
        return raw_width, None
    return raw_width, raw_width * unit.scale_to_m


def _width_evidence(
    door: ifcopenshell.entity_instance,
    raw_width: float | None,
    width_m: float | None,
    unit: UnitResolution,
) -> tuple[Evidence, ...]:
    evidence: list[Evidence] = []
    if unit.available and unit.evidence_ref is not None:
        evidence.append(
            Evidence(
                ref=unit.evidence_ref,
                label="LENGTHUNIT",
                raw_value=unit.label,
                normalized_value=unit.scale_to_m,
                unit="METRE",
                source="project",
            )
        )
    evidence.append(
        Evidence(
            ref=f"door.{door.GlobalId}.attribute.OverallWidth",
            label="OverallWidth",
            raw_value=raw_width,
            normalized_value=width_m,
            unit=unit.label,
            source="occurrence",
        )
    )
    return tuple(evidence)


def extract_door_facts(model: ifcopenshell.file) -> tuple[DoorFact, ...]:
    """Extract frozen facts for every IFC door occurrence in a model."""
    unit = resolve_length_unit(model)
    facts: list[DoorFact] = []
    for door in model.by_type("IfcDoor"):
        resolved: dict[str, ResolvedValue] = {}
        evidence: list[Evidence] = []
        for property_name in _SUPPORTED_PROPERTIES:
            value, observations = _resolve_property_detail(door, property_name)
            resolved[property_name] = value
            evidence.extend(_property_evidence(observations, property_name))
        raw_width, width_m = _width_values(door, unit)
        evidence.extend(_width_evidence(door, raw_width, width_m, unit))
        facts.append(
            DoorFact(
                element_global_id=door.GlobalId,
                display_name=door.Name or "",
                ifc_schema=model.schema,
                fire_exit=resolved["FireExit"],
                fire_rating=resolved["FireRating"],
                self_closing=resolved["SelfClosing"],
                overall_width_raw=raw_width,
                overall_width_m=width_m,
                evidence=tuple(evidence),
            )
        )
    return tuple(facts)
