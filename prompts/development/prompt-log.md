# Prompt log

## Runtime explanation contract v1

- Runtime files: `runtime/system.md`, `runtime/explain_finding.user.md`, and
  `runtime/output.schema.json`.
- Call site: `bim_preflight.explain.request_explanation` using the OpenAI Responses API.
- Local validation: fake-client tests exercise input rendering, exact call arguments, strict
  schema validation, evidence provenance, semantic rejection, and safe failure behavior.
- Live model validation: not performed. No live model run is recorded. Fake-client tests are not
  live model validation.

## Runtime explanation contract v2

- Replaced open-ended narrative generation and pattern filtering with exact English canonical
  sentence enums. Runtime validation narrows those choices to the supplied rule, finding code,
  status, and evidenced deficiencies.
- Added synchronized package resources for wheel installations and a structural outbound schema
  that omits keywords unsupported by the OpenAI strict-schema subset while retaining the full
  Draft 2020-12 schema locally.
- Added local fake-client coverage for multilingual and confusable bypasses, response errors,
  UTF-8 size limits, recursive input, and installed-resource behavior.
- Live model validation: not performed. No live model run is recorded. Fake-client tests and the
  package smoke test are not live model validation.

## Runtime explanation contract v3

- Bound local semantic validation to the requested closed mode. Missing-evidence output must
  contain the complete supported deficiency set exactly once; result and manual-check modes must
  return an empty `missing_information` list. The manual-check mode uses a distinct fixed summary,
  preventing result and recommendation actions from accepting identical output.
- Relevance-gated the missing-evidence action to findings with controlled missing, invalid, or
  diagnostic information. Fake-client and Streamlit AppTest regressions cover cross-mode rejection,
  pre-client failure, button state, and stale-output suppression.
- Live model validation: not performed. No live model run is recorded.

## Runtime explanation contract v4

- Split the result-summary vocabulary across width pass/fail, metadata complete/incomplete, and
  explicit non-egress/unresolved applicability outcomes. Local validation rejects reuse of a
  controlled summary across those opposing findings.
- The metadata-complete sentence describes only a non-empty `FireRating` label and a readable
  `SelfClosing` boolean; it does not claim that either value proves adequate fire performance.
- Live model validation: not performed. No live model run is recorded.
