"""IFC analysis orchestration with deterministic per-door isolation."""

from pathlib import Path

from bim_preflight.ifc_extract import extract_door_facts, open_ifc
from bim_preflight.models import AnalysisReport, DoorFact, EngineStatus, ModelInfo, RuleResult
from bim_preflight.rules import (
    METADATA_RULE_ID,
    RULE_VERSION,
    WIDTH_RULE_ID,
    evaluate_metadata_rule,
    evaluate_width_rule,
)
from bim_preflight.units import resolve_length_unit


class IfcLoadError(RuntimeError):
    """Raised when an IFC file cannot be opened for analysis."""


def evaluate_door(door: DoorFact, threshold_m: float) -> tuple[RuleResult, RuleResult]:
    """Evaluate both deterministic rules for one extracted door fact."""
    return evaluate_width_rule(door, threshold_m), evaluate_metadata_rule(door)


def _error_results(door: DoorFact) -> tuple[RuleResult, RuleResult]:
    message = "An internal error prevented evaluation of this door."
    evidence_refs = tuple(item.ref for item in door.evidence)
    return tuple(
        RuleResult(
            rule_id=rule_id,
            rule_version=RULE_VERSION,
            element_global_id=door.element_global_id,
            element_name=door.display_name,
            status=EngineStatus.ERROR,
            finding_code="DOOR_EVALUATION_ERROR",
            message=message,
            evidence_refs=evidence_refs,
            inputs_used=(),
        )
        for rule_id in (WIDTH_RULE_ID, METADATA_RULE_ID)
    )


def analyse_ifc(path: str | Path, threshold_m: float) -> AnalysisReport:
    """Open an IFC file, extract doors once, and return sorted rule findings."""
    try:
        model = open_ifc(path)
    except Exception as error:
        raise IfcLoadError("Unable to load IFC file.") from error

    unit = resolve_length_unit(model)
    door_facts = tuple(sorted(extract_door_facts(model), key=lambda door: door.element_global_id))
    results: list[RuleResult] = []
    for door in door_facts:
        try:
            results.extend(evaluate_door(door, threshold_m))
        except Exception:  # noqa: BLE001 - the engine must isolate unexpected per-door failures.
            results.extend(_error_results(door))
    return AnalysisReport(
        model_info=ModelInfo(
            schema=model.schema,
            length_unit=unit.label,
            door_count=len(door_facts),
        ),
        door_facts=door_facts,
        results=tuple(sorted(results, key=lambda result: (result.element_global_id, result.rule_id))),
    )
