# Aragora Capability Matrix

> Source of truth: generated via `python scripts/generate_capability_matrix.py`
> OpenAPI source: `openapi.json`

## Executive Summary

| Surface | Inventory | Capability Coverage |
|---------|-----------|---------------------|
| **HTTP API** | 1772 paths / 2100 operations | 81.1% |
| **CLI** | 80 commands | 43.2% |
| **SDK (Python)** | 186 namespaces | 70.3% |
| **SDK (TypeScript)** | 185 namespaces | 70.3% |
| **UI** | tracked in capability surfaces | 86.5% |
| **Capability Catalog** | 37/37 mapped | 100.0% |

## Surface Gaps

### Missing API (7)

- `distributed_tracing`
- `extended_debates`
- `kafka_streaming`
- `multi_tenancy`
- `rabbitmq_streaming`
- `structured_logging`
- `supermemory`

### Missing CLI (21)

- `belief_network`
- `circuit_breaker`
- `compliance_framework`
- `distributed_tracing`
- `extended_debates`
- `kafka_streaming`
- `prometheus_metrics`
- `prompt_evolution`
- `pulse_trending`
- `rabbitmq_streaming`
- `rbac_v2`
- `rlm`
- `slack_integration`
- `slo_alerting`
- `sso_authentication`
- `structured_logging`
- `supermemory`
- `teams_integration`
- `telegram_connector`
- `webhook_integrations`
- `whatsapp_connector`

### Missing SDK (11)

- `circuit_breaker`
- `distributed_tracing`
- `extended_debates`
- `kafka_streaming`
- `prompt_evolution`
- `rabbitmq_streaming`
- `slack_integration`
- `structured_logging`
- `supermemory`
- `telegram_connector`
- `whatsapp_connector`

### Missing UI (5)

- `backup_disaster_recovery`
- `distributed_tracing`
- `extended_debates`
- `structured_logging`
- `webhook_integrations`

### Missing CHANNELS (30)

- `agent_team_selection`
- `backup_disaster_recovery`
- `belief_network`
- `circuit_breaker`
- `compliance_framework`
- `consensus_detection`
- `continuum_memory`
- `control_plane`
- `distributed_tracing`
- `extended_debates`
- `graph_debates`
- `kafka_streaming`
- `knowledge_mound`
- `marketplace`
- `matrix_debates`
- `multi_tenancy`
- `nomic_loop`
- `prometheus_metrics`
- `prompt_evolution`
- `pulse_trending`
- `rabbitmq_streaming`
- `rbac_v2`
- `rlm`
- `slo_alerting`
- `sso_authentication`
- ... and 5 more

## Regeneration

```bash
python scripts/generate_capability_matrix.py
```
