# Compatibility shims for moved symbols

When a symbol moves to a lower import layer, its old import path stays as a
re-export of the same object until the retire-after point. Each row names the
old and new location as `module:symbol`, the pull request that moved it, and
the earliest point at which the old path may be removed. Every row has
import-and-call tests at both paths.

| old path | new path | PR | retire-after |
|---|---|---|---|
| `aragora.audit.log:AuditCategory` | `aragora.observability.audit_log:AuditCategory` | #10382 | not before M4 seal |
| `aragora.audit.log:AuditEvent` | `aragora.observability.audit_log:AuditEvent` | #10382 | not before M4 seal |
| `aragora.audit.log:AuditLog` | `aragora.observability.audit_log:AuditLog` | #10382 | not before M4 seal |
| `aragora.audit.log:AuditOutcome` | `aragora.observability.audit_log:AuditOutcome` | #10382 | not before M4 seal |
| `aragora.audit.log:AuditQuery` | `aragora.observability.audit_log:AuditQuery` | #10382 | not before M4 seal |
| `aragora.audit.log:audit_admin_action` | `aragora.observability.audit_log:audit_admin_action` | #10382 | not before M4 seal |
| `aragora.audit.log:audit_auth_login` | `aragora.observability.audit_log:audit_auth_login` | #10382 | not before M4 seal |
| `aragora.audit.log:audit_data_access` | `aragora.observability.audit_log:audit_data_access` | #10382 | not before M4 seal |
| `aragora.audit.log:get_audit_log` | `aragora.observability.audit_log:get_audit_log` | #10382 | not before M4 seal |
| `aragora.audit.log:reset_audit_log` | `aragora.observability.audit_log:reset_audit_log` | #10382 | not before M4 seal |
| `aragora.audit.persistence:AuditPersistenceBackend` | `aragora.observability.audit_persistence:AuditPersistenceBackend` | #10382 | not before M4 seal |
| `aragora.audit.persistence:FileBackend` | `aragora.observability.audit_persistence:FileBackend` | #10382 | not before M4 seal |
| `aragora.audit.persistence:PostgresBackend` | `aragora.observability.audit_persistence:PostgresBackend` | #10382 | not before M4 seal |
| `aragora.audit.persistence:get_backend` | `aragora.observability.audit_persistence:get_backend` | #10382 | not before M4 seal |
| `aragora.audit.persistence.base:AuditPersistenceBackend` | `aragora.observability.audit_persistence.base:AuditPersistenceBackend` | #10382 | not before M4 seal |
| `aragora.audit.persistence.base:PersistenceError` | `aragora.observability.audit_persistence.base:PersistenceError` | #10382 | not before M4 seal |
| `aragora.audit.persistence.file:FileBackend` | `aragora.observability.audit_persistence.file:FileBackend` | #10382 | not before M4 seal |
| `aragora.audit.persistence.postgres:PostgresBackend` | `aragora.observability.audit_persistence.postgres:PostgresBackend` | #10382 | not before M4 seal |
| `aragora.audit.unified:AuditOutcome` | `aragora.observability.unified_audit:AuditOutcome` | #10382 | not before M4 seal |
| `aragora.audit.unified:AuditSeverity` | `aragora.observability.unified_audit:AuditSeverity` | #10382 | not before M4 seal |
| `aragora.audit.unified:UnifiedAuditCategory` | `aragora.observability.unified_audit:UnifiedAuditCategory` | #10382 | not before M4 seal |
| `aragora.audit.unified:UnifiedAuditEvent` | `aragora.observability.unified_audit:UnifiedAuditEvent` | #10382 | not before M4 seal |
| `aragora.audit.unified:UnifiedAuditLogger` | `aragora.observability.unified_audit:UnifiedAuditLogger` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_access` | `aragora.observability.unified_audit:audit_access` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_action` | `aragora.observability.unified_audit:audit_action` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_admin` | `aragora.observability.unified_audit:audit_admin` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_data` | `aragora.observability.unified_audit:audit_data` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_debate` | `aragora.observability.unified_audit:audit_debate` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_log` | `aragora.observability.unified_audit:audit_log` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_login` | `aragora.observability.unified_audit:audit_login` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_logout` | `aragora.observability.unified_audit:audit_logout` | #10382 | not before M4 seal |
| `aragora.audit.unified:audit_security` | `aragora.observability.unified_audit:audit_security` | #10382 | not before M4 seal |
| `aragora.audit.unified:configure_unified_audit_logger` | `aragora.observability.unified_audit:configure_unified_audit_logger` | #10382 | not before M4 seal |
| `aragora.audit.unified:get_unified_audit_logger` | `aragora.observability.unified_audit:get_unified_audit_logger` | #10382 | not before M4 seal |
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
