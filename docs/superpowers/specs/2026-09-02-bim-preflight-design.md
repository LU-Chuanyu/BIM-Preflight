# BIM Preflight Design Specification

## 1. Purpose

BIM Preflight is an English-language web micro-prototype for BIM coordinators and design reviewers. It accepts an IFC file, extracts door facts, runs two deterministic egress-door preflight rules, visualises the evidence, and optionally asks an LLM to explain an immutable finding.

The product is a project-configured screening tool. It does not certify statutory compliance, determine whether a real building is safe, or replace review of the authoring model and applicable regulations.

## 2. Assessment Contract

The submission must demonstrate:

- a runnable web prototype;
- one authentic IFC parsing path, not a JSON-only mock;
- exactly two implemented rules;
- deterministic, inspectable rule outcomes;
- prompts that are actually loaded by runtime code;
- a useful but non-authoritative AI interaction;
- automated tests and a reproducible local setup;
- a GitHub repository containing code and prompts;
- a demonstration video shorter than three minutes.

The core IFC parsing and rule checks must work without an API key. When AI is unavailable or its output is rejected, the interface must preserve and display the original engine result and explicitly mark the explanation as unavailable.

## 3. Supported Scope

### 3.1 Inputs

- STEP Physical File IFC models readable by IfcOpenShell 0.8.5.
- Primary target schemas: IFC2X3, IFC4, and IFC4X3.
- User-selected minimum opening-width screening threshold, entered in millimetres.
- Demonstration profile: 900 mm, labelled `Demo project screening profile`; it is not presented as a regulatory threshold.

### 3.2 Candidate doors

The rules run for `IfcDoor` occurrences. A door is treated as an egress-door candidate only when the resolved `Pset_DoorCommon.FireExit` value is a valid IFC boolean `TRUE`.

- Explicit `FALSE`: both rules return `NOT_APPLICABLE`.
- Missing or invalid at both occurrence and type: both rules return `NOT_EVALUABLE`.
- Names, descriptions, object types, classifications, or free text never substitute for `FireExit` in version 1.

### 3.3 Property resolution

For each supported property, the extractor resolves occurrence and type sources separately and retains both as evidence.

1. A valid occurrence property overrides the corresponding type property.
2. If the occurrence property is absent, the type property is inherited.
3. An invalid occurrence value is not silently replaced by a type value.
4. Multiple contradictory values at the same precedence level produce an invalid resolution.
5. IFC2X3 type evidence may come from `IfcDoorStyle`; IFC4 and IFC4X3 type evidence may come from `IfcDoorType`.

This policy is applied independently to `FireExit`, `FireRating`, and `SelfClosing`.

### 3.4 Unit resolution

`IfcDoor.OverallWidth` uses the model's project length unit. Before comparison, the extractor must:

1. find exactly one usable project `LENGTHUNIT`;
2. resolve its scale to metres;
3. retain the original numeric value, unit label, and scale as evidence;
4. convert the value to metres for the rule engine.

Missing, ambiguous, or unsupported units make Rule 1 `NOT_EVALUABLE`. No default metre or millimetre assumption is allowed. Geometry-derived width fallback is excluded from version 1.

## 4. Rules

### R1: Egress-door opening-width screening

Identifier: `R1_EGRESS_DOOR_OPENING_WIDTH`

For a door whose resolved `FireExit` is `TRUE`:

- `PASS` when a positive, unit-normalised `OverallWidth` is greater than or equal to the configured threshold;
- `FAIL` when it is below the configured threshold;
- `NOT_EVALUABLE` when width or unit evidence is missing, invalid, non-positive, or ambiguous.

`OverallWidth` is described throughout the interface as a model-declared door-opening width proxy. It is not called clear width, unobstructed width, certified width, or statutory compliance.

### R2: Egress-door metadata completeness

Identifier: `R2_EGRESS_DOOR_METADATA_COMPLETENESS`

For a door whose resolved `FireExit` is `TRUE`, the rule checks whether:

- `FireRating` is present as a non-empty readable label; and
- `SelfClosing` is present as a valid boolean.

The rule returns:

- `PASS` when both metadata fields are present and valid;
- `FAIL` when either field is missing, blank, invalid, or contradictory at the same source level.

`SelfClosing = FALSE` counts as present metadata and may therefore produce `PASS`. Rule 2 does not assess whether the stated values satisfy a fire code or describe real installed performance.

### 4.3 Shared engine statuses

- `PASS`: the input satisfies this project's explicit screening rule.
- `FAIL`: the input deterministically violates this project's explicit screening or completeness rule.
- `NOT_EVALUABLE`: applicability or required evidence cannot be resolved.
- `NOT_APPLICABLE`: `FireExit` is explicitly `FALSE`.
- `ERROR`: an internal parse or evaluation error prevented a trustworthy result.

Every result also contains a stable `finding_code` that explains the branch without relying on prose.

## 5. Immutable Domain Model

Production domain objects are frozen dataclasses.

```text
EngineStatus = PASS | FAIL | NOT_EVALUABLE | NOT_APPLICABLE | ERROR
ValueState = PRESENT | MISSING | INVALID
PropertySource = OCCURRENCE | TYPE | NONE

Evidence:
  ref: str
  label: str
  raw_value: scalar | null
  normalized_value: scalar | null
  unit: str | null
  source: str

ResolvedValue:
  key: str
  state: ValueState
  value: bool | str | float | null
  source: PropertySource
  evidence_refs: tuple[str, ...]

DoorFact:
  element_global_id: str
  display_name: str
  ifc_schema: str
  fire_exit: ResolvedValue
  fire_rating: ResolvedValue
  self_closing: ResolvedValue
  overall_width_raw: float | null
  overall_width_m: float | null
  evidence: tuple[Evidence, ...]

RuleResult:
  rule_id: str
  rule_version: str
  element_global_id: str
  element_name: str
  status: EngineStatus
  finding_code: str
  message: str
  evidence_refs: tuple[str, ...]
  inputs_used: immutable scalar mapping
```

`RuleResult` is the only source used by result badges and deterministic messages.

## 6. AI Explanation Boundary

The LLM receives a JSON projection of one completed `RuleResult`. It does not receive a writable engine object and cannot invoke tools.

The model may return only:

```text
ExplanationDraft:
  summary: str
  evidence_refs: list[str]
  missing_information: list[str]
  next_action: str
```

The LLM does not output `status`, `rule_id`, `element_global_id`, applicability, measurements, conversions, thresholds, or rule configuration. The application continues to display those values directly from `RuleResult`.

Runtime validation must enforce:

- exactly the four allowed output keys;
- bounded string and list lengths;
- `evidence_refs` is a subset of the supplied `RuleResult.evidence_refs`;
- no extra numeric value absent from the supplied result;
- no unsupported legal, approval, certification, or code-compliance claim.

Invalid output is discarded. It is never merged into a `RuleResult`. The user sees `AI explanation unavailable; the deterministic finding remains unchanged.`

All IFC-authored strings are marked as untrusted data in the runtime prompt. The default UI has three bounded actions: explain result, explain missing evidence, and recommend the next manual check. It has no general chat box.

The following notice is deterministic UI copy, not model-generated text:

> Screening only. `IfcDoor.OverallWidth` is a model-declared door-opening width proxy, not a certified clear-opening measurement or a statutory compliance conclusion.

## 7. Web Interface

The Streamlit interface contains:

1. an IFC uploader and a millimetre threshold control;
2. a model summary with schema, project length unit, door count, and rule profile;
3. status metrics for pass, fail, not evaluable, and not applicable;
4. a compact results table with rule, status, finding code, name, and GlobalId;
5. an opening-width dot plot with the selected threshold line;
6. a selected-finding evidence panel showing property path, source, raw value, unit, normalised value, and rule input;
7. an optional AI explanation panel that never controls the result badge;
8. a concise methods and limitations section.

The first version does not include a 3D model viewer. Stable GlobalId and full property provenance provide the review trail.

## 8. Samples and Provenance

The repository includes:

- a generated, standards-conformant IFC fixture with pass, fail, incomplete, inherited, explicitly non-applicable, and unclassified doors; and
- one unmodified buildingSMART certification sample for parser smoke testing, with CC BY 4.0 attribution and the original source URL.

The generated file is labelled synthetic test data and is produced by a checked-in script. It is never described as a real project model.

## 9. Error Behaviour

- Invalid or unreadable IFC: show a concise file error; do not run rules.
- Missing project length unit: load door metadata, but make Rule 1 `NOT_EVALUABLE`.
- A failing door must not stop evaluation of other doors.
- Unexpected per-door errors produce an `ERROR` result for that door and rule.
- Missing API key, API timeout, refusal, malformed JSON, or failed explanation validation affects only the explanation panel.
- Raw secrets, full prompt payloads, and API keys are never written to logs or repository files.

## 10. Acceptance Tests

At minimum, automated tests cover:

1. 1000 mm against 900 mm produces R1 `PASS` and 1.0 m normalisation.
2. 800 mm against 900 mm produces R1 `FAIL` with raw value, unit, and threshold evidence.
3. Missing `OverallWidth` produces R1 `NOT_EVALUABLE`.
4. Explicit `FireExit = FALSE` makes both rules `NOT_APPLICABLE`.
5. Missing `FireExit` makes both rules `NOT_EVALUABLE`.
6. Type-level `FireExit = TRUE` is inherited and its source is retained.
7. A valid occurrence value overrides a different type value and both sources remain auditable.
8. Non-empty `FireRating` plus `SelfClosing = FALSE` produces R2 `PASS`.
9. Missing or blank R2 metadata produces R2 `FAIL` with exact missing fields.
10. Equivalent metre and millimetre inputs produce the same R1 outcome; unknown unit evidence prevents evaluation.
11. Malicious IFC strings cannot alter rule status.
12. An explanation with invented evidence references or forbidden keys is rejected.
13. Missing API key or malformed model output leaves the original finding usable.
14. A generated IFC fixture is parsed end to end into the expected door facts and results.
15. The Streamlit application starts successfully and renders its empty state without credentials.

## 11. Deliverables

- Source code and checked-in runtime prompts.
- Generated and attributed sample data.
- Automated unit and integration tests.
- English README with setup, architecture, rule semantics, limitations, sample provenance, and demo commands.
- `docs/demo-script.md` targeting a 2 minute 40 second recording.
- One-page updated CV and final email are separate application artifacts and are not generated or transmitted by the web application.

## 12. Non-goals

Version 1 excludes regulatory retrieval, legal advice, multi-jurisdiction profiles, RAG, autonomous agents, model editing, automatic property enrichment, travel-distance checks, clash detection, geometry-derived clear width, 3D rendering, BCF export, authentication, databases, queues, usage analytics, Docker, and cloud deployment.

## 13. Primary References

- buildingSMART IFC 4.3 `IfcDoor`: <https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcDoor.htm>
- buildingSMART IFC 4.3 `Pset_DoorCommon`: <https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/Pset_DoorCommon.htm>
- buildingSMART project units concept: <https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/concepts/Project_Context/Project_Units/content.html>
- IfcOpenShell element utilities: <https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html>
- IfcOpenShell unit utilities: <https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/unit/index.html>
- buildingSMART certification datasets and CC BY 4.0 license: <https://github.com/buildingSMART/Certification-datasets>
