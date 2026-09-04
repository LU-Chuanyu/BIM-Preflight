"""Pure deterministic egress-door screening rules."""

from collections.abc import Iterable
from math import isfinite

from bim_preflight.models import DoorFact, EngineStatus, RuleResult, ValueState

RULE_VERSION = "1.0.0"
WIDTH_RULE_ID = "R1_EGRESS_DOOR_OPENING_WIDTH"
METADATA_RULE_ID = "R2_EGRESS_DOOR_METADATA_COMPLETENESS"
_THRESHOLD_REF = f"rule.{WIDTH_RULE_ID}.configuration.threshold_m"


class RuleConfigurationError(ValueError):
    """Raised when a deterministic rule configuration is unusable."""


def validate_threshold_m(threshold_m: object) -> float:
    """Require a finite, strictly positive metric screening threshold."""
    if type(threshold_m) not in {int, float} or not isfinite(threshold_m) or threshold_m <= 0:
        raise RuleConfigurationError("threshold_m must be a finite, strictly positive number")
    return float(threshold_m)


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


def _applicability_inputs(door: DoorFact) -> tuple[tuple[str, None | bool | int | float | str], ...]:
    fire_exit = door.fire_exit
    return (
        ("fire_exit_value", fire_exit.value),
        ("fire_exit_state", fire_exit.state.value),
        ("fire_exit_source", fire_exit.source.value),
    )


def evaluate_width_rule(door: DoorFact, threshold_m: float) -> RuleResult:
    """Screen a classified egress door's model-declared opening-width proxy."""
    threshold_m = validate_threshold_m(threshold_m)
    applicability_status, code, message, fire_exit_refs = _applicability(door)
    inputs = (("overall_width_m", door.overall_width_m), ("threshold_m", threshold_m))
    if applicability_status is not None:
        return _rule_result(
            rule_id=WIDTH_RULE_ID,
            door=door,
            status=applicability_status,
            finding_code=code or "FIRE_EXIT_UNRESOLVED",
            message=message or "The door's FireExit classification is missing or invalid.",
            evidence_refs=fire_exit_refs,
            inputs_used=_applicability_inputs(door),
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
            inputs_used=_applicability_inputs(door),
        )

    defects: list[tuple[str, str, str]] = []
    fire_rating = door.fire_rating
    if fire_rating.state is ValueState.MISSING:
        defects.append(("FIRE_RATING", "FireRating", "MISSING"))
    elif (
        fire_rating.state is not ValueState.PRESENT
        or not isinstance(fire_rating.value, str)
        or not fire_rating.value.strip()
    ):
        defects.append(("FIRE_RATING", "FireRating", "INVALID"))
    self_closing = door.self_closing
    if self_closing.state is ValueState.MISSING:
        defects.append(("SELF_CLOSING", "SelfClosing", "MISSING"))
    elif self_closing.state is not ValueState.PRESENT or type(self_closing.value) is not bool:
        defects.append(("SELF_CLOSING", "SelfClosing", "INVALID"))

    if defects:
        code = "_".join(f"{field}_{state}" for field, _, state in defects)
        if len(defects) == 1:
            _field, label, state = defects[0]
            message = (
                f"The {label} profile field is {'missing' if state == 'MISSING' else 'invalid'} "
                "for this project completeness profile."
            )
        else:
            code = f"METADATA_INCOMPLETE_{code}"
            message = "This project completeness profile is incomplete: " + "; ".join(
                f"{label} profile field is {state.lower()}" for _, label, state in defects
            ) + "."
        return _rule_result(
            rule_id=METADATA_RULE_ID,
            door=door,
            status=EngineStatus.FAIL,
            finding_code=code,
            message=message,
            evidence_refs=metadata_refs,
            inputs_used=inputs,
        )
    return _rule_result(
        rule_id=METADATA_RULE_ID,
        door=door,
        status=EngineStatus.PASS,
        finding_code="METADATA_COMPLETE",
        message="The FireRating and SelfClosing profile fields are present for this project completeness profile.",
        evidence_refs=metadata_refs,
        inputs_used=inputs,
    )
