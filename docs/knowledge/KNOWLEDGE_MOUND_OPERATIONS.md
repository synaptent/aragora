# Knowledge Mound Operations Guide

> **Last Updated:** 2026-01-27

The Knowledge Mound is Aragora's unified knowledge storage system that accumulates insights from debates, documents, and external sources. It provides semantic querying, contradiction detection, and knowledge quality management.

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [API Endpoints](#api-endpoints)
  - [Nodes & Relationships](#nodes--relationships)
  - [Graph Operations](#graph-operations)
  - [Extraction](#extraction)
  - [Curation](#curation)
  - [Pruning](#pruning)
  - [Contradiction Detection](#contradiction-detection)
  - [Governance](#governance)
  - [Analytics](#analytics)
  - [Federation](#federation)
  - [Deduplication](#deduplication)
  - [Export](#export)
- [Examples](#examples)
- [Architecture](#architecture)
- [Performance Tuning](#performance-tuning)
- [Legacy facts without an organization (operator-only)](#legacy-facts-without-an-organization-operator-only)

---

## Overview

The Knowledge Mound serves as the "organizational memory" for Aragora, enabling:

- **Cross-debate learning**: Insights from past debates inform future discussions
- **Contradiction detection**: Identifies conflicting claims across knowledge items
- **Quality management**: Auto-curation, pruning, and confidence decay
- **Federation**: Sync knowledge across distributed deployments
- **RBAC governance**: Fine-grained access control with audit trails

---

## Core Concepts

### Knowledge Nodes

A knowledge node represents a discrete unit of knowledge:

```json
{
  "id": "node-123",
  "content": "GraphQL provides better flexibility for complex nested queries",
  "node_type": "claim",
  "confidence": 0.85,
  "source": {"debate_id": "debate-456", "round": 3},
  "workspace_id": "ws-001",
  "created_at": "2024-01-15T10:30:00Z",
  "metadata": {"domain": "api-design", "tags": ["graphql", "architecture"]}
}
```

**Node Types:**
- `claim` - Extracted assertion from debates
- `fact` - Verified factual information
- `insight` - Derived knowledge from analysis
- `reference` - External source reference

### Relationships

Nodes connect via typed relationships:

| Relationship | Description |
|--------------|-------------|
| `supports` | Evidence supporting a claim |
| `contradicts` | Conflicting information |
| `derives_from` | Knowledge derived from source |
| `supersedes` | Updated version of knowledge |
| `related_to` | General semantic relationship |

### Confidence Decay

Knowledge confidence decays over time based on:
- Age (older = less confident)
- Validation frequency
- Contradiction count
- Usage patterns

---

## API Endpoints

### Nodes & Relationships

#### Create a Node

```http
POST /api/v1/knowledge/mound/nodes
Content-Type: application/json

{
  "content": "Microservices improve deployment flexibility but increase operational complexity",
  "node_type": "claim",
  "confidence": 0.8,
  "workspace_id": "ws-001",
  "metadata": {
    "domain": "architecture",
    "tags": ["microservices", "devops"]
  }
}
```

**Response:**
```json
{
  "id": "node-789",
  "content": "Microservices improve deployment flexibility...",
  "node_type": "claim",
  "confidence": 0.8,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### Get a Node

```http
GET /api/v1/knowledge/mound/nodes/node-789
```

#### List Nodes

```http
GET /api/v1/knowledge/mound/nodes?workspace_id=ws-001&node_type=claim&limit=50
```

#### Create Relationship

```http
POST /api/v1/knowledge/mound/relationships
Content-Type: application/json

{
  "source_id": "node-123",
  "target_id": "node-456",
  "relationship_type": "supports",
  "confidence": 0.9
}
```

#### Get Node Relationships

```http
GET /api/v1/knowledge/mound/nodes/node-123/relationships
```

---

### Graph Operations

#### Traverse Graph

```http
GET /api/v1/knowledge/mound/graph/node-123?depth=3&relationship_types=supports,derives_from
```

**Response:**
```json
{
  "root": {"id": "node-123", "content": "..."},
  "nodes": [...],
  "edges": [
    {"source": "node-123", "target": "node-456", "type": "supports"}
  ],
  "depth": 3
}
```

#### Get Node Lineage

```http
GET /api/v1/knowledge/mound/graph/node-123/lineage
```

Returns the provenance chain showing how knowledge was derived.

#### Get Related Nodes

```http
GET /api/v1/knowledge/mound/graph/node-123/related?limit=10
```

Uses semantic similarity to find related knowledge.

---

### Extraction

Extract knowledge from debates automatically.

#### Extract from Debate

```http
POST /api/v1/knowledge/mound/extraction/debate
Content-Type: application/json

{
  "debate_id": "debate-456",
  "messages": [
    {"agent_id": "claude", "content": "GraphQL reduces over-fetching...", "round": 1},
    {"agent_id": "gpt4", "content": "REST is simpler for basic CRUD...", "round": 1}
  ],
  "consensus_text": "Use GraphQL for complex queries, REST for simple endpoints",
  "topic": "API design patterns"
}
```

**Response:**
```json
{
  "extracted_claims": [
    {"id": "node-001", "content": "GraphQL reduces over-fetching", "confidence": 0.85},
    {"id": "node-002", "content": "REST is simpler for basic CRUD", "confidence": 0.82}
  ],
  "relationships": [
    {"source": "node-001", "target": "node-002", "type": "contrasts_with"}
  ],
  "consensus_node": {"id": "node-003", "content": "Use GraphQL for complex queries..."}
}
```

#### CDC Ingestion (Change Data Capture)

CDC events can be stored as knowledge nodes. Include CDC metadata to preserve
provenance and freshness signals.

```http
POST /api/v1/knowledge/mound/nodes
Content-Type: application/json

{
  "content": "Enterprise pricing updated to $499/mo",
  "node_type": "signal",
  "confidence": 0.9,
  "workspace_id": "ws-001",
  "metadata": {
    "source_type": "postgresql",
    "cdc_operation": "update",
    "table": "pricing",
    "timestamp": "2026-01-25T12:34:56Z"
  }
}
```

#### Promote Extracted Claims

```http
POST /api/v1/knowledge/mound/extraction/promote
Content-Type: application/json

{
  "claim_ids": ["node-001", "node-002"],
  "target_tier": "verified"
}
```

#### Get Extraction Statistics

```http
GET /api/v1/knowledge/mound/extraction/stats?workspace_id=ws-001
```

---

### Curation

Manage automatic knowledge quality curation.

#### Get Curation Policy

```http
GET /api/v1/knowledge/mound/curation/policy?workspace_id=ws-001
```

**Response:**
```json
{
  "min_confidence_threshold": 0.3,
  "staleness_decay_rate": 0.1,
  "auto_archive_days": 90,
  "contradiction_resolution": "highest_confidence",
  "enabled": true
}
```

#### Set Curation Policy

```http
POST /api/v1/knowledge/mound/curation/policy
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "min_confidence_threshold": 0.4,
  "staleness_decay_rate": 0.15,
  "auto_archive_days": 60
}
```

#### Trigger Curation Run

```http
POST /api/v1/knowledge/mound/curation/run
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "dry_run": true
}
```

#### Get Quality Scores

```http
GET /api/v1/knowledge/mound/curation/scores?workspace_id=ws-001
```

---

### Pruning

Remove stale or low-quality knowledge.

#### Get Prunable Items

```http
GET /api/v1/knowledge/mound/pruning/items?workspace_id=ws-001&staleness_threshold=0.9&min_age_days=30
```

**Response:**
```json
{
  "items": [
    {
      "id": "node-old-001",
      "content": "...",
      "staleness_score": 0.95,
      "last_accessed": "2023-06-15T...",
      "confidence": 0.2
    }
  ],
  "total_count": 47
}
```

#### Execute Pruning

```http
POST /api/v1/knowledge/mound/pruning/execute
Content-Type: application/json

{
  "item_ids": ["node-old-001", "node-old-002"],
  "action": "archive"  // or "delete"
}
```

#### Auto-Prune with Policy

```http
POST /api/v1/knowledge/mound/pruning/auto
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "policy": {
    "staleness_threshold": 0.9,
    "min_age_days": 30,
    "action": "archive"
  }
}
```

#### Restore Archived Item

```http
POST /api/v1/knowledge/mound/pruning/restore
Content-Type: application/json

{
  "item_id": "node-old-001"
}
```

#### Apply Confidence Decay

```http
POST /api/v1/knowledge/mound/pruning/decay
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "decay_rate": 0.05
}
```

---

### Contradiction Detection

Identify and resolve conflicting knowledge.

#### Detect Contradictions

```http
POST /api/v1/knowledge/mound/contradictions/detect
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "item_ids": ["node-123", "node-456"]  // optional
}
```

**Response:**
```json
{
  "contradictions": [
    {
      "id": "contra-001",
      "items": [
        {"id": "node-123", "content": "GraphQL is always better"},
        {"id": "node-456", "content": "REST is simpler and sufficient"}
      ],
      "similarity_score": 0.87,
      "detected_at": "2024-01-15T..."
    }
  ],
  "scan_duration_ms": 1250
}
```

#### List Unresolved Contradictions

```http
GET /api/v1/knowledge/mound/contradictions?workspace_id=ws-001&status=unresolved
```

#### Resolve Contradiction

```http
POST /api/v1/knowledge/mound/contradictions/contra-001/resolve
Content-Type: application/json

{
  "resolution": "merge",  // or "keep_first", "keep_second", "supersede"
  "winner_id": "node-123",
  "reason": "More recent and higher confidence"
}
```

#### Get Contradiction Statistics

```http
GET /api/v1/knowledge/mound/contradictions/stats?workspace_id=ws-001
```

---

### Governance

RBAC and audit trail management.

#### Create Role

```http
POST /api/v1/knowledge/mound/governance/roles
Content-Type: application/json

{
  "name": "knowledge_curator",
  "permissions": ["read", "write", "prune", "curate"],
  "workspace_id": "ws-001"
}
```

#### Assign Role

```http
POST /api/v1/knowledge/mound/governance/roles/assign
Content-Type: application/json

{
  "user_id": "user-123",
  "role_name": "knowledge_curator",
  "workspace_id": "ws-001"
}
```

#### Check Permission

```http
POST /api/v1/knowledge/mound/governance/permissions/check
Content-Type: application/json

{
  "user_id": "user-123",
  "permission": "prune",
  "resource_id": "node-456"
}
```

#### Query Audit Trail

```http
GET /api/v1/knowledge/mound/governance/audit?workspace_id=ws-001&action=delete&since=2024-01-01
```

---

### Analytics

Usage and quality analytics.

#### Domain Coverage Analysis

```http
GET /api/v1/knowledge/mound/analytics/coverage?workspace_id=ws-001
```

**Response:**
```json
{
  "domains": [
    {"name": "api-design", "node_count": 156, "avg_confidence": 0.78},
    {"name": "security", "node_count": 89, "avg_confidence": 0.82}
  ],
  "total_nodes": 1247,
  "coverage_score": 0.73
}
```

#### Usage Patterns

```http
GET /api/v1/knowledge/mound/analytics/usage?workspace_id=ws-001&period=30d
```

#### Quality Trend

```http
GET /api/v1/knowledge/mound/analytics/quality/trend?workspace_id=ws-001&period=90d
```

---

### Federation

Sync knowledge across distributed deployments.

**Permissions:** `federation:read` for status/list, admin role for region registration.

#### Register Region

```http
POST /api/v1/knowledge/mound/federation/regions
Content-Type: application/json

{
  "region_id": "eu-west",
  "endpoint_url": "https://eu.aragora.example.com",
  "api_key": "...",
  "mode": "bidirectional",
  "sync_scope": "summary"
}
```

#### Sync to Region

```http
POST /api/v1/knowledge/mound/federation/sync/push
Content-Type: application/json

{
  "region_id": "eu-west",
  "workspace_id": "ws-001",
  "since": "2024-01-01T00:00:00Z",
  "visibility_levels": ["public", "shared"]
}
```

#### Pull from Region

```http
POST /api/v1/knowledge/mound/federation/sync/pull
Content-Type: application/json

{
  "region_id": "eu-west",
  "workspace_id": "ws-001"
}
```

---

### Deduplication

Identify and merge duplicate knowledge nodes within a workspace.

**Permissions:** `knowledge:read` for report/cluster/merge operations.

#### List Duplicate Clusters

```http
GET /api/v1/knowledge/mound/dedup/clusters?workspace_id=ws-001&similarity_threshold=0.9&limit=50
```

#### Generate Dedup Report

```http
GET /api/v1/knowledge/mound/dedup/report?workspace_id=ws-001&similarity_threshold=0.9
```

#### Merge Duplicate Cluster

```http
POST /api/v1/knowledge/mound/dedup/merge
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "cluster_id": "cluster-123",
  "primary_node_id": "node-1",
  "archive": true
}
```

#### Auto-Merge Exact Duplicates

```http
POST /api/v1/knowledge/mound/dedup/auto-merge
Content-Type: application/json

{
  "workspace_id": "ws-001",
  "dry_run": true
}
```

---

### Export

Export knowledge graph in various formats.

#### Export as D3 JSON

```http
GET /api/v1/knowledge/mound/export/d3?workspace_id=ws-001&root_id=node-123&depth=3
```

#### Export as GraphML

```http
GET /api/v1/knowledge/mound/export/graphml?workspace_id=ws-001
```

---

## Examples

### End-to-End: Debate to Knowledge

```python
import httpx

# 1. Run a debate (via debate API)
debate_result = await run_debate("Should we use microservices?")

# 2. Extract knowledge from debate
extraction = httpx.post(
    "/api/v1/knowledge/mound/extraction/debate",
    json={
        "debate_id": debate_result["id"],
        "messages": debate_result["messages"],
        "consensus_text": debate_result["consensus"],
        "topic": "microservices architecture"
    }
)

# 3. Review and promote high-confidence claims
httpx.post(
    "/api/v1/knowledge/mound/extraction/promote",
    json={
        "claim_ids": [c["id"] for c in extraction["extracted_claims"] if c["confidence"] > 0.8],
        "target_tier": "verified"
    }
)

# 4. Check for contradictions with existing knowledge
httpx.post(
    "/api/v1/knowledge/mound/contradictions/detect",
    json={"workspace_id": "ws-001"}
)
```

### Knowledge Quality Maintenance

```python
# Weekly maintenance job
import httpx

# 1. Apply confidence decay
httpx.post(
    "/api/v1/knowledge/mound/pruning/decay",
    json={"workspace_id": "ws-001", "decay_rate": 0.02}
)

# 2. Detect contradictions
contradictions = httpx.post(
    "/api/v1/knowledge/mound/contradictions/detect",
    json={"workspace_id": "ws-001"}
)

# 3. Get prunable items
prunable = httpx.get(
    "/api/v1/knowledge/mound/pruning/items",
    params={"workspace_id": "ws-001", "staleness_threshold": 0.95}
)

# 4. Archive very stale items
if prunable["total_count"] > 0:
    httpx.post(
        "/api/v1/knowledge/mound/pruning/execute",
        json={
            "item_ids": [item["id"] for item in prunable["items"][:100]],
            "action": "archive"
        }
    )
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Knowledge Mound Handler                       │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐      │
│  │  Extraction │  Curation   │   Pruning   │Contradiction│      │
│  │    Mixin    │    Mixin    │    Mixin    │    Mixin    │      │
│  └──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘      │
│         │             │             │             │              │
│  ┌──────┴─────────────┴─────────────┴─────────────┴──────┐      │
│  │                  KnowledgeMound Core                   │      │
│  │  ┌─────────────┬─────────────┬─────────────┐          │      │
│  │  │   Storage   │  Embedding  │    Graph    │          │      │
│  │  │   Backend   │   Service   │   Engine    │          │      │
│  │  └─────────────┴─────────────┴─────────────┘          │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │PostgreSQL│        │  Vector  │        │   Neo4j  │
   │ Storage  │        │   DB     │        │  (opt)   │
   └──────────┘        └──────────┘        └──────────┘
```

---

## Performance Tuning

### Query Optimization

| Parameter | Default | Recommended | Notes |
|-----------|---------|-------------|-------|
| `limit` | 100 | 50-200 | Lower for faster queries |
| `depth` | 2 | 1-3 | Graph traversal depth |
| `embedding_batch_size` | 32 | 16-64 | For bulk operations |

### Request-Scoped Query Cache

Enable the request-scoped cache to avoid repeating identical lookups within
the same request or task.

| Variable | Default | Notes |
|----------|---------|-------|
| `ARAGORA_QUERY_CACHE_ENABLED` | `true` | Toggle request cache |
| `ARAGORA_QUERY_CACHE_MAX_SIZE` | `1000` | Max entries per request |

### Curation Settings

| Setting | Conservative | Aggressive |
|---------|--------------|------------|
| `staleness_decay_rate` | 0.05 | 0.15 |
| `min_confidence_threshold` | 0.2 | 0.4 |
| `auto_archive_days` | 180 | 60 |

### Federation Sync

- **Pull frequency**: Every 15-60 minutes
- **Batch size**: 100-500 items
- **Conflict resolution**: `highest_confidence` or `most_recent`

---

## Legacy facts without an organization (operator-only)

Facts stored before facts carried an owning organization keep `org_id = NULL`. They are
quarantined: no API route, CLI command, sync job or in-process reader returns, changes or
deletes them, and no organization can claim them. The rows are kept, not deleted.

Only an operator with direct access to the knowledge database may give such a fact an owner.
This is never done over HTTP and never by an ordinary user.

1. Record, outside Aragora, the ownership evidence for each fact ID: which organization owns
   it and how that is known. A fact without recorded evidence stays unassigned.
2. Back up the database (default `ARAGORA_DATA_DIR/knowledge.db`):

   ```bash
   sqlite3 "$ARAGORA_DATA_DIR/knowledge.db" ".backup 'knowledge.db.bak'"
   ```

3. List the unassigned IDs read-only:

   ```bash
   sqlite3 -readonly "$ARAGORA_DATA_DIR/knowledge.db" \
     "SELECT id, workspace_id, substr(statement, 1, 80) FROM facts WHERE org_id IS NULL;"
   ```

4. Assign the evidenced facts by explicit ID and verify the returned count:

   ```python
   from pathlib import Path
   from aragora.knowledge import FactStore

   ids = ["fact-id-1", "fact-id-2"]  # only IDs with recorded ownership evidence
   store = FactStore(db_path=Path("/path/to/knowledge.db"))
   assigned = store.assign_org("org-id", fact_ids=ids)
   assert assigned == len(ids), assigned
   ```

   A lower count means an ID was wrong, repeated or already owned: investigate before going on.

Never call `assign_org` with `fact_ids=None`: that assigns every unassigned fact, which is bulk
adoption and is not supported. Never guess an owner, and never adopt facts automatically or for
the first writer. `assign_org` never changes a fact that already belongs to an organization.

---

## Related Documentation

- [API Reference](../api/API_REFERENCE.md)
- [Debate Orchestration](../debate/ORCHESTRATION.md)
- [Memory Systems](./MEMORY_STRATEGY.md)
