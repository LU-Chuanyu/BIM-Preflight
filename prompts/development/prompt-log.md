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
