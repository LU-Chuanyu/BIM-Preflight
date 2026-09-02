# BIM Preflight

BIM Preflight is a small, evidence-first Streamlit prototype for BIM coordinators and design
reviewers. It reads real STEP-format IFC files, resolves door properties with source provenance,
normalises the project length unit, and runs exactly two deterministic egress-door screening
rules. An optional AI layer can explain an already-completed result but cannot change it.

This project solves a narrow review problem: model issues such as a below-profile door-opening
width proxy, incomplete fire-door metadata, or unresolved `FireExit` classification should be
visible before a human reviewer spends time tracing the IFC manually.

## Quick workflow

1. Start the app with `streamlit run app.py`.
2. Choose **Bundled synthetic demo** and keep the default 900 mm setting. The result labels this
   setting exactly as `Demo project screening profile`; it is not a regulation.
3. Select **Run preflight**. The app parses an actual IFC4 STEP file and renders 12 findings for
   six doors, including pass, fail, not-evaluable, and not-applicable outcomes.
4. Select a finding to inspect the GlobalId, property source, raw value, project unit, normalised
   value, rule input, and stable finding code.
5. If `OPENAI_API_KEY` is absent, the deterministic workflow remains complete and AI actions are
   visibly disabled. If a key is configured, the three bounded AI actions remain separate from
   the engine-owned result.

You can instead upload an `.ifc` file and choose a project screening threshold. Uploaded files
are temporary and are removed after analysis.

## Architecture and data flow

```text
IFC STEP file
    -> IfcOpenShell parser
    -> project-unit and occurrence/type property resolution
    -> frozen DoorFact records with evidence references
    -> two deterministic Python rules
    -> immutable RuleResult records
       -> Streamlit status, table, plot, and evidence panel
       -> optional bounded AI explanation (separate object, locally validated)
```

The UI projects engine results; it does not recalculate a status. Parsing, unit conversion,
screening, charts, and evidence inspection do not require an API key.

## Exact rule semantics

| Rule | Applies when | PASS | FAIL | Other outcomes |
|---|---|---|---|---|
| `R1_EGRESS_DOOR_OPENING_WIDTH` | Resolved `Pset_DoorCommon.FireExit = TRUE` | Positive, unit-normalised `IfcDoor.OverallWidth` is at least the selected project threshold | The normalised value is below the selected project threshold | Missing, invalid, non-positive, or unnormalisable width is `NOT_EVALUABLE`; explicit `FireExit = FALSE` is `NOT_APPLICABLE` |
| `R2_EGRESS_DOOR_METADATA_COMPLETENESS` | Resolved `Pset_DoorCommon.FireExit = TRUE` | `FireRating` is a non-empty readable label and `SelfClosing` is a valid boolean | Either required property is missing, blank, invalid, or contradictory at the same source level | Missing/invalid `FireExit` is `NOT_EVALUABLE`; explicit `FireExit = FALSE` is `NOT_APPLICABLE` |

`IfcDoor.OverallWidth` is a model-declared door-opening width proxy, never clear width. The 900 mm
default is the `Demo project screening profile`, never regulation. R2 checks presence only:
`SelfClosing = FALSE` counts as present, and a present `FireRating` is not evidence that its label
is adequate. Neither rule makes a legal, code, safety, approval, certification, or performance
conclusion.

## Status meanings

| Status | Meaning |
|---|---|
| `PASS` | The input satisfies the selected project screening rule. |
| `FAIL` | The input violates the selected project screening or completeness rule. |
| `NOT_EVALUABLE` | Applicability or required evidence cannot be resolved. |
| `NOT_APPLICABLE` | `FireExit` is explicitly `FALSE`. |
| `ERROR` | An internal parse or rule error prevented a trustworthy result. |

Every result also has a stable `finding_code`, so integrations and tests do not depend on prose.

## Property precedence and evidence

`FireExit`, `FireRating`, and `SelfClosing` are resolved independently:

1. A valid occurrence-level value overrides the corresponding type value.
2. If the occurrence value is absent, a valid type-level value is inherited.
3. An invalid occurrence value does not silently fall back to the type.
4. Multiple contradictory values at the same level are invalid.
5. Every observed occurrence and type source remains in the evidence trail, including when an
   occurrence value wins.

Names, descriptions, classifications, and free text never substitute for `FireExit`.

## Setup and run

Python 3.12 or 3.13 is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
streamlit run app.py
```

Open the local address printed by Streamlit. To regenerate the committed synthetic sample:

```bash
python scripts/generate_demo_ifc.py
```

The generator also accepts an output path:

```bash
python scripts/generate_demo_ifc.py /tmp/demo-egress-doors.ifc
```

Output bytes are independent of that path: all IFC root identifiers are compressed UUIDv5 values
derived from stable semantic keys, entity construction is ordered, and every volatile header
field is fixed.

## Tests

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q bim_preflight app.py scripts
python -c "import ifcopenshell; m=ifcopenshell.open('samples/demo-egress-doors.ifc'); print(m.schema, len(m.by_type('IfcDoor')))"
```

The final smoke command prints `IFC4 6`. To rerun the explicit IfcOpenShell schema and EXPRESS-rule
validation (`express_rules=True`) for the generated demo:

```bash
python -m pytest tests/test_demo_sample.py::test_demo_ifc_passes_schema_and_express_validation -q
```

The suite exercises real in-memory and on-disk IFC files, the six-case sample at 900 mm, exact
byte regeneration, rule and extraction boundaries, adversarial AI-output validation, and the
credential-free Streamlit workflow. The committed synthetic file also passes IfcOpenShell 0.8.5
schema and EXPRESS-rule validation.

## Samples and provenance

### Project-generated synthetic sample

`samples/demo-egress-doors.ifc` is project-generated synthetic test data, not a real project or
legal evidence. Its six doors deliberately cover:

| Door | Width | `FireExit` source/value | Metadata case |
|---|---:|---|---|
| `01 Width Pass` | 1000 mm | occurrence / `TRUE` | complete; `SelfClosing = FALSE` |
| `02 Width Fail` | 800 mm | occurrence / `TRUE` | complete |
| `03 Metadata Incomplete` | 1000 mm | occurrence / `TRUE` | missing `FireRating` |
| `04 Explicit Non-Egress` | 1000 mm | occurrence / `FALSE` | rules not applicable |
| `05 Missing FireExit` | 1000 mm | missing | applicability unresolved |
| `06 Type-Inherited Properties` | 1000 mm | type / `TRUE` | `FireRating` and `SelfClosing` also inherited |

SHA-256: `ed46c5f98f5c959f4c004cf8209b7fb12d6fce035086419069313357efe5440f`.

### Official parser smoke sample

`samples/official/Building-Architecture.ifc` is an unmodified buildingSMART International Ltd.
Certification-datasets file, retrieved on 2026-09-03 from the
[exact primary source](https://raw.githubusercontent.com/buildingSMART/Certification-datasets/main/IFC%204.0.2.1%20%28IFC%204%29/PCERT-Sample-Scene/Building-Architecture.ifc).
It is distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) with the
upstream six-line license notice in `samples/official/LICENSE-CC-BY-4.0.txt`; that notice is not
the full legal code. SHA-256:
`3ff9b10bd00c7b96dded51e7ca5a6b69efbea38b049adcdd05fcd247de7e70d5`.
See `NOTICE.md` for the repository URL and attribution. This file is used only to prove that the
parser opens a traceable external IFC4 model; it is never run or presented as compliance evidence.

## AI boundary and prompt map

The deterministic engine is the sole authority for status, applicability, identifiers,
measurements, conversions, threshold, deficiencies, and provenance. The model receives a JSON
projection of one frozen `RuleResult` and may return only `summary`, `evidence_refs`,
`missing_information`, and `next_action`. Local validation enforces the exact schema, narrows
controlled-language selections to the supplied result, including distinct summaries for width
pass/fail, metadata complete/incomplete, and explicit non-egress/unresolved applicability. The
metadata-complete summary states only that `FireRating` is non-empty and `SelfClosing` is readable;
it does not claim that either value is adequate. Every evidence reference must come from the
supplied result. Explanation modes are enforced locally, and the missing-evidence action is
available only when the controlled result profile contains missing, invalid, or diagnostic
information; the manual-check mode uses distinct fixed summary framing. Rejected, unavailable, or
malformed output is discarded and leaves the finding unchanged.

AI assisted this prototype's implementation and review. Verification is provided by deterministic
tests and checked-in evidence; the optional model explanation remains experimental and has not
been live-model validated.

| Prompt asset | Runtime role |
|---|---|
| `bim_preflight/prompt_assets/system.md` | Defines the bounded selector and untrusted-data boundary. |
| `bim_preflight/prompt_assets/explain_finding.user.md` | Carries one closed action mode and one engine-owned result. |
| `bim_preflight/prompt_assets/output.schema.json` | Defines the exact four-field structured output. |
| `prompts/runtime/` | Reviewable source copies, guarded against package-resource drift by tests. |
| `prompts/development/prompt-log.md` | Records local fake-client validation and the absence of a live call. |

No live-model validation has been performed. The repository records no hosted URL, demo video,
or GitHub remote yet.

## Limitations

- IFC4 is the tested demo and official-smoke path. IFC2X3 and IFC4X3 are intended parser targets
  in the extraction code but have not been validated by this prototype.
- `OverallWidth` is read from the model; version 1 does not derive geometry or certified clear
  width.
- The tool does not retrieve regulations, select jurisdictions, inspect travel distance, perform
  clash detection, render 3D geometry, modify the model, or export BCF.
- There is no live-model validation, hosted deployment, authentication, database, job queue, or
  usage analytics.
- Optional AI output is explanatory only and has not been live-model validated.

## Repository map

| Path | Purpose |
|---|---|
| `app.py` | Streamlit workflow and evidence interface |
| `bim_preflight/ifc_extract.py` | IFC opening, unit-aware facts, and property provenance |
| `bim_preflight/rules.py` | Exactly two deterministic rules |
| `bim_preflight/engine.py` | Orchestration and per-rule error isolation |
| `bim_preflight/presentation.py` | Table, evidence, and Plotly view models |
| `bim_preflight/explain.py` | Optional Responses adapter and fail-closed validation |
| `bim_preflight/prompt_assets/` and `prompts/` | Installed and reviewable prompt contracts |
| `scripts/generate_demo_ifc.py` | Deterministic IFC4 synthetic sample generator |
| `samples/` | Synthetic demo and attributed official parser fixture |
| `NOTICE.md` | Official-sample attribution, source, retrieval date, and checksums |
| `tests/` | Unit, integration, adversarial, reproduction, and AppTest coverage |
| `docs/demo-script.md` | 2:40 recording script |
