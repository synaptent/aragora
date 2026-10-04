# Compatibility shims for moved symbols

When a symbol moves to a lower import layer, its old import path stays as a
re-export of the same object until the retire-after point. Each row names the
old and new location as `module:symbol`, the pull request that moved it, and
the earliest point at which the old path may be removed. Every row has
import-and-call tests at both paths.

| old path | new path | PR | retire-after |
|---|---|---|---|
| `aragora.debate.cache.embeddings_lru:EmbeddingCache` | `aragora.shared.embedding_cache:EmbeddingCache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:EmbeddingCacheManager` | `aragora.shared.embedding_cache:EmbeddingCacheManager` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:get_embedding_cache` | `aragora.shared.embedding_cache:get_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:get_scoped_embedding_cache` | `aragora.shared.embedding_cache:get_scoped_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:cleanup_embedding_cache` | `aragora.shared.embedding_cache:cleanup_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:reset_embedding_cache` | `aragora.shared.embedding_cache:reset_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.tracing:DebateMetrics` | `aragora.observability.debate_tracing:DebateMetrics` | #10307 | not before M4 seal |
| `aragora.debate.tracing:Span` | `aragora.observability.debate_tracing:Span` | #10307 | not before M4 seal |
| `aragora.debate.tracing:SpanContext` | `aragora.observability.debate_tracing:SpanContext` | #10307 | not before M4 seal |
| `aragora.debate.tracing:SpanRecorder` | `aragora.observability.debate_tracing:SpanRecorder` | #10307 | not before M4 seal |
| `aragora.debate.tracing:Tracer` | `aragora.observability.debate_tracing:Tracer` | #10307 | not before M4 seal |
| `aragora.debate.tracing:clear_metrics` | `aragora.observability.debate_tracing:clear_metrics` | #10307 | not before M4 seal |
| `aragora.debate.tracing:generate_span_id` | `aragora.observability.debate_tracing:generate_span_id` | #10307 | not before M4 seal |
| `aragora.debate.tracing:generate_trace_id` | `aragora.observability.debate_tracing:generate_trace_id` | #10307 | not before M4 seal |
| `aragora.debate.tracing:get_debate_context` | `aragora.observability.debate_tracing:get_debate_context` | #10307 | not before M4 seal |
| `aragora.debate.tracing:get_debate_id` | `aragora.observability.debate_tracing:get_debate_id` | #10307 | not before M4 seal |
| `aragora.debate.tracing:get_metrics` | `aragora.observability.debate_tracing:get_metrics` | #10307 | not before M4 seal |
| `aragora.debate.tracing:get_tracer` | `aragora.observability.debate_tracing:get_tracer` | #10307 | not before M4 seal |
| `aragora.debate.tracing:set_debate_context` | `aragora.observability.debate_tracing:set_debate_context` | #10307 | not before M4 seal |
| `aragora.debate.tracing:set_tracer` | `aragora.observability.debate_tracing:set_tracer` | #10307 | not before M4 seal |
| `aragora.debate.tracing:trace_agent_call` | `aragora.observability.debate_tracing:trace_agent_call` | #10307 | not before M4 seal |
| `aragora.debate.tracing:trace_phase` | `aragora.observability.debate_tracing:trace_phase` | #10307 | not before M4 seal |
| `aragora.debate.tracing:trace_round` | `aragora.observability.debate_tracing:trace_round` | #10307 | not before M4 seal |
| `aragora.debate.tracing:with_debate_context` | `aragora.observability.debate_tracing:with_debate_context` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:DEFAULT_LEDGER_PATH` | `aragora.evaluation.shift_ledger:DEFAULT_LEDGER_PATH` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:FAILURE_THRESHOLDS` | `aragora.evaluation.shift_ledger:FAILURE_THRESHOLDS` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:GREEN_SHIFT_REQUIRED_HOURS` | `aragora.evaluation.shift_ledger:GREEN_SHIFT_REQUIRED_HOURS` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:HEALTHY_STOP_PREFIXES` | `aragora.evaluation.shift_ledger:HEALTHY_STOP_PREFIXES` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:LedgerEntry` | `aragora.evaluation.shift_ledger:LedgerEntry` | #10307 | not before M4 seal |
| `aragora.swarm.shift_ledger:ShiftLedger` | `aragora.evaluation.shift_ledger:ShiftLedger` | #10307 | not before M4 seal |
| `aragora.persistence.db_config:CONSOLIDATED_DB_MAPPING` | `aragora.config.data_dir:CONSOLIDATED_DB_MAPPING` | #10316 | not before M4 seal |
| `aragora.persistence.db_config:DatabaseMode` | `aragora.config.data_dir:DatabaseMode` | #10316 | not before M4 seal |
| `aragora.persistence.db_config:DatabaseType` | `aragora.config.data_dir:DatabaseType` | #10316 | not before M4 seal |
| `aragora.persistence.db_config:LEGACY_DB_NAMES` | `aragora.config.data_dir:LEGACY_DB_NAMES` | #10316 | not before M4 seal |
| `aragora.persistence.db_config:get_db_mode` | `aragora.config.data_dir:get_db_mode` | #10316 | not before M4 seal |
| `aragora.persistence.db_config:get_default_data_dir` | `aragora.config.data_dir:get_default_data_dir` | #10316 | not before M4 seal |
| `aragora.tenancy.context:_current_tenant` | `aragora.config.tenant_context:_current_tenant` | #10316 | not before M4 seal |
| `aragora.tenancy.context:_current_tenant_id` | `aragora.config.tenant_context:_current_tenant_id` | #10316 | not before M4 seal |
| `aragora.tenancy.context:get_current_tenant` | `aragora.config.tenant_context:get_current_tenant` | #10316 | not before M4 seal |
| `aragora.tenancy.context:get_current_tenant_id` | `aragora.config.tenant_context:get_current_tenant_id` | #10316 | not before M4 seal |
| `aragora.tenancy.context:set_tenant` | `aragora.config.tenant_context:set_tenant` | #10316 | not before M4 seal |
| `aragora.tenancy.context:set_tenant_id` | `aragora.config.tenant_context:set_tenant_id` | #10316 | not before M4 seal |
