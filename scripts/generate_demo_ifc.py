"""Generate the deterministic, candidate-authored BIM Preflight demo IFC."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid

ROOT = Path(__file__).parents[1]
DEFAULT_OUTPUT = ROOT / "samples" / "demo-egress-doors.ifc"
_GUID_NAMESPACE = uuid.UUID("48075764-c763-59ce-a62b-93bc4c997459")
_FIXED_TIMESTAMP = "2026-09-03T00:00:00"


def _guid(semantic_key: str) -> str:
    """Return a compressed IFC GlobalId derived from a stable semantic key."""
    return ifcopenshell.guid.compress(uuid.uuid5(_GUID_NAMESPACE, semantic_key).hex)


def _placement(
    model: ifcopenshell.file,
    relative_to: ifcopenshell.entity_instance | None = None,
) -> ifcopenshell.entity_instance:
    origin = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = model.create_entity("IfcAxis2Placement3D", Location=origin)
    return model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=relative_to, RelativePlacement=axis
    )


def _nominal_value(model: ifcopenshell.file, value: bool | str) -> object:
    if type(value) is bool:
        return model.create_entity("IfcBoolean", value)
    return model.create_entity("IfcLabel", value)


def _property_set(
    model: ifcopenshell.file,
    semantic_key: str,
    properties: tuple[tuple[str, bool | str], ...],
) -> ifcopenshell.entity_instance:
    values = tuple(
        model.create_entity(
            "IfcPropertySingleValue",
            Name=name,
            NominalValue=_nominal_value(model, value),
        )
        for name, value in properties
    )
    return model.create_entity(
        "IfcPropertySet",
        GlobalId=_guid(f"pset:{semantic_key}"),
        Name="Pset_DoorCommon",
        HasProperties=values,
    )


def _set_fixed_header(model: ifcopenshell.file) -> None:
    model.header.file_description.description = ("ViewDefinition [ReferenceView]",)
    model.header.file_description.implementation_level = "2;1"
    model.header.file_name.name = "demo-egress-doors.ifc"
    model.header.file_name.time_stamp = _FIXED_TIMESTAMP
    model.header.file_name.author = ("BIM Preflight candidate",)
    model.header.file_name.organization = ("Candidate-authored synthetic test data",)
    model.header.file_name.preprocessor_version = "IfcOpenShell 0.8.5"
    model.header.file_name.originating_system = "BIM Preflight deterministic demo generator"
    model.header.file_name.authorization = "Candidate-authored synthetic test data"


def generate_demo_ifc(output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    """Write the deterministic six-door IFC4 demo and return its path."""
    output = Path(output_path)
    model = ifcopenshell.file(schema="IFC4")
    _set_fixed_header(model)

    millimetre = model.create_entity(
        "IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE"
    )
    units = model.create_entity("IfcUnitAssignment", Units=(millimetre,))
    world_origin = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    world_axis = model.create_entity("IfcAxis2Placement3D", Location=world_origin)
    context = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Model",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=0.00001,
        WorldCoordinateSystem=world_axis,
    )
    project = model.create_entity(
        "IfcProject",
        GlobalId=_guid("spatial:project"),
        Name="BIM Preflight Synthetic Demo",
        Description="Candidate-authored synthetic test data; not a real project model.",
        RepresentationContexts=(context,),
        UnitsInContext=units,
    )
    site_placement = _placement(model)
    site = model.create_entity(
        "IfcSite",
        GlobalId=_guid("spatial:site"),
        Name="Synthetic Site",
        Description="Candidate-authored synthetic test data.",
        ObjectPlacement=site_placement,
        CompositionType="ELEMENT",
    )
    building_placement = _placement(model, site_placement)
    building = model.create_entity(
        "IfcBuilding",
        GlobalId=_guid("spatial:building"),
        Name="Synthetic Building",
        ObjectPlacement=building_placement,
        CompositionType="ELEMENT",
    )
    storey_placement = _placement(model, building_placement)
    storey = model.create_entity(
        "IfcBuildingStorey",
        GlobalId=_guid("spatial:storey"),
        Name="Synthetic Ground Floor",
        ObjectPlacement=storey_placement,
        CompositionType="ELEMENT",
        Elevation=0.0,
    )

    for key, parent, child in (
        ("project-site", project, site),
        ("site-building", site, building),
        ("building-storey", building, storey),
    ):
        model.create_entity(
            "IfcRelAggregates",
            GlobalId=_guid(f"rel:aggregate:{key}"),
            RelatingObject=parent,
            RelatedObjects=(child,),
        )

    cases = (
        (
            "01-width-pass",
            "01 Width Pass",
            1000.0,
            (("FireExit", True), ("FireRating", "60 min"), ("SelfClosing", False)),
        ),
        (
            "02-width-fail",
            "02 Width Fail",
            800.0,
            (("FireExit", True), ("FireRating", "60 min"), ("SelfClosing", True)),
        ),
        (
            "03-metadata-incomplete",
            "03 Metadata Incomplete",
            1000.0,
            (("FireExit", True), ("SelfClosing", True)),
        ),
        (
            "04-explicit-non-egress",
            "04 Explicit Non-Egress",
            1000.0,
            (("FireExit", False), ("FireRating", "60 min"), ("SelfClosing", True)),
        ),
        (
            "05-missing-fire-exit",
            "05 Missing FireExit",
            1000.0,
            (("FireRating", "60 min"), ("SelfClosing", True)),
        ),
        ("06-type-inherited", "06 Type-Inherited Properties", 1000.0, ()),
    )

    doors: list[ifcopenshell.entity_instance] = []
    for semantic_key, name, width, occurrence_properties in cases:
        door = model.create_entity(
            "IfcDoor",
            GlobalId=_guid(f"door:{semantic_key}"),
            Name=name,
            Description="Candidate-authored synthetic test case.",
            ObjectPlacement=_placement(model, storey_placement),
            OverallHeight=2100.0,
            OverallWidth=width,
            PredefinedType="DOOR",
            OperationType="SINGLE_SWING_LEFT",
        )
        doors.append(door)
        if occurrence_properties:
            pset = _property_set(model, semantic_key, occurrence_properties)
            model.create_entity(
                "IfcRelDefinesByProperties",
                GlobalId=_guid(f"rel:occurrence-properties:{semantic_key}"),
                RelatedObjects=(door,),
                RelatingPropertyDefinition=pset,
            )

    inherited_pset = _property_set(
        model,
        "06-type-inherited",
        (("FireExit", True), ("FireRating", "90 min"), ("SelfClosing", False)),
    )
    inherited_type = model.create_entity(
        "IfcDoorType",
        GlobalId=_guid("type:06-type-inherited"),
        Name="Synthetic Inherited Door Type",
        HasPropertySets=(inherited_pset,),
        PredefinedType="DOOR",
        OperationType="SINGLE_SWING_LEFT",
        ParameterTakesPrecedence=False,
    )
    model.create_entity(
        "IfcRelDefinesByType",
        GlobalId=_guid("rel:type:06-type-inherited"),
        RelatedObjects=(doors[-1],),
        RelatingType=inherited_type,
    )
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid("rel:containment:doors-ground-floor"),
        RelatedElements=tuple(doors),
        RelatingStructure=storey,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    generate_demo_ifc(args.output)


if __name__ == "__main__":
    main()
