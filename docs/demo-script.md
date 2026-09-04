# BIM Preflight demo script — 2:40 total

Record the local Streamlit app and terminal in one continuous take. Do not show an API key or
claim a live AI call unless one has actually completed and its output has passed local validation.

## 0:00–0:15 — Scope (15 seconds)

**Visible action:** Show the title, screening notice, bundled-demo selector, and 900 mm input.

**Spoken line:** “BIM Preflight parses IFC door data and runs two deterministic project-screening
rules. This 900 millimetre value is the Demo project screening profile, not a regulation, and
OverallWidth is a model-declared opening-width proxy, not certified clear width.”

## 0:15–1:35 — Deterministic engine evidence (80 seconds)

**Visible actions:** Keep **Bundled synthetic demo** selected, click **Run preflight**, and point to the
IFC4 schema, `MILLIMETRE` project unit, six-door count, five status counters, and 12-row result
table. Select `01 Width Pass` R1 and show raw 1000 mm, normalised 1.0 m, the threshold input, stable
GlobalId, and `WIDTH_MEETS_THRESHOLD`. Then select `02 Width Fail` R1 and show raw 800 mm,
normalised 0.8 m, the same threshold, and `WIDTH_BELOW_THRESHOLD`. Finally select the R2 result for
`01 Width Pass` and show that `SelfClosing = FALSE` is present evidence.

**Spoken lines:** “The file is a real IFC4 STEP file parsed by IfcOpenShell. The engine resolves the
declared project unit before comparing widths. Here, one thousand millimetres becomes one metre
and passes this profile; eight hundred millimetres becomes zero point eight metres and fails.
Each result carries a GlobalId, finding code, inputs, and source evidence. R2 checks only metadata
presence, so a valid false SelfClosing value is present; it does not prove fire performance.”

## 1:35–2:05 — Uncertainty and applicability (30 seconds)

**Visible actions:** Select `03 Metadata Incomplete` R2, then `04 Explicit Non-Egress`, then
`05 Missing FireExit`, and finish by selecting the R2 result for
`06 Type-Inherited Properties` and its evidence.

**Spoken lines:** “Missing FireRating is an explicit completeness failure. FireExit false makes
both rules not applicable. Missing FireExit is not evaluable; names never substitute for that
property. This final door inherits FireExit, FireRating, and SelfClosing from its IFC type, and the
evidence panel labels that source as type. The interface preserves uncertainty instead of turning
it into a pass.”

## 2:05–2:30 — Optional experimental explanation (25 seconds)

**Visible action:** Keep the selected deterministic result visible and point to the optional AI
explanation actions, which are disabled when no `OPENAI_API_KEY` is configured. Briefly show
`prompts/runtime/output.schema.json` and `bim_preflight/explain.py` side by side if the recording
layout allows it.

**Spoken lines:** “The primary product is the deterministic web tool and needs no API key. The
optional AI explanation is experimental and has not been live-model validated here. When
configured, it can select only four explanation fields from a checked-in schema. Local validation
constrains text and evidence references, discards rejected output, and leaves the immutable engine
result as the only verdict.”

## 2:30–2:40 — Reproduction and close (10 seconds)

**Visible action:** Show a terminal with the completed test summary and, on the next line, the
`IFC4 6` sample smoke result. Do not scroll through test logs.

**Spoken line:** “Tests cover the rules, IFC parsing, exact sample regeneration, prompt boundary,
and web workflow. This is local project screening, not a legal or performance verdict.”
