"""Small, real IFC fixtures used by extraction tests."""

import ifcopenshell
import ifcopenshell.guid


def make_ifc_model(length_prefix: str | None = "MILLI") -> ifcopenshell.file:
    """Create an IFC4 project; ``None`` omits ``UnitsInContext``."""
    model = ifcopenshell.file(schema="IFC4")
    units = None
    if length_prefix is not None:
        prefix = None if length_prefix == "METRE" else length_prefix
        length_unit = model.create_entity(
            "IfcSIUnit", UnitType="LENGTHUNIT", Prefix=prefix, Name="METRE"
        )
        units = model.create_entity("IfcUnitAssignment", Units=(length_unit,))
    model.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        Name="Test project",
        UnitsInContext=units,
    )
    return model


def _nominal_value(model: ifcopenshell.file, value: object) -> object:
    if isinstance(value, bool):
        return model.create_entity("IfcBoolean", value)
    if isinstance(value, str):
        return model.create_entity("IfcLabel", value)
    if isinstance(value, int | float):
        return model.create_entity("IfcReal", float(value))
    return value


def _property_set(
    model: ifcopenshell.file, name: str, properties: dict[str, object]
) -> ifcopenshell.entity_instance:
    values = tuple(
        model.create_entity(
            "IfcPropertySingleValue", Name=key, NominalValue=_nominal_value(model, value)
        )
        for key, value in properties.items()
    )
    return model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        HasProperties=values,
    )


def make_door_model(
    *,
    name: str = "Test Door",
    overall_width: float | None = 900.0,
    occurrence_properties: dict[str, object] | None = None,
    type_properties: dict[str, object] | None = None,
    length_prefix: str | None = "MILLI",
) -> tuple[ifcopenshell.file, ifcopenshell.entity_instance]:
    """Create one IFC4 door with independently assigned occurrence/type Psets."""
    model = make_ifc_model(length_prefix=length_prefix)
    door = model.create_entity(
        "IfcDoor",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        OverallWidth=overall_width,
    )
    if occurrence_properties is not None:
        occurrence_pset = _property_set(model, "Pset_DoorCommon", occurrence_properties)
        model.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=(door,),
            RelatingPropertyDefinition=occurrence_pset,
        )
    if type_properties is not None:
        door_type = model.create_entity(
            "IfcDoorType", GlobalId=ifcopenshell.guid.new(), Name="Test Door Type"
        )
        type_pset = _property_set(model, "Pset_DoorCommon", type_properties)
        door_type.HasPropertySets = (type_pset,)
        model.create_entity(
            "IfcRelDefinesByType",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=(door,),
            RelatingType=door_type,
        )
    return model, door
