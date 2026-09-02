"""Fail-closed, non-authoritative explanations for frozen rule results."""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from bim_preflight.models import RuleResult, to_primitive

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROMPT_ROOT = _PROJECT_ROOT / "prompts" / "runtime"
_SYSTEM_PROMPT_PATH = _PROMPT_ROOT / "system.md"
_USER_PROMPT_PATH = _PROMPT_ROOT / "explain_finding.user.md"
_OUTPUT_SCHEMA_PATH = _PROMPT_ROOT / "output.schema.json"

_VALID_MODES = frozenset(
    {
        "EXPLAIN_RESULT",
        "EXPLAIN_MISSING_EVIDENCE",
        "RECOMMEND_NEXT_MANUAL_CHECK",
    }
)
_SAFE_UNAVAILABLE = "AI explanation unavailable; the deterministic finding remains unchanged."

_NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "half",
        "quarter",
    }
)
_MEASUREMENT_UNITS = frozenset(
    {
        "mm",
        "millimeter",
        "millimeters",
        "millimetre",
        "millimetres",
        "cm",
        "centimeter",
        "centimeters",
        "centimetre",
        "centimetres",
        "m",
        "meter",
        "meters",
        "metre",
        "metres",
        "inch",
        "inches",
        "foot",
        "feet",
    }
)
_MEASUREMENT_TERMS = frozenset(
    {"width", "height", "length", "opening", "distance", "measurement", "threshold"}
)
_FORBIDDEN_WORDS = (
    "pass",
    "passes",
    "passed",
    "passing",
    "fail",
    "fails",
    "failed",
    "failing",
    "failure",
    "error",
    "status",
    "acceptable",
    "unacceptable",
    "adequate",
    "approve",
    "approved",
    "approval",
    "certify",
    "certified",
    "certification",
    "compliant",
    "compliance",
    "complies",
    "legal",
    "legally",
    "lawful",
    "lawfully",
    "permitted",
    "satisfactory",
    "unsatisfactory",
    "conform",
    "conforms",
    "conforming",
    "conformity",
    "authorized",
    "authorised",
    "regulation",
    "regulations",
    "regulatory",
    "safe",
    "safety",
    "unsafe",
)
_FORBIDDEN_PHRASES = (
    "not evaluable",
    "not applicable",
    "meets requirement",
    "meets requirements",
    "meets the requirement",
    "meets the requirements",
    "meets code",
    "meets the code",
    "satisfies requirement",
    "satisfies requirements",
    "satisfies the requirement",
    "satisfies the requirements",
    "satisfies code",
    "building code",
    "fire code",
    "code compliant",
    "legally compliant",
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


def _read_text(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _unavailable("prompt contract unavailable") from error
    if not value.strip():
        raise _unavailable("prompt contract unavailable")
    return value


def _load_schema() -> dict[str, Any]:
    try:
        schema = json.loads(_read_text(_OUTPUT_SCHEMA_PATH))
        Draft202012Validator.check_schema(schema)
    except (json.JSONDecodeError, SchemaError, TypeError) as error:
        raise _unavailable("schema contract unavailable") from error
    if not isinstance(schema, dict):
        raise _unavailable("schema contract unavailable")
    return schema


def build_explanation_input(result: RuleResult, mode: str) -> str:
    """Render one closed mode and one JSON projection as explicitly untrusted data."""
    mode = _validate_mode(mode)
    template = _read_text(_USER_PROMPT_PATH)
    result_json = json.dumps(to_primitive(result), ensure_ascii=False, indent=2)
    if template.count("{{MODE}}") != 1 or template.count("{{ENGINE_OWNED_RULE_RESULT}}") != 1:
        raise _unavailable("prompt contract unavailable")
    return template.replace("{{MODE}}", mode).replace("{{ENGINE_OWNED_RULE_RESULT}}", result_json)


def _normalise_words(text: str) -> tuple[str, str]:
    normalised = unicodedata.normalize("NFKC", text).casefold()
    words = " ".join(
        "".join(character if character.isalnum() else " " for character in normalised).split()
    )
    return normalised, words


def _contains_obfuscated_word(text: str, word: str) -> bool:
    letters = r"\W*".join(re.escape(character) for character in word)
    return re.search(rf"(?<![a-z0-9]){letters}(?![a-z0-9])", text) is not None


def _has_quantity_statement(text: str) -> bool:
    normalised, words_text = _normalise_words(text)
    if any(character.isnumeric() for character in normalised):
        return True
    words = set(words_text.split())
    has_number_word = bool(words & _NUMBER_WORDS)
    if has_number_word and (words & _MEASUREMENT_UNITS or words & _MEASUREMENT_TERMS):
        return True
    return bool(words & {"convert", "converted", "converting", "conversion", "conversions"})


def _has_forbidden_claim(text: str) -> bool:
    normalised, words = _normalise_words(text)
    if any(_contains_obfuscated_word(normalised, word) for word in _FORBIDDEN_WORDS):
        return True
    if re.search(r"\b(?:meets|satisfies)\b(?:\s+\w+){0,4}\s+requirements?\b", words):
        return True
    return any(phrase in words for phrase in _FORBIDDEN_PHRASES)


def _narrative_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    return (
        payload["summary"],
        *payload["missing_information"],
        payload["next_action"],
    )


def validate_explanation(payload: object, result: RuleResult) -> ExplanationDraft:
    """Validate schema, exact evidence provenance, and non-authoritative semantics."""
    schema = _load_schema()
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError:
        raise _unavailable("schema validation failed") from None
    if not isinstance(payload, dict):
        raise _unavailable("schema validation failed")

    references = payload["evidence_refs"]
    allowed_references = set(result.evidence_refs)
    if any(reference not in allowed_references for reference in references):
        raise _unavailable("evidence validation failed")

    for text in _narrative_fields(payload):
        if _has_quantity_statement(text):
            raise _unavailable("quantity validation failed")
        if _has_forbidden_claim(text):
            raise _unavailable("semantic validation failed")

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
    instructions = _read_text(_SYSTEM_PROMPT_PATH)
    rendered_input = build_explanation_input(result, mode)
    schema = _load_schema()

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

    if getattr(response, "status", None) != "completed":
        raise _unavailable("response incomplete")
    if _contains_refusal(response):
        raise _unavailable("response refused")
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise _unavailable("response empty")
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError:
        raise _unavailable("response malformed") from None
    return validate_explanation(payload, result)
