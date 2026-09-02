"""Pure deterministic egress-door screening rules."""

from collections.abc import Iterable
from math import isfinite

from bim_preflight.models import DoorFact, EngineStatus, RuleResult, ValueState

RULE_VERSION = "1.0.0"
WIDTH_RULE_ID = "R1_EGRESS_DOOR_OPENING_WIDTH"
METADATA_RULE_ID = "R2_EGRESS_DOOR_METADATA_COMPLETENESS"
_THRESHOLD_REF = f"rule.{WIDTH_RULE_ID}.configuration.threshold_m"


def _unique_refs(*reference_groups: Iterable[str]) -> tuple[str, ...]:
    """Join evidence references while preserving their first-seen order."""
    return tuple(dict.fromkeys(ref for group in reference_groups for ref in group))


def _width_evidence_refs(door: DoorFact) -> tuple[str, ...]:
    return tuple(item.ref for item in door.evidence if item.label in {"LENGTHUNIT", "OverallWidth"})


def _rule_result(
    *,
    rule_id: str,
    door: DoorFact,
    status: EngineStatus,
    finding_code: str,
    message: str,
    evidence_refs: tuple[str, ...],
    inputs_used: tuple[tuple[str, None | bool | int | float | str], ...],
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        element_global_id=door.element_global_id,
        element_name=door.display_name,
        status=status,
        finding_code=finding_code,
        message=message,
        evidence_refs=evidence_refs,
        inputs_used=inputs_used,
    )


def _applicability(
    door: DoorFact,
) -> tuple[EngineStatus | None, str | None, str | None, tuple[str, ...]]:
    """Return the shared FireExit applicability decision for both rules."""
    fire_exit = door.fire_exit
    if fire_exit.state is ValueState.PRESENT and type(fire_exit.value) is bool:
        if fire_exit.value:
            return None, None, None, fire_exit.evidence_refs
        return (
            EngineStatus.NOT_APPLICABLE,
            "FIRE_EXIT_FALSE",
            "The door is explicitly not classified as a fire exit.",
            fire_exit.evidence_refs,
        )
    return (
        EngineStatus.NOT_EVALUABLE,
        "FIRE_EXIT_UNRESOLVED",
        "The door's FireExit classification is missing or invalid.",
        fire_exit.evidence_refs,
    )


def evaluate_width_rule(door: DoorFact, threshold_m: float) -> RuleResult:
    """Screen a classified egress door's model-declared opening-width proxy."""
    applicability_status, code, message, fire_exit_refs = _applicability(door)
    inputs = (("overall_width_m", door.overall_width_m), ("threshold_m", threshold_m))
    if applicability_status is not None:
        return _rule_result(
            rule_id=WIDTH_RULE_ID,
            door=door,
            status=applicability_status,
            finding_code=code or "FIRE_EXIT_UNRESOLVED",
            message=message or "The door's FireExit classification is missing or invalid.",
            evidence_refs=_unique_refs(fire_exit_refs, (_THRESHOLD_REF,)),
            inputs_used=inputs,
        )

    width_refs = _width_evidence_refs(door)
    width_m = door.overall_width_m
    if width_m is None:
        finding_code = "WIDTH_MISSING" if door.overall_width_raw is None else "WIDTH_NOT_EVALUABLE"
        return _rule_result(
            rule_id=WIDTH_RULE_ID,
            door=door,
            status=EngineStatus.NOT_EVALUABLE,
            finding_code=finding_code,
            message="The model-declared opening-width proxy cannot be evaluated.",
            evidence_refs=_unique_refs(fire_exit_refs, width_refs, (_THRESHOLD_REF,)),
            inputs_used=inputs,
        )
    if type(width_m) not in {int, float} or not isfinite(width_m) or width_m <= 0:
        return _rule_result(
            rule_id=WIDTH_RULE_ID,
            door=door,
            status=EngineStatus.NOT_EVALUABLE,
            finding_code="WIDTH_NOT_EVALUABLE",
            message="The model-declared opening-width proxy cannot be evaluated.",
            evidence_refs=_unique_refs(fire_exit_refs, width_refs, (_THRESHOLD_REF,)),
            inputs_used=inputs,
        )
    if width_m >= threshold_m:
        return _rule_result(
            rule_id=WIDTH_RULE_ID,
            door=door,
            status=EngineStatus.PASS,
            finding_code="WIDTH_MEETS_THRESHOLD",
            message="The model-declared opening-width proxy meets the configured screening threshold.",
            evidence_refs=_unique_refs(fire_exit_refs, width_refs, (_THRESHOLD_REF,)),
            inputs_used=inputs,
        )
    return _rule_result(
        rule_id=WIDTH_RULE_ID,
        door=door,
        status=EngineStatus.FAIL,
        finding_code="WIDTH_BELOW_THRESHOLD",
        message="The model-declared opening-width proxy is below the configured screening threshold.",
        evidence_refs=_unique_refs(fire_exit_refs, width_refs, (_THRESHOLD_REF,)),
        inputs_used=inputs,
    )


def evaluate_metadata_rule(door: DoorFact) -> RuleResult:
    """Check required fire-exit metadata presence without judging fire-code adequacy."""
    applicability_status, code, message, fire_exit_refs = _applicability(door)
    inputs = (("fire_rating", door.fire_rating.value), ("self_closing", door.self_closing.value))
    metadata_refs = _unique_refs(
        fire_exit_refs, door.fire_rating.evidence_refs, door.self_closing.evidence_refs
    )
    if applicability_status is not None:
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=applicability_status,
            finding_code=code or "FIRE_EXIT_UNRESOLVED",
            message=message or "The door's FireExit classification is missing or invalid.",
            evidence_refs=fire_exit_refs,
            inputs_used=inputs,
        )

    fire_rating = door.fire_rating
    if fire_rating.state is ValueState.MISSING:
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=EngineStatus.FAIL,
            finding_code="FIRE_RATING_MISSING",
            message="Required FireRating metadata is missing.",
            evidence_refs=metadata_refs,
            inputs_used=inputs,
        )
    if fire_rating.state is not ValueState.PRESENT or not isinstance(fire_rating.value, str) or not fire_rating.value.strip():
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=EngineStatus.FAIL,
            finding_code="FIRE_RATING_INVALID",
            message="Required FireRating metadata is blank or invalid.",
            evidence_refs=metadata_refs,
            inputs_used=inputs,
        )

    self_closing = door.self_closing
    if self_closing.state is ValueState.MISSING:
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=EngineStatus.FAIL,
            finding_code="SELF_CLOSING_MISSING",
            message="Required SelfClosing metadata is missing.",
            evidence_refs=metadata_refs,
            inputs_used=inputs,
        )
    if self_closing.state is not ValueState.PRESENT or type(self_closing.value) is not bool:
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=EngineStatus.FAIL,
            finding_code="SELF_CLOSING_INVALID",
            message="Required SelfClosing metadata is invalid.",
            evidence_refs=metadata_refs,
            inputs_used=inputs,
        )
    return _rule_result(
        rule_id=METADATA_RULE_ID,
        door=door,
        status=EngineStatus.PASS,
        finding_code="METADATA_COMPLETE",
        message="Required FireRating and SelfClosing metadata are present.",
        evidence_refs=metadata_refs,
        inputs_used=inputs,
    )
