"""End-to-end checks for the reproducible IFC release samples."""

import json
from pathlib import Path

import ifcopenshell
from streamlit.testing.v1 import AppTest

from bim_preflight.engine import analyse_ifc
from bim_preflight.models import EngineStatus, PropertySource
from bim_preflight.rules import METADATA_RULE_ID, WIDTH_RULE_ID
from scripts.generate_demo_ifc import generate_demo_ifc

ROOT = Path(__file__).parents[1]
DEMO_PATH = ROOT / "samples" / "demo-egress-doors.ifc"
OFFICIAL_PATH = ROOT / "samples" / "official" / "Building-Architecture.ifc"
APP_PATH = ROOT / "app.py"

EXPECTED_RESULTS = {
    "01 Width Pass": {
        WIDTH_RULE_ID: (EngineStatus.PASS, "WIDTH_MEETS_THRESHOLD"),
        METADATA_RULE_ID: (EngineStatus.PASS, "METADATA_COMPLETE"),
    },
    "02 Width Fail": {
        WIDTH_RULE_ID: (EngineStatus.FAIL, "WIDTH_BELOW_THRESHOLD"),
        METADATA_RULE_ID: (EngineStatus.PASS, "METADATA_COMPLETE"),
    },
    "03 Metadata Incomplete": {
        WIDTH_RULE_ID: (EngineStatus.PASS, "WIDTH_MEETS_THRESHOLD"),
        METADATA_RULE_ID: (EngineStatus.FAIL, "FIRE_RATING_MISSING"),
    },
    "04 Explicit Non-Egress": {
        WIDTH_RULE_ID: (EngineStatus.NOT_APPLICABLE, "FIRE_EXIT_FALSE"),
        METADATA_RULE_ID: (EngineStatus.NOT_APPLICABLE, "FIRE_EXIT_FALSE"),
    },
    "05 Missing FireExit": {
        WIDTH_RULE_ID: (EngineStatus.NOT_EVALUABLE, "FIRE_EXIT_UNRESOLVED"),
        METADATA_RULE_ID: (EngineStatus.NOT_EVALUABLE, "FIRE_EXIT_UNRESOLVED"),
    },
    "06 Type-Inherited Properties": {
        WIDTH_RULE_ID: (EngineStatus.PASS, "WIDTH_MEETS_THRESHOLD"),
        METADATA_RULE_ID: (EngineStatus.PASS, "METADATA_COMPLETE"),
    },
}


def test_demo_ifc_has_exact_six_case_rule_matrix_and_type_provenance() -> None:
    """Catches sample drift that stops exercising a required engine branch."""
    report = analyse_ifc(DEMO_PATH, threshold_m=0.9)

    assert report.model_info.schema == "IFC4"
    assert report.model_info.length_unit == "MILLIMETRE"
    assert report.model_info.door_count == 6
    assert len(report.results) == 12

    names_by_id = {door.element_global_id: door.display_name for door in report.door_facts}
    actual = {
        names_by_id[door_id]: {
            result.rule_id: (result.status, result.finding_code)
            for result in report.results
            if result.element_global_id == door_id
        }
        for door_id in names_by_id
    }
    assert actual == EXPECTED_RESULTS

    doors = {door.display_name: door for door in report.door_facts}
    assert doors["01 Width Pass"].overall_width_raw == 1000.0
    assert doors["01 Width Pass"].overall_width_m == 1.0
    assert doors["01 Width Pass"].self_closing.value is False
    assert doors["02 Width Fail"].overall_width_raw == 800.0
    assert doors["03 Metadata Incomplete"].fire_rating.value is None
    assert doors["06 Type-Inherited Properties"].fire_exit.source is PropertySource.TYPE
    assert doors["06 Type-Inherited Properties"].fire_rating.source is PropertySource.TYPE
    assert doors["06 Type-Inherited Properties"].self_closing.source is PropertySource.TYPE
    assert all(
        ".type.Pset_DoorCommon." in reference
        for resolved in (
            doors["06 Type-Inherited Properties"].fire_exit,
            doors["06 Type-Inherited Properties"].fire_rating,
            doors["06 Type-Inherited Properties"].self_closing,
        )
        for reference in resolved.evidence_refs
    )


def test_generator_reproduces_committed_ifc_bytes_and_fixed_header(tmp_path: Path) -> None:
    """Catches random GlobalIds, timestamps, or output-path leakage in generated STEP bytes."""
    regenerated = tmp_path / "different-output-name.ifc"
    generate_demo_ifc(regenerated)

    assert regenerated.read_bytes() == DEMO_PATH.read_bytes()
    model = ifcopenshell.open(str(regenerated))
    assert model.header.file_name.name == "demo-egress-doors.ifc"
    assert model.header.file_name.time_stamp == "2026-09-03T00:00:00"
    roots = model.by_type("IfcRoot")
    assert len({root.GlobalId for root in roots}) == len(roots)
    assert all(len(root.GlobalId) == 22 for root in roots)


def test_official_buildingsmart_sample_is_parser_smoke_data_only() -> None:
    """Catches a missing, substituted, or unreadable official IFC parser fixture."""
    model = ifcopenshell.open(str(OFFICIAL_PATH))

    assert model.schema == "IFC4"
    assert len(model.by_type("IfcProject")) == 1
    assert len(model.by_type("IfcBuilding")) >= 1


def test_bundled_demo_runs_in_streamlit_without_ai_credentials(monkeypatch) -> None:
    """Catches a packaged sample that cannot complete the visible two-rule workflow."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(APP_PATH, default_timeout=15).run()
    app.radio(key="input_source").set_value("Bundled synthetic demo")
    app.button(key="run_preflight").click()
    app.run()

    assert app.exception == []
    summary = next(json.loads(node.value) for node in app.json if "door_count" in node.value)
    assert summary["schema"] == "IFC4"
    assert summary["project_length_unit"] == "MILLIMETRE"
    assert summary["door_count"] == 6
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics == {
        "PASS": "6",
        "FAIL": "2",
        "NOT_EVALUABLE": "2",
        "NOT_APPLICABLE": "2",
        "ERROR": "0",
    }
