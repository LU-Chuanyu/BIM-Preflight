# Runtime prompt contract

The prompt package is deliberately small. The deterministic rule engine remains the only
source of verdicts, measurements, thresholds, deficiencies, and evidence provenance. The model
is a bounded selector: narrative fields must be exact English sentences from checked-in enums.

| File | Runtime use | Local verification |
|---|---|---|
| `runtime/system.md` | Loaded as `instructions` by `request_explanation` | `tests/test_explain.py` exercises the exact Responses API boundary and controlled-language rejection |
| `runtime/explain_finding.user.md` | Rendered by `build_explanation_input` with one closed mode and one JSON-serialised `RuleResult` | Tests cover all modes, arbitrary working directories, and malicious IFC strings |
| `runtime/output.schema.json` | Full local Draft 2020-12 contract, including bounds and canonical enums | Tests check the dialect, exact four-key shape, bounds, enums, and rejection paths |
| `development/prompt-log.md` | Records prompt usage and validation evidence | Human-readable development record; it is not loaded at runtime |

Identical runtime copies live in `bim_preflight/prompt_assets/` so installed wheels can load them
with `importlib.resources`; synchronization tests prevent drift. The outbound strict schema is a
deep copy of the local schema with unsupported annotation/validation keywords removed, while its
types, required fields, closed object shape, enums, item schemas, and list bounds remain.

The model output is never merged with or written back to the frozen engine result. Local code
narrows the global enums to the selected rule result and permits only deficiencies supported by
its finding code and inputs. It also enforces mode semantics locally: the missing-evidence mode is
relevance-gated and must return the complete supported deficiency set, while the other modes must
return no missing-information items; the manual-check mode also requires its own fixed summary
framing. Rejected or unavailable explanations leave the deterministic finding unchanged.
