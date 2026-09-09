"""End-to-end checks for the reproducible IFC release samples."""

from hashlib import sha256
from pathlib import Path

import ifcopenshell
import ifcopenshell.validate
from streamlit.testing.v1 import AppTest

from bim_preflight.engine import analyse_ifc
from bim_preflight.models import EngineStatus, PropertySource
from bim_preflight.rules import METADATA_RULE_ID, WIDTH_RULE_ID
from scripts.generate_demo_ifc import generate_demo_ifc

ROOT = Path(__file__).parents[1]
DEMO_PATH = ROOT / "samples" / "demo-egress-doors.ifc"
OFFICIAL_PATH = ROOT / "samples" / "official" / "Building-Architecture.ifc"
OFFICIAL_LICENSE_PATH = ROOT / "samples" / "official" / "LICENSE-CC-BY-4.0.txt"
APP_PATH = ROOT / "app.py"
README_PATH = ROOT / "README.md"
NOTICE_PATH = ROOT / "NOTICE.md"
DEMO_SCRIPT_PATH = ROOT / "docs" / "demo-script.md"
DEMO_SHA256 = "b2cacb9e6c97b21a814c56fd787533155faaef084d9e424141302375e6d3bf27"
OFFICIAL_SHA256 = "3ff9b10bd00c7b96dded51e7ca5a6b69efbea38b049adcdd05fcd247de7e70d5"
OFFICIAL_LICENSE_SHA256 = "3e20c50b6edfdb4be207f64495586115d0574c8394538109d74f79e1d8976d18"

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

    model = ifcopenshell.open(str(DEMO_PATH))
    door06 = next(
        door for door in model.by_type("IfcDoor") if door.Name == "06 Type-Inherited Properties"
    )
    assert door06.PredefinedType is None
    assert door06.OperationType is None
    assert len(door06.IsTypedBy) == 1
    inherited_type = door06.IsTypedBy[0].RelatingType
    assert inherited_type.PredefinedType == "DOOR"
    assert inherited_type.OperationType == "SINGLE_SWING_LEFT"


def test_generator_reproduces_committed_ifc_bytes_and_fixed_header(tmp_path: Path) -> None:
    """Catches random GlobalIds, timestamps, or output-path leakage in generated STEP bytes."""
    regenerated = tmp_path / "different-output-name.ifc"
    generate_demo_ifc(regenerated)

    assert regenerated.read_bytes() == DEMO_PATH.read_bytes()
    model = ifcopenshell.open(str(regenerated))
    assert model.header.file_name.name == "demo-egress-doors.ifc"
    assert model.header.file_name.time_stamp == "2026-09-03T00:00:00"
    assert model.header.file_name.author == ("BIM Preflight project generator",)
    assert model.header.file_name.organization == (
        "BIM Preflight project-generated synthetic test data",
    )
    assert model.header.file_name.authorization == (
        "BIM Preflight project-generated synthetic test data"
    )
    assert model.by_type("IfcProject")[0].Description == (
        "Project-generated synthetic test data; not a real project model."
    )
    assert model.by_type("IfcSite")[0].Description == (
        "Project-generated synthetic test data."
    )
    assert {door.Description for door in model.by_type("IfcDoor")} == {
        "Project-generated synthetic test case."
    }
    assert b"candidate-authored" not in regenerated.read_bytes().lower()
    roots = model.by_type("IfcRoot")
    assert len({root.GlobalId for root in roots}) == len(roots)
    assert all(len(root.GlobalId) == 22 for root in roots)


def test_release_truth_language_hash_and_docs_remain_synchronised() -> None:
    """Catches authorship overclaims, stale hashes, or a demo script that shows wrong evidence."""
    release_paths = (
        ROOT / "scripts" / "generate_demo_ifc.py",
        DEMO_PATH,
        APP_PATH,
        README_PATH,
        NOTICE_PATH,
        DEMO_SCRIPT_PATH,
    )
    assert all(b"candidate-authored" not in path.read_bytes().lower() for path in release_paths)
    assert sha256(DEMO_PATH.read_bytes()).hexdigest() == DEMO_SHA256

    readme = README_PATH.read_text()
    normalised_readme = " ".join(readme.split())
    assert "AI assisted this prototype's implementation and review." in normalised_readme
    assert "deterministic tests and checked-in evidence" in normalised_readme
    assert DEMO_SHA256 in readme
    assert DEMO_SHA256 in NOTICE_PATH.read_text()

    demo_script = " ".join(DEMO_SCRIPT_PATH.read_text().split())
    assert "selecting the R2 result for `06 Type-Inherited Properties`" in demo_script
    assert "The primary product is the deterministic web tool" in demo_script
    assert "optional AI explanation is experimental" in demo_script

def test_demo_ifc_passes_schema_and_express_validation() -> None:
    """Catches a generated sample that parses but violates IFC4 schema or EXPRESS rules."""
    model = ifcopenshell.open(str(DEMO_PATH))
    logger = ifcopenshell.validate.json_logger()

    ifcopenshell.validate.validate(model, logger, express_rules=True)

    assert logger.statements == []


def test_official_buildingsmart_sample_is_parser_smoke_data_only() -> None:
    """Catches a missing, substituted, or unreadable official IFC parser fixture."""
    model = ifcopenshell.open(str(OFFICIAL_PATH))

    assert model.schema == "IFC4"
    assert len(model.by_type("IfcProject")) == 1
    assert len(model.by_type("IfcBuilding")) >= 1


def test_official_sample_and_license_match_documented_sha256() -> None:
    """Catches offline modification of either byte-exact attributed upstream artifact."""
    assert sha256(OFFICIAL_PATH.read_bytes()).hexdigest() == OFFICIAL_SHA256
    assert sha256(OFFICIAL_LICENSE_PATH.read_bytes()).hexdigest() == OFFICIAL_LICENSE_SHA256


def test_demo_source_hides_upload_widget_and_identifies_bundled_data(monkeypatch) -> None:
    """Catches an irrelevant disabled uploader obscuring the selected bundled workflow."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(APP_PATH, default_timeout=15).run()

    app.radio(key="input_source").set_value("Bundled synthetic demo")
    app.run()

    assert app.exception == []
    assert app.file_uploader == []
    assert any(
        caption.value == "Using the bundled project-generated synthetic IFC4 demo with six doors."
        for caption in app.caption
    )
    assert any(
        info.value == "Select Run preflight to analyse the bundled synthetic demo."
        for info in app.info
    )
    assert all("Upload an IFC file" not in info.value for info in app.info)


def test_bundled_demo_runs_in_streamlit_without_ai_credentials(monkeypatch) -> None:
    """Catches a packaged demo that loses its compact review-first dashboard."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(APP_PATH, default_timeout=15).run()
    app.radio(key="input_source").set_value("Bundled synthetic demo")
    app.button(key="run_preflight").click()
    app.run()

    assert app.exception == []
    assert app.json == []
    metrics = {metric.label: metric.value for metric in app.metric}
    assert {metrics[label] for label in ("IFC schema", "Project unit", "Doors")} == {
        "IFC4",
        "MILLIMETRE",
        "6",
    }
    assert "Source" not in metrics
    assert "Screening threshold" not in metrics
    assert any(caption.value == "Source: Bundled synthetic demo" for caption in app.caption)
    assert any(
        caption.value == "Screening threshold: Demo project screening profile: 900 mm"
        for caption in app.caption
    )
    assert {label: metrics[label] for label in ("PASS", "FAIL", "NOT_EVALUABLE", "NOT_APPLICABLE", "ERROR")} == {
        "PASS": "6",
        "FAIL": "2",
        "NOT_EVALUABLE": "2",
        "NOT_APPLICABLE": "2",
        "ERROR": "0",
    }
    assert any(
        "2 failed checks require resolution; 2 need additional information." in markdown.value
        for markdown in app.markdown
    )
    result_table = app.dataframe[0].value
    assert len(result_table) == 12
    assert result_table.iloc[0]["check"] == "Opening width"
    assert result_table.iloc[0]["status"] == "FAIL"
    assert result_table.iloc[0]["element_name"] == "02 Width Fail"
    assert result_table.iloc[0]["rule_id"] == WIDTH_RULE_ID
    assert app.selectbox(key="finding_selector").value.endswith("02 Width Fail")
    assert app.selectbox(key="finding_selector").value.startswith(WIDTH_RULE_ID)
