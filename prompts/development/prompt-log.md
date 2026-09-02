# Prompt log

## Runtime explanation contract v1

- Runtime files: `runtime/system.md`, `runtime/explain_finding.user.md`, and
  `runtime/output.schema.json`.
- Call site: `bim_preflight.explain.request_explanation` using the OpenAI Responses API.
- Local validation: fake-client tests exercise input rendering, exact call arguments, strict
  schema validation, evidence provenance, semantic rejection, and safe failure behavior.
- Live model validation: not performed. No live model run is recorded. Fake-client tests are not
  live model validation.
