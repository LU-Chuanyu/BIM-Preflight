"""Frozen, JSON-projectable values shared by the preflight pipeline."""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum

type Scalar = None | bool | int | float | str


class EngineStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class ValueState(str, Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    INVALID = "INVALID"


class PropertySource(str, Enum):
    OCCURRENCE = "OCCURRENCE"
    TYPE = "TYPE"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class Evidence:
    ref: str
    label: str
    raw_value: Scalar
    normalized_value: Scalar
    unit: str | None
    source: str


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    key: str
    state: ValueState
    value: Scalar
    source: PropertySource
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoorFact:
    element_global_id: str
    display_name: str
    ifc_schema: str
    fire_exit: ResolvedValue
    fire_rating: ResolvedValue
    self_closing: ResolvedValue
    overall_width_raw: float | None
    overall_width_m: float | None
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    rule_version: str
    element_global_id: str
    element_name: str
    status: EngineStatus
    finding_code: str
    message: str
    evidence_refs: tuple[str, ...]
    inputs_used: tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    schema: str
    length_unit: str | None
    door_count: int


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    model_info: ModelInfo
    door_facts: tuple[DoorFact, ...]
    results: tuple[RuleResult, ...]


def to_primitive(value: object) -> object:
    """Convert domain values into recursively JSON-safe Python primitives."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [to_primitive(item) for item in value]
    if isinstance(value, list):
        return [to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {key: to_primitive(item) for key, item in value.items()}
    return value
