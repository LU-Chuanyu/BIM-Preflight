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
