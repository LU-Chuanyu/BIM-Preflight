"""Fail-closed, non-authoritative explanations for frozen rule results."""

import copy
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from bim_preflight.models import RuleResult, to_primitive

_RESOURCE_PACKAGE = "bim_preflight.prompt_assets"
_SYSTEM_PROMPT_NAME = "system.md"
_USER_PROMPT_NAME = "explain_finding.user.md"
_OUTPUT_SCHEMA_NAME = "output.schema.json"
_MAX_OUTPUT_BYTES = 16_384

_VALID_MODES = frozenset(
    {
        "EXPLAIN_RESULT",
        "EXPLAIN_MISSING_EVIDENCE",
        "RECOMMEND_NEXT_MANUAL_CHECK",
    }
)
_SAFE_UNAVAILABLE = "AI explanation unavailable; the deterministic finding remains unchanged."

_WIDTH_RULE_ID = "R1_EGRESS_DOOR_OPENING_WIDTH"
_METADATA_RULE_ID = "R2_EGRESS_DOOR_METADATA_COMPLETENESS"

_SUMMARY_FIRE_EXIT = "The finding concerns the door's FireExit classification."
_SUMMARY_WIDTH = "The finding concerns the model-declared door-opening width proxy."
_SUMMARY_WIDTH_MISSING = (
    "The finding concerns unavailable model-declared opening-width information."
)
_SUMMARY_WIDTH_UNUSABLE = "The finding concerns unusable model-declared opening-width information."
_SUMMARY_WIDTH_ERROR = "The finding concerns an interrupted opening-width screening check."
_SUMMARY_METADATA = "The finding concerns FireRating and SelfClosing metadata."
_SUMMARY_METADATA_ERROR = "The finding concerns an interrupted metadata completeness check."

_ACTION_FIRE_EXIT = "Verify the FireExit property and source in the authoring model."
_ACTION_WIDTH = "Review the model-declared opening-width source in the authoring model."
_ACTION_WIDTH_SOURCE = (
    "Verify the OverallWidth source and project length-unit definition in the authoring model."
)
_ACTION_WIDTH_ERROR = "Repeat the deterministic opening-width check after reviewing the source model."
_ACTION_METADATA = "Review the FireRating and SelfClosing sources in the authoring model."
_ACTION_FIRE_RATING = "Verify the FireRating property and source in the authoring model."
_ACTION_SELF_CLOSING = "Verify the SelfClosing property and source in the authoring model."
_ACTION_BOTH_METADATA = (
    "Verify the FireRating and SelfClosing properties and sources in the authoring model."
)
_ACTION_METADATA_ERROR = "Repeat the deterministic metadata check after reviewing the source model."

_MISSING_FIRE_EXIT = "FireExit classification is missing."
_INVALID_FIRE_EXIT = "FireExit classification is invalid."
_UNRESOLVED_FIRE_EXIT = "FireExit classification is unresolved."
_MISSING_WIDTH = "OverallWidth is missing."
_UNUSABLE_WIDTH = "Opening-width input or project length-unit information is unusable."
_MISSING_FIRE_RATING = "FireRating metadata is missing."
_INVALID_FIRE_RATING = "FireRating metadata is invalid."
_MISSING_SELF_CLOSING = "SelfClosing metadata is missing."
_INVALID_SELF_CLOSING = "SelfClosing metadata is invalid."
_WIDTH_DIAGNOSTICS = "Further diagnostic information for the opening-width check is unavailable."
_METADATA_DIAGNOSTICS = "Further diagnostic information for the metadata check is unavailable."

_R1_PROFILES = {
    ("PASS", "WIDTH_MEETS_THRESHOLD"): (_SUMMARY_WIDTH, _ACTION_WIDTH, frozenset()),
    ("FAIL", "WIDTH_BELOW_THRESHOLD"): (_SUMMARY_WIDTH, _ACTION_WIDTH, frozenset()),
    ("NOT_EVALUABLE", "WIDTH_MISSING"): (
        _SUMMARY_WIDTH_MISSING,
        _ACTION_WIDTH_SOURCE,
        frozenset({_MISSING_WIDTH}),
    ),
    ("NOT_EVALUABLE", "WIDTH_NOT_EVALUABLE"): (
        _SUMMARY_WIDTH_UNUSABLE,
        _ACTION_WIDTH_SOURCE,
        frozenset({_UNUSABLE_WIDTH}),
    ),
    ("ERROR", "WIDTH_RULE_EVALUATION_ERROR"): (
        _SUMMARY_WIDTH_ERROR,
        _ACTION_WIDTH_ERROR,
        frozenset({_WIDTH_DIAGNOSTICS}),
    ),
}

_METADATA_DEFICIENCIES = {
    "FIRE_RATING_MISSING": (
        frozenset({_MISSING_FIRE_RATING}),
        _ACTION_FIRE_RATING,
    ),
    "FIRE_RATING_INVALID": (
        frozenset({_INVALID_FIRE_RATING}),
        _ACTION_FIRE_RATING,
    ),
    "SELF_CLOSING_MISSING": (
        frozenset({_MISSING_SELF_CLOSING}),
        _ACTION_SELF_CLOSING,
    ),
    "SELF_CLOSING_INVALID": (
        frozenset({_INVALID_SELF_CLOSING}),
        _ACTION_SELF_CLOSING,
    ),
    "METADATA_INCOMPLETE_FIRE_RATING_MISSING_SELF_CLOSING_MISSING": (
        frozenset({_MISSING_FIRE_RATING, _MISSING_SELF_CLOSING}),
        _ACTION_BOTH_METADATA,
    ),
    "METADATA_INCOMPLETE_FIRE_RATING_MISSING_SELF_CLOSING_INVALID": (
        frozenset({_MISSING_FIRE_RATING, _INVALID_SELF_CLOSING}),
        _ACTION_BOTH_METADATA,
    ),
    "METADATA_INCOMPLETE_FIRE_RATING_INVALID_SELF_CLOSING_MISSING": (
        frozenset({_INVALID_FIRE_RATING, _MISSING_SELF_CLOSING}),
        _ACTION_BOTH_METADATA,
    ),
    "METADATA_INCOMPLETE_FIRE_RATING_INVALID_SELF_CLOSING_INVALID": (
        frozenset({_INVALID_FIRE_RATING, _INVALID_SELF_CLOSING}),
        _ACTION_BOTH_METADATA,
    ),
}

_UNSUPPORTED_OUTBOUND_SCHEMA_KEYS = frozenset(
    {"$schema", "minLength", "maxLength", "uniqueItems"}
)


@dataclass(frozen=True, slots=True)
class ExplanationDraft:
    summary: str
    evidence_refs: tuple[str, ...]
    missing_information: tuple[str, ...]
    next_action: str


class ExplanationUnavailable(RuntimeError):
    """Raised when a safe explanation cannot be produced."""


def _unavailable(reason: str | None = None) -> ExplanationUnavailable:
    if reason is None:
        return ExplanationUnavailable(_SAFE_UNAVAILABLE)
    return ExplanationUnavailable(f"{_SAFE_UNAVAILABLE} ({reason})")


def _validate_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode not in _VALID_MODES:
        raise _unavailable("unsupported mode")
    return mode


def _read_resource(name: str) -> str:
    try:
        value = resources.files(_RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, OSError, TypeError):
        raise _unavailable("prompt contract unavailable") from None
    if not value.strip():
        raise _unavailable("prompt contract unavailable")
    return value


def _load_schema() -> dict[str, Any]:
    try:
        schema = json.loads(_read_resource(_OUTPUT_SCHEMA_NAME))
        Draft202012Validator.check_schema(schema)
    except (json.JSONDecodeError, SchemaError, TypeError, RecursionError):
        raise _unavailable("schema contract unavailable") from None
    if not isinstance(schema, dict):
        raise _unavailable("schema contract unavailable")
    return schema


def _outbound_schema(schema: dict[str, Any]) -> dict[str, Any]:
    outbound = copy.deepcopy(schema)

    def remove_unsupported(value: object) -> None:
        if isinstance(value, dict):
            for key in _UNSUPPORTED_OUTBOUND_SCHEMA_KEYS:
                value.pop(key, None)
            for child in value.values():
                remove_unsupported(child)
        elif isinstance(value, list):
            for child in value:
                remove_unsupported(child)

    remove_unsupported(outbound)
    return outbound


def build_explanation_input(result: RuleResult, mode: str) -> str:
    """Render one closed mode and one JSON projection as explicitly untrusted data."""
    mode = _validate_mode(mode)
    template = _read_resource(_USER_PROMPT_NAME)
    result_json = json.dumps(to_primitive(result), ensure_ascii=False, indent=2)
    if template.count("{{MODE}}") != 1 or template.count("{{ENGINE_OWNED_RULE_RESULT}}") != 1:
        raise _unavailable("prompt contract unavailable")
    return template.replace("{{MODE}}", mode).replace("{{ENGINE_OWNED_RULE_RESULT}}", result_json)


def _fire_exit_profile(result: RuleResult) -> tuple[str, str, frozenset[str]] | None:
    if result.finding_code == "FIRE_EXIT_FALSE" and result.status.value == "NOT_APPLICABLE":
        return _SUMMARY_FIRE_EXIT, _ACTION_FIRE_EXIT, frozenset()
    if result.finding_code != "FIRE_EXIT_UNRESOLVED" or result.status.value != "NOT_EVALUABLE":
        return None
    state = dict(result.inputs_used).get("fire_exit_state")
    if state == "MISSING":
        missing = _MISSING_FIRE_EXIT
    elif state == "INVALID":
        missing = _INVALID_FIRE_EXIT
    else:
        missing = _UNRESOLVED_FIRE_EXIT
    return _SUMMARY_FIRE_EXIT, _ACTION_FIRE_EXIT, frozenset({missing})


def _controlled_profile(result: RuleResult) -> tuple[str, str, frozenset[str]]:
    fire_exit_profile = _fire_exit_profile(result)
    if fire_exit_profile is not None and result.rule_id in {_WIDTH_RULE_ID, _METADATA_RULE_ID}:
        return fire_exit_profile

    key = (result.status.value, result.finding_code)
    if result.rule_id == _WIDTH_RULE_ID and key in _R1_PROFILES:
        return _R1_PROFILES[key]
    if result.rule_id == _METADATA_RULE_ID:
        if key == ("PASS", "METADATA_COMPLETE"):
            return _SUMMARY_METADATA, _ACTION_METADATA, frozenset()
        if key == ("ERROR", "METADATA_RULE_EVALUATION_ERROR"):
            return (
                _SUMMARY_METADATA_ERROR,
                _ACTION_METADATA_ERROR,
                frozenset({_METADATA_DIAGNOSTICS}),
            )
        if result.status.value == "FAIL" and result.finding_code in _METADATA_DEFICIENCIES:
            missing, action = _METADATA_DEFICIENCIES[result.finding_code]
            return _SUMMARY_METADATA, action, missing
    raise _unavailable("controlled language profile unavailable")


def validate_explanation(payload: object, result: RuleResult) -> ExplanationDraft:
    """Validate local schema, exact evidence, and the result-specific language profile."""
    schema = _load_schema()
    try:
        Draft202012Validator(schema).validate(payload)
    except RecursionError:
        raise _unavailable("schema validation failed") from None
    except ValidationError as error:
        reason = "controlled language validation failed" if error.validator == "enum" else (
            "schema validation failed"
        )
        raise _unavailable(reason) from None
    if not isinstance(payload, dict):
        raise _unavailable("schema validation failed")

    references = payload["evidence_refs"]
    allowed_references = set(result.evidence_refs)
    if any(reference not in allowed_references for reference in references):
        raise _unavailable("evidence validation failed")

    summary, next_action, allowed_missing = _controlled_profile(result)
    narratives = (payload["summary"], *payload["missing_information"], payload["next_action"])
    if not all(value.isascii() for value in narratives):
        raise _unavailable("controlled language validation failed")
    if payload["summary"] != summary or payload["next_action"] != next_action:
        raise _unavailable("controlled language validation failed")
    if not set(payload["missing_information"]).issubset(allowed_missing):
        raise _unavailable("controlled language validation failed")

    return ExplanationDraft(
        summary=payload["summary"],
        evidence_refs=tuple(references),
        missing_information=tuple(payload["missing_information"]),
        next_action=payload["next_action"],
    )


def _contains_refusal(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "refusal" or value.get("refusal"):
            return True
        return any(_contains_refusal(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_refusal(item) for item in value)
    if getattr(value, "type", None) == "refusal" or getattr(value, "refusal", None):
        return True
    return any(
        _contains_refusal(child)
        for attribute in ("output", "content")
        if (child := getattr(value, attribute, None)) is not None
    )


def request_explanation(
    result: RuleResult,
    mode: str,
    client: Any | None = None,
    model_name: str = "gpt-5-mini",
) -> ExplanationDraft:
    """Explicitly request one explanation and fail closed on every boundary error."""
    mode = _validate_mode(mode)
    instructions = _read_resource(_SYSTEM_PROMPT_NAME)
    rendered_input = build_explanation_input(result, mode)
    schema = _outbound_schema(_load_schema())

    if client is None:
        try:
            from openai import OpenAI

            client = OpenAI()
        except Exception:  # noqa: BLE001
            raise _unavailable() from None

    try:
        response = client.responses.create(
            model=model_name,
            instructions=instructions,
            input=rendered_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "explanation_draft",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
    except Exception:  # noqa: BLE001
        raise _unavailable() from None

    try:
        if getattr(response, "status", None) != "completed":
            raise _unavailable("response incomplete")
        if getattr(response, "error", None) is not None:
            raise _unavailable("response error")
        if _contains_refusal(response):
            raise _unavailable("response refused")
        output_text = getattr(response, "output_text", None)
    except ExplanationUnavailable:
        raise
    except (Exception, RecursionError):  # noqa: BLE001
        raise _unavailable() from None

    if not isinstance(output_text, str) or not output_text.strip():
        raise _unavailable("response empty")
    try:
        output_size = len(output_text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _unavailable("response malformed") from None
    if output_size > _MAX_OUTPUT_BYTES:
        raise _unavailable("response size exceeded")
    try:
        payload = json.loads(output_text)
    except (json.JSONDecodeError, RecursionError):
        raise _unavailable("response malformed") from None
    return validate_explanation(payload, result)
