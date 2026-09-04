"""IFC analysis orchestration with deterministic per-door isolation."""

from collections.abc import Iterable
from pathlib import Path

from bim_preflight.ifc_extract import extract_door_facts, open_ifc
from bim_preflight.models import AnalysisReport, DoorFact, EngineStatus, ModelInfo, RuleResult
from bim_preflight.rules import (
    METADATA_RULE_ID,
    RULE_VERSION,
    WIDTH_RULE_ID,
    RuleConfigurationError,
    evaluate_metadata_rule,
    evaluate_width_rule,
    validate_threshold_m,
)
from bim_preflight.units import resolve_length_unit


class IfcLoadError(RuntimeError):
    """Raised when an IFC file cannot be opened for analysis."""


def evaluate_door(door: DoorFact, threshold_m: float) -> tuple[RuleResult, RuleResult]:
    """Evaluate both deterministic rules for one extracted door fact."""
    return evaluate_width_rule(door, threshold_m), evaluate_metadata_rule(door)


def _unique_refs(*reference_groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for group in reference_groups for ref in group))


def _rule_error_result(door: DoorFact, rule_id: str, threshold_m: float) -> RuleResult:
    if rule_id == WIDTH_RULE_ID:
        evidence_refs = _unique_refs(
            door.fire_exit.evidence_refs,
            (item.ref for item in door.evidence if item.label in {"LENGTHUNIT", "OverallWidth"}),
        )
        return RuleResult(
            rule_id=WIDTH_RULE_ID,
            rule_version=RULE_VERSION,
            element_global_id=door.element_global_id,
            element_name=door.display_name,
            status=EngineStatus.ERROR,
            finding_code="WIDTH_RULE_EVALUATION_ERROR",
            message="An internal error prevented opening-width proxy screening for this door.",
            evidence_refs=evidence_refs,
            inputs_used=(("overall_width_m", door.overall_width_m), ("threshold_m", threshold_m)),
        )

    evidence_refs = _unique_refs(
        door.fire_exit.evidence_refs,
        door.fire_rating.evidence_refs,
        door.self_closing.evidence_refs,
    )
    return RuleResult(
        rule_id=METADATA_RULE_ID,
        rule_version=RULE_VERSION,
        element_global_id=door.element_global_id,
        element_name=door.display_name,
        status=EngineStatus.ERROR,
        finding_code="METADATA_RULE_EVALUATION_ERROR",
        message="An internal error prevented metadata completeness screening for this door.",
        evidence_refs=evidence_refs,
        inputs_used=(
            ("fire_rating", door.fire_rating.value),
            ("self_closing", door.self_closing.value),
        ),
    )


def analyse_ifc(path: str | Path, threshold_m: float) -> AnalysisReport:
    """Open an IFC file, extract doors once, and return sorted rule findings."""
    threshold_m = validate_threshold_m(threshold_m)
    try:
        model = open_ifc(path)
        unit = resolve_length_unit(model)
        door_facts = tuple(sorted(extract_door_facts(model), key=lambda door: door.element_global_id))
    except Exception as error:
        raise IfcLoadError("Unable to load IFC file.") from error

    results: list[RuleResult] = []
    for door in door_facts:
        try:
            results.append(evaluate_width_rule(door, threshold_m))
        except RuleConfigurationError:
            raise
        except Exception:  # noqa: BLE001 - the engine must isolate unexpected rule failures.
            results.append(_rule_error_result(door, WIDTH_RULE_ID, threshold_m))
        try:
            results.append(evaluate_metadata_rule(door))
        except Exception:  # noqa: BLE001 - the engine must isolate unexpected rule failures.
            results.append(_rule_error_result(door, METADATA_RULE_ID, threshold_m))
    return AnalysisReport(
        model_info=ModelInfo(
            schema=model.schema,
            length_unit=unit.label,
            door_count=len(door_facts),
            length_unit_issue=unit.error_code,
        ),
        door_facts=door_facts,
        results=tuple(sorted(results, key=lambda result: (result.element_global_id, result.rule_id))),
    )
