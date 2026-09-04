import math

import pytest

from bim_preflight.models import (
    DoorFact,
    EngineStatus,
    Evidence,
    PropertySource,
    ResolvedValue,
    ValueState,
)
from bim_preflight.rules import RuleConfigurationError, evaluate_metadata_rule, evaluate_width_rule


def _resolved_value(
    key: str, value: bool | str | None, *, state: ValueState | None = None
) -> ResolvedValue:
    resolved_state = state or (ValueState.PRESENT if value is not None else ValueState.MISSING)
    source = PropertySource.OCCURRENCE if resolved_state is not ValueState.MISSING else PropertySource.NONE
    return ResolvedValue(
        key=key,
        state=resolved_state,
        value=value if resolved_state is ValueState.PRESENT else None,
        source=source,
        evidence_refs=(f"door.d1.occurrence.Pset_DoorCommon.{key}",)
        if resolved_state is not ValueState.MISSING
        else (),
    )


def make_door_fact(
    *,
    fire_exit: bool | None,
    overall_width_m: float | None = 1.0,
    overall_width_raw: float | None = 1000.0,
    fire_rating: str | None = "60 min",
    self_closing: bool | None = True,
    fire_exit_state: ValueState | None = None,
    fire_rating_state: ValueState | None = None,
    self_closing_state: ValueState | None = None,
) -> DoorFact:
    """Build a literal DoorFact whose absent values use ValueState.MISSING."""
    return DoorFact(
        element_global_id="d1",
        display_name="Door 1",
        ifc_schema="IFC4",
        fire_exit=_resolved_value("FireExit", fire_exit, state=fire_exit_state),
        fire_rating=_resolved_value("FireRating", fire_rating, state=fire_rating_state),
        self_closing=_resolved_value("SelfClosing", self_closing, state=self_closing_state),
        overall_width_raw=overall_width_raw,
        overall_width_m=overall_width_m,
        evidence=(
            Evidence(
                ref="door.d1.attribute.OverallWidth",
                label="OverallWidth",
                raw_value=overall_width_raw,
                normalized_value=overall_width_m,
                unit="MILLIMETRE",
                source="occurrence",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("width_m", "expected"),
    [(1.0, EngineStatus.PASS), (0.9, EngineStatus.PASS), (0.8, EngineStatus.FAIL)],
)
def test_width_screening_uses_positive_normalised_width_and_inclusive_boundary(
    width_m: float, expected: EngineStatus
) -> None:
    """Catches a strict boundary comparison or comparison against raw IFC units."""
    result = evaluate_width_rule(make_door_fact(fire_exit=True, overall_width_m=width_m), 0.9)
    assert result.status is expected
    assert result.finding_code == (
        "WIDTH_MEETS_THRESHOLD" if expected is EngineStatus.PASS else "WIDTH_BELOW_THRESHOLD"
    )
    assert result.evidence_refs == (
        "door.d1.occurrence.Pset_DoorCommon.FireExit",
        "door.d1.attribute.OverallWidth",
        "rule.R1_EGRESS_DOOR_OPENING_WIDTH.configuration.threshold_m",
    )
    assert result.inputs_used == (("overall_width_m", width_m), ("threshold_m", 0.9))
    assert "clear width" not in result.message.lower()
    assert "statutory" not in result.message.lower()


def test_explicitly_non_egress_door_uses_only_decisive_applicability_data() -> None:
    """Catches treating explicit FireExit false as a metadata or width failure."""
    door = make_door_fact(fire_exit=False)
    width = evaluate_width_rule(door, 0.9)
    metadata = evaluate_metadata_rule(door)
    assert width.status is EngineStatus.NOT_APPLICABLE
    assert metadata.status is EngineStatus.NOT_APPLICABLE
    assert width.finding_code == "FIRE_EXIT_FALSE"
    assert metadata.finding_code == "FIRE_EXIT_FALSE"
    assert width.evidence_refs == (
        "door.d1.occurrence.Pset_DoorCommon.FireExit",
    )
    assert metadata.evidence_refs == ("door.d1.occurrence.Pset_DoorCommon.FireExit",)
    assert width.inputs_used == metadata.inputs_used == (
        ("fire_exit_value", False),
        ("fire_exit_state", "PRESENT"),
        ("fire_exit_source", "OCCURRENCE"),
    )


def test_unresolved_egress_classification_is_not_evaluable_for_both_rules() -> None:
    """Catches allowing names or metadata to substitute for FireExit."""
    door = make_door_fact(fire_exit=None)
    width = evaluate_width_rule(door, 0.9)
    metadata = evaluate_metadata_rule(door)
    assert width.status is EngineStatus.NOT_EVALUABLE
    assert metadata.status is EngineStatus.NOT_EVALUABLE
    assert width.finding_code == "FIRE_EXIT_UNRESOLVED"
    assert metadata.finding_code == "FIRE_EXIT_UNRESOLVED"
    assert width.evidence_refs == ()
    assert metadata.evidence_refs == ()
    assert width.inputs_used == metadata.inputs_used == (
        ("fire_exit_value", None),
        ("fire_exit_state", "MISSING"),
        ("fire_exit_source", "NONE"),
    )


@pytest.mark.parametrize(
    "invalid_threshold",
    [math.nan, math.inf, -math.inf, 0.0, -0.1, True, "0.9"],
)
def test_invalid_threshold_is_rejected_before_fire_exit_short_circuit(
    invalid_threshold: object,
) -> None:
    """Catches bad configuration being converted into a door verdict or error result."""
    with pytest.raises(RuleConfigurationError, match="threshold"):
        evaluate_width_rule(make_door_fact(fire_exit=False), invalid_threshold)


def test_missing_width_is_not_evaluable_with_width_and_threshold_evidence() -> None:
    """Catches treating missing OverallWidth as a threshold violation."""
    door = make_door_fact(fire_exit=True, overall_width_m=None, overall_width_raw=None)
    result = evaluate_width_rule(door, 0.9)
    assert result.status is EngineStatus.NOT_EVALUABLE
    assert result.finding_code == "WIDTH_MISSING"
    assert result.evidence_refs == (
        "door.d1.occurrence.Pset_DoorCommon.FireExit",
        "door.d1.attribute.OverallWidth",
        "rule.R1_EGRESS_DOOR_OPENING_WIDTH.configuration.threshold_m",
    )


def test_non_positive_or_unnormalised_width_is_not_evaluable() -> None:
    """Catches accepting zero or comparing an unresolved project unit as metres."""
    door = make_door_fact(fire_exit=True, overall_width_m=None, overall_width_raw=0.0)
    result = evaluate_width_rule(door, 0.9)
    assert result.status is EngineStatus.NOT_EVALUABLE
    assert result.finding_code == "WIDTH_NOT_EVALUABLE"


def test_non_finite_width_is_not_evaluable() -> None:
    """Catches allowing an invalid normalised numeric value to become a failed screening."""
    result = evaluate_width_rule(make_door_fact(fire_exit=True, overall_width_m=math.nan), 0.9)
    assert result.status is EngineStatus.NOT_EVALUABLE
    assert result.finding_code == "WIDTH_NOT_EVALUABLE"


def test_false_self_closing_is_complete_metadata() -> None:
    """Catches mistaking a valid false IFC boolean for missing metadata."""
    result = evaluate_metadata_rule(make_door_fact(fire_exit=True, self_closing=False))
    assert result.status is EngineStatus.PASS
    assert result.finding_code == "METADATA_COMPLETE"
    assert (
        result.message
        == "The FireRating and SelfClosing profile fields are present for this project completeness profile."
    )


def test_blank_fire_rating_fails_metadata_completeness() -> None:
    """Catches translating invalid FireRating evidence into NOT_EVALUABLE."""
    result = evaluate_metadata_rule(
        make_door_fact(
            fire_exit=True,
            fire_rating=None,
            fire_rating_state=ValueState.INVALID,
        )
    )
    assert result.status is EngineStatus.FAIL
    assert result.finding_code == "FIRE_RATING_INVALID"
    assert result.message == "The FireRating profile field is invalid for this project completeness profile."
    assert result.evidence_refs == (
        "door.d1.occurrence.Pset_DoorCommon.FireExit",
        "door.d1.occurrence.Pset_DoorCommon.FireRating",
        "door.d1.occurrence.Pset_DoorCommon.SelfClosing",
    )


def test_missing_self_closing_fails_metadata_completeness() -> None:
    """Catches turning incomplete required metadata into NOT_EVALUABLE."""
    result = evaluate_metadata_rule(make_door_fact(fire_exit=True, self_closing=None))
    assert result.status is EngineStatus.FAIL
    assert result.finding_code == "SELF_CLOSING_MISSING"
    assert result.message == "The SelfClosing profile field is missing for this project completeness profile."
    assert result.evidence_refs == (
        "door.d1.occurrence.Pset_DoorCommon.FireExit",
        "door.d1.occurrence.Pset_DoorCommon.FireRating",
    )


@pytest.mark.parametrize(
    ("fire_rating_state", "self_closing_state", "expected_code", "expected_message"),
    [
        (
            ValueState.MISSING,
            ValueState.MISSING,
            "METADATA_INCOMPLETE_FIRE_RATING_MISSING_SELF_CLOSING_MISSING",
            "This project completeness profile is incomplete: FireRating profile field is missing; SelfClosing profile field is missing.",
        ),
        (
            ValueState.MISSING,
            ValueState.INVALID,
            "METADATA_INCOMPLETE_FIRE_RATING_MISSING_SELF_CLOSING_INVALID",
            "This project completeness profile is incomplete: FireRating profile field is missing; SelfClosing profile field is invalid.",
        ),
        (
            ValueState.INVALID,
            ValueState.MISSING,
            "METADATA_INCOMPLETE_FIRE_RATING_INVALID_SELF_CLOSING_MISSING",
            "This project completeness profile is incomplete: FireRating profile field is invalid; SelfClosing profile field is missing.",
        ),
    ],
)
def test_metadata_aggregates_all_missing_or_invalid_fields_in_canonical_order(
    fire_rating_state: ValueState,
    self_closing_state: ValueState,
    expected_code: str,
    expected_message: str,
) -> None:
    """Catches reporting only the first incomplete metadata field encountered."""
    result = evaluate_metadata_rule(
        make_door_fact(
            fire_exit=True,
            fire_rating=None,
            self_closing=None,
            fire_rating_state=fire_rating_state,
            self_closing_state=self_closing_state,
        )
    )
    assert result.status is EngineStatus.FAIL
    assert result.finding_code == expected_code
    assert result.message == expected_message
