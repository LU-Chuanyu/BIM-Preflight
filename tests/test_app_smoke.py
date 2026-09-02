"""Credential-free Streamlit integration tests for the dashboard."""

from pathlib import Path
from shutil import copyfile
from typing import Self

import pytest
from ifc_factory import make_door_model, make_ifc_model
from streamlit.testing.v1 import AppTest

from bim_preflight.engine import IfcLoadError
from bim_preflight.explain import ExplanationDraft

APP_PATH = Path(__file__).parents[1] / "app.py"
NOTICE = (
    "Screening only. IfcDoor.OverallWidth is a model-declared door-opening width proxy, not a "
    "certified clear-opening measurement or a statutory compliance conclusion."
)


def _app(monkeypatch: pytest.MonkeyPatch, *, with_api_key: bool = False) -> AppTest:
    if with_api_key:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    else:
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


def _zero_door_ifc_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "zero-doors.ifc"
    make_ifc_model().write(str(path))
    return path.read_bytes()


def _upload_and_run(app: AppTest, data: bytes, *, name: str = "doors.ifc") -> AppTest:
    app.file_uploader(key="ifc_upload").set_value((name, data, "application/x-step"))
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


def test_valid_zero_door_ifc_renders_summary_without_finding_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an empty result list reaching a selector that requires one option."""
    app = _upload_and_run(_app(monkeypatch), _zero_door_ifc_bytes(tmp_path))

    assert app.exception == []
    assert any(
        info.value == "No IfcDoor occurrences were found; no rules were evaluated." for info in app.info
    )
    assert app.selectbox == []
    assert all(not button.key.startswith("ai_") for button in app.button)


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
    assert any(
        "Selected project screening threshold: 950 mm" in str(node.value) for node in app.json
    )


def test_threshold_labels_reserve_the_demo_profile_for_its_900_mm_demo_value() -> None:
    """Catches upload or custom-demo values being presented as the fixed demonstration profile."""
    from app import _threshold_label

    assert _threshold_label("Upload IFC", 0.9) == "Selected project screening threshold: 900 mm"
    assert _threshold_label("Upload IFC", 0.95) == "Selected project screening threshold: 950 mm"
    assert _threshold_label("Bundled synthetic demo", 0.9) == "Demo project screening profile: 900 mm"
    assert (
        _threshold_label("Bundled synthetic demo", 0.95)
        == "Selected project screening threshold: 950 mm"
    )


def test_changing_threshold_without_run_clears_the_previous_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches controls claiming a different threshold than the stored report used."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))
    assert app.dataframe

    app.number_input(key="threshold_mm").set_value(950)
    app.run()

    assert app.dataframe == []
    assert any("Upload an IFC file and select Run preflight to start." == info.value for info in app.info)


def test_switching_source_or_replacing_same_named_upload_clears_the_previous_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches stale analysis surviving an input identity change before the next run."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path, width=900.0))
    app.file_uploader(key="ifc_upload").set_value(
        ("doors.ifc", _ifc_bytes(tmp_path, width=1000.0), "application/x-step")
    )
    app.run()
    assert app.dataframe == []


def test_replacing_identical_upload_bytes_under_a_new_name_clears_report_and_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a fingerprint that treats two different uploaded artefacts as the same input."""
    data = _ifc_bytes(tmp_path)
    app = _upload_and_run(_app(monkeypatch), data, name="first.ifc")
    selector = app.selectbox(key="finding_selector")
    selector.set_value(next(value for value in selector.options if "R2_" in value))
    app.run()

    app.file_uploader(key="ifc_upload").set_value(("second.ifc", data, "application/x-step"))
    app.run()

    assert app.dataframe == []
    assert app.selectbox == []

    app.button(key="run_preflight").click()
    app.run()
    assert app.exception == []
    assert "R1_EGRESS_DOOR_OPENING_WIDTH" in app.selectbox(key="finding_selector").value


def test_demo_fingerprint_uses_content_when_available_and_a_stable_missing_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a demo fingerprint based only on a path that can be replaced in place."""
    import app as app_module
    from app import _input_fingerprint

    demo_path = tmp_path / "demo.ifc"
    demo_path.write_bytes(b"first demo")
    monkeypatch.setattr(app_module, "DEMO_PATH", demo_path)
    first = _input_fingerprint("Bundled synthetic demo", 900, None)
    demo_path.write_bytes(b"second demo")
    second = _input_fingerprint("Bundled synthetic demo", 900, None)
    demo_path.unlink()
    missing_one = _input_fingerprint("Bundled synthetic demo", 900, None)
    missing_two = _input_fingerprint("Bundled synthetic demo", 900, None)

    assert first != second
    assert missing_one == missing_two
    assert "unavailable" in missing_one

    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))
    app.radio(key="input_source").set_value("Bundled synthetic demo")
    app.run()
    assert app.dataframe == []


def test_invalid_ifc_is_rendered_as_a_typed_file_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches parser exceptions escaping into the Streamlit page."""
    app = _upload_and_run(_app(monkeypatch), b"this is not IFC")

    assert app.exception == []
    assert any(error.value == "Unable to load IFC file." for error in app.error)


def test_missing_demo_file_is_a_visible_unavailable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a fake bundled model or an unhandled missing sample path."""
    isolated_app = tmp_path / "app.py"
    copyfile(APP_PATH, isolated_app)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(isolated_app, default_timeout=10).run()
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


def test_selected_status_uses_a_trusted_marker_without_unsafe_colored_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a fixed text colour that can disappear under an application theme."""
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))
    status_copy = " ".join(markdown.value for markdown in app.markdown if "WIDTH_MEETS" in markdown.value)

    assert "<span" not in status_copy
    assert "🟢" in status_copy
    assert "PASS" in status_copy


def test_control_caption_is_neutral_about_the_demo_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches an upload control being described as though it were always the bundled demo."""
    app = _app(monkeypatch)

    assert any(
        caption.value
        == "Default threshold: 900 mm. The bundled synthetic demo uses the Demo project screening profile."
        for caption in app.caption
    )


def test_explanation_draft_is_not_rendered_after_selecting_another_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an R1 explanation remaining visible when the selected result becomes R2."""
    calls: list[tuple[str, str, str]] = []

    def fake_request(result: object, mode: str) -> ExplanationDraft:
        calls.append((result.rule_id, result.element_global_id, mode))
        return ExplanationDraft("R1 draft", (), (), "Review the source.")

    monkeypatch.setattr("bim_preflight.explain.request_explanation", fake_request)
    app = _upload_and_run(_app(monkeypatch, with_api_key=True), _ifc_bytes(tmp_path))
    app.button(key="ai_EXPLAIN_RESULT").click()
    app.run()
    assert calls and calls[-1][0] == "R1_EGRESS_DOOR_OPENING_WIDTH"

    selector = app.selectbox(key="finding_selector")
    selector.set_value(next(value for value in selector.options if "R2_" in value))
    app.run()
    displayed = " ".join(node.value for node in [*app.markdown, *app.caption, *app.text])
    assert "R1 draft" not in displayed


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


def test_upload_temporary_file_is_unlinked_after_success_and_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches cleanup beginning too late to cover a failed write after allocation."""
    import app as app_module
    from app import analyse_uploaded_bytes, temporary_ifc_path

    seen: list[Path] = []

    def successful_analyser(path: Path, threshold_m: float) -> object:
        seen.append(path)
        assert path.exists()
        return object()

    assert analyse_uploaded_bytes(b"valid", 0.9, analyser=successful_analyser)
    assert seen and not seen[0].exists()

    allocated_path = tmp_path / "allocated.ifc"

    class FailingTemporaryFile:
        name = str(allocated_path)

        def __enter__(self) -> Self:
            allocated_path.touch()
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def write(self, data: bytes) -> int:
            raise OSError("write failed")

    monkeypatch.setattr(app_module, "NamedTemporaryFile", lambda **kwargs: FailingTemporaryFile())
    with pytest.raises(OSError, match="write failed"), temporary_ifc_path(b"invalid"):
        pass
    assert not allocated_path.exists()


def test_error_results_have_a_visible_error_metric(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches internal engine failures disappearing behind only the four required status metrics."""
    from bim_preflight import engine

    def broken_width_rule(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated rule failure")

    monkeypatch.setattr(engine, "evaluate_width_rule", broken_width_rule)
    app = _upload_and_run(_app(monkeypatch), _ifc_bytes(tmp_path))

    assert _metric_value(app, "ERROR") == "1"


def test_methods_copy_keeps_r2_in_its_metadata_only_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches a UI claim that turns metadata presence into a fire-code conclusion."""
    app = _app(monkeypatch)
    copy = " ".join(markdown.value for markdown in app.markdown)

    assert "R2 checks metadata presence only" in copy
    assert "SelfClosing=false counts as present" in copy
    assert "No legal, fire-code, or installed-performance conclusion" in copy
