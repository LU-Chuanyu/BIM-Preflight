"""Credential-free Streamlit integration tests for the dashboard."""

from pathlib import Path

import pytest
from ifc_factory import make_door_model
from streamlit.testing.v1 import AppTest

from bim_preflight.engine import IfcLoadError

APP_PATH = Path(__file__).parents[1] / "app.py"
NOTICE = (
    "Screening only. IfcDoor.OverallWidth is a model-declared door-opening width proxy, not a "
    "certified clear-opening measurement or a statutory compliance conclusion."
)


def _app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return AppTest.from_file(APP_PATH, default_timeout=10).run()


def _ifc_bytes(tmp_path: Path, *, width: float = 900.0) -> bytes:
    path = tmp_path / "upload.ifc"
    model, _door = make_door_model(
        overall_width=width,
        occurrence_properties={"FireExit": True, "FireRating": "60 min", "SelfClosing": False},
    )
    model.write(str(path))
    return path.read_bytes()


def _upload_and_run(app: AppTest, data: bytes) -> AppTest:
    app.file_uploader(key="ifc_upload").set_value(("doors.ifc", data, "application/x-step"))
    app.run()
    app.button(key="run_preflight").click()
    return app.run()


def _metric_value(app: AppTest, label: str) -> str:
    return next(metric.value for metric in app.metric if metric.label == label)


def test_empty_state_is_credential_free_and_keeps_the_exact_screening_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an import-time AI call or an empty state that looks like a result."""
    app = _app(monkeypatch)

    assert app.exception == []
    assert app.file_uploader(key="ifc_upload").label == "Upload IFC"
    assert app.number_input(key="threshold_mm").value == 900
    assert any(NOTICE == info.value for info in app.info)
    assert app.dataframe == []
    assert all(button.disabled for button in app.button if button.key.startswith("ai_"))


def test_real_ifc_upload_renders_results_and_a_unique_finding_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a JSON-only happy path or ambiguous evidence selection labels."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))

    assert app.exception == []
    assert _metric_value(app, "PASS") == "2"
    selector = app.selectbox(key="finding_selector")
    assert "R1_EGRESS_DOOR_OPENING_WIDTH" in selector.value
    assert "GlobalId" in selector.value


def test_rerunning_with_a_higher_threshold_changes_the_authoritative_r1_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches rendering an old report after a configuration rerun."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path, width=900.0))
    assert _metric_value(app, "PASS") == "2"

    app.number_input(key="threshold_mm").set_value(950)
    app.button(key="run_preflight").click()
    app.run()

    assert _metric_value(app, "FAIL") == "1"


def test_invalid_ifc_is_rendered_as_a_typed_file_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches parser exceptions escaping into the Streamlit page."""
    app = _upload_and_run(_app(monkeypatch), b"this is not IFC")

    assert app.exception == []
    assert any(error.value == "Unable to load IFC file." for error in app.error)


def test_missing_demo_file_is_a_visible_unavailable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches a fake bundled model or an unhandled missing sample path."""
    app = _app(monkeypatch)
    app.radio(key="input_source").set_value("Bundled synthetic demo")
    app.button(key="run_preflight").click()
    app.run()

    assert app.exception == []
    assert any("Bundled synthetic demo is not available yet." == info.value for info in app.info)


def test_missing_key_disables_actions_without_constructing_an_explanation_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a credential-free rerun reaching the optional explanation adapter."""
    calls: list[object] = []

    def forbidden_request(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("request_explanation must not run without a credential")

    monkeypatch.setattr("bim_preflight.explain.request_explanation", forbidden_request)
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))

    assert calls == []
    assert all(button.disabled for button in app.button if button.key.startswith("ai_"))


def test_finding_selection_uses_the_requested_rule_and_global_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches a selector that identifies a finding only by a duplicated display name."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))
    selector = app.selectbox(key="finding_selector")
    metadata_label = next(value for value in selector.options if "R2_" in value)
    selector.set_value(metadata_label)
    app.run()

    assert app.selectbox(key="finding_selector").value == metadata_label
    assert "R2_EGRESS_DOOR_METADATA_COMPLETENESS" in metadata_label
    assert "GlobalId=" in metadata_label


def test_upload_temporary_file_is_unlinked_when_analysis_fails(tmp_path: Path) -> None:
    """Catches uploaded IFC files accumulating after a typed load failure."""
    from app import analyse_uploaded_bytes

    seen: list[Path] = []

    def failing_analyser(path: Path, threshold_m: float) -> object:
        seen.append(path)
        assert path.suffix == ".ifc"
        raise IfcLoadError("Unable to load IFC file.")

    with pytest.raises(IfcLoadError):
        analyse_uploaded_bytes(b"invalid", 0.9, analyser=failing_analyser)
    assert seen and not seen[0].exists()


def test_methods_copy_keeps_r2_in_its_metadata_only_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches a UI claim that turns metadata presence into a fire-code conclusion."""
    app = _app(monkeypatch)
    copy = " ".join(markdown.value for markdown in app.markdown)

    assert "R2 checks metadata presence only" in copy
    assert "SelfClosing=false counts as present" in copy
    assert "No legal, fire-code, or installed-performance conclusion" in copy
