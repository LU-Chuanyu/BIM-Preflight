# Runtime prompt contract

The prompt package is deliberately small. The deterministic rule engine remains the only
source of verdicts, measurements, thresholds, and evidence provenance.

| File | Runtime use | Local verification |
|---|---|---|
| `runtime/system.md` | Loaded as `instructions` by `request_explanation` | `tests/test_explain.py` exercises the exact Responses API boundary and semantic rejection |
| `runtime/explain_finding.user.md` | Rendered by `build_explanation_input` with one closed mode and one JSON-serialised `RuleResult` | Tests cover all modes, arbitrary working directories, and malicious IFC strings |
| `runtime/output.schema.json` | Sent as a strict JSON Schema and re-applied locally with Draft 2020-12 validation | Tests check the schema dialect, exact four-key shape, bounds, and rejection paths |
| `development/prompt-log.md` | Records prompt usage and validation evidence | Human-readable development record; it is not loaded at runtime |

The model output is never merged with or written back to the frozen engine result. Rejected or
unavailable explanations leave the deterministic finding unchanged.
