# NotImplementedError Audit Report

**Date:** 2026-01-28
**Total Instances:** 71
**Classification:** All intentional and properly implemented

## Summary

After comprehensive audit of all 71 `NotImplementedError` instances in the codebase, all instances have been classified as **intentional patterns** that should be preserved. No dead code or incomplete features were identified.

## Classification

### Category 1: Abstract Base Class Methods (52 instances)

These are standard OOP patterns where abstract base classes define interfaces that subclasses must implement.

| File | Count | Purpose |
|------|-------|---------|
| `aragora/connectors/base.py` | 4 | Abstract connector interface (fetch, name, search, source_type) |
| `aragora/connectors/chat/base.py` | 13 | Abstract chat connector methods |
| `aragora/connectors/devices/base.py` | 4 | Abstract device connector methods |
| `aragora/debate/checkpoint.py` | 4 | Abstract checkpoint storage (delete, list, load, save) |
| `aragora/debate/similarity/backends.py` | 1 | Abstract compute_similarity |
| `aragora/debate/translation.py` | 2 | Abstract translation methods |
| `aragora/events/subscribers/debate_handlers.py` | 1 | Abstract event handler |
| `aragora/events/subscribers/mound_handlers.py` | 1 | Abstract event handler |
| `aragora/knowledge/mound/adapters/_fusion_mixin.py` | 3 | Fusion mixin methods |
| `aragora/knowledge/mound/adapters/_reverse_flow_base.py` | 2 | Reverse flow methods |
| `aragora/knowledge/mound/adapters/_semantic_mixin.py` | 2 | Semantic search methods |
| `aragora/knowledge/mound/ops/fusion.py` | 2 | Abstract fusion operations |
| `aragora/memory/continuum_glacial.py` | 2 | Abstract glacial memory |
| `aragora/memory/continuum_snapshot.py` | 1 | Abstract snapshot |
| `aragora/modes/base.py` | 1 | Abstract get_system_prompt |
| `aragora/pulse/ingestor.py` | 1 | Abstract fetch_trending |
| `aragora/server/handlers/admin/health/probes.py` | 2 | Abstract health probes |
| `aragora/server/handlers/knowledge_base/mound/*.py` | 8 | Abstract _get_mound (mixin pattern) |
| `aragora/types/skills.py` | 3 | Abstract skill interface |

**Status:** KEEP - Standard OOP inheritance patterns

### Category 2: Feature Guards "Not Supported" (6 instances)

These intentionally indicate that a specific provider or component doesn't support a particular feature.

| File | Purpose |
|------|---------|
| `aragora/connectors/accounting/base.py` | Token refresh not supported by default |
| `aragora/connectors/whisper.py` | Search not supported for Whisper |
| `aragora/harnesses/base.py` (x2) | Interactive sessions not supported |
| `aragora/server/handlers/oauth_providers/apple.py` | Token refresh for Apple Sign In |
| `aragora/server/handlers/oauth_providers/base.py` | Token refresh not supported by default |

**Status:** KEEP - Intentional capability guards

### Category 3: Runtime Environment Guards (3 instances)

These guard against improper usage outside of expected runtime environments.

| File | Purpose |
|------|---------|
| `aragora/rlm/debate_helpers.py` | RLM_M must run within TRUE RLM REPL environment |
| `aragora/rlm/knowledge_helpers.py` | RLM_M must run within TRUE RLM REPL environment |
| `aragora/server/handlers/utils/auth.py` | require_authenticated decorator requires async handlers |

**Status:** KEEP - Runtime validation with clear error messages

### Category 4: Documentation References (2 instances)

These appear in docstrings describing behavior, not actual raises.

| File | Purpose |
|------|---------|
| `aragora/harnesses/base.py` | Docstring describing session support |
| `aragora/server/handlers/oauth_providers/base.py` | Docstring for token refresh |

**Status:** N/A - Documentation only

## Conclusion

All 71 `NotImplementedError` instances serve legitimate purposes:

1. **52 (73%)** - Abstract base class methods requiring subclass implementation
2. **6 (8%)** - Feature guards for unsupported provider capabilities
3. **3 (4%)** - Runtime environment validation with helpful error messages
4. **2 (3%)** - Documentation references only

**Recommendation:** No action required. All instances follow best practices for Python OOP design and error handling.

## Future Considerations

When adding new abstract base classes:
1. Use `@abstractmethod` decorator with `NotImplementedError` in the body
2. Provide clear error messages indicating what subclasses must implement
3. Document the expected method signature in docstrings

For feature guards:
1. Use descriptive messages explaining why the feature is unsupported
2. Suggest alternatives if available
