---
title: Redis Failover Runbook
description: Redis Failover Runbook
---

# Redis Failover Runbook

Procedures for Redis high availability and recovery.

## Architecture

```
                    ┌─────────────┐
                    │   Sentinel  │
                    │   Cluster   │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │  Master  │  │ Replica 1│  │ Replica 2│
      │ (write)  │──│  (read)  │──│  (read)  │
      └──────────┘  └──────────┘  └──────────┘
```

---

## Health Check

```bash
# Check Redis master
redis-cli -h redis-master.aragora INFO replication

# Check Redis replicas
redis-cli -h redis-replica.aragora INFO replication

# Check Sentinel (if using)
redis-cli -h redis-sentinel.aragora -p 26379 SENTINEL masters

# Check cluster health (Redis Cluster mode)
redis-cli -h redis.aragora CLUSTER INFO
```

---

## Kubernetes Redis HA

### Using Bitnami Chart

```bash
helm install redis bitnami/redis \
  --namespace aragora \
  --set architecture=replication \
  --set replica.replicaCount=2 \
  --set sentinel.enabled=true \
  --set sentinel.quorum=2 \
  --set auth.password=$REDIS_PASSWORD
```

### Check Status

```bash
# Get pod status
kubectl get pods -n aragora -l app.kubernetes.io/name=redis

# Check master
kubectl exec -it redis-master-0 -n aragora -- redis-cli INFO replication

# Check sentinel
kubectl exec -it redis-node-0 -n aragora -c sentinel -- \
  redis-cli -p 26379 SENTINEL masters
```

---

## Manual Failover

### Sentinel Failover

```bash
# Trigger failover
redis-cli -h redis-sentinel.aragora -p 26379 SENTINEL FAILOVER mymaster

# Verify new master
redis-cli -h redis-sentinel.aragora -p 26379 SENTINEL get-master-addr-by-name mymaster
```

### Manual Promotion

If Sentinel is not available:

```bash
# 1. Stop writes to current master
redis-cli -h redis-master.aragora CLIENT PAUSE 60000

# 2. Wait for replication sync
redis-cli -h redis-replica-0.aragora INFO replication
# Check master_link_status:up and master_sync_in_progress:0

# 3. Promote replica
redis-cli -h redis-replica-0.aragora REPLICAOF NO ONE

# 4. Update application configuration
kubectl set env deployment/aragora-api REDIS_HOST=redis-replica-0.aragora

# 5. Point old master to new master
redis-cli -h redis-master.aragora REPLICAOF redis-replica-0.aragora 6379
```

---

## AWS ElastiCache Failover

### Automatic Failover

ElastiCache handles failover automatically. Monitor via:

```bash
# Check cluster status
aws elasticache describe-replication-groups \
  --replication-group-id aragora-redis

# Check events
aws elasticache describe-events \
  --source-type replication-group \
  --source-identifier aragora-redis
```

### Manual Failover

```bash
# Trigger failover
aws elasticache modify-replication-group \
  --replication-group-id aragora-redis \
  --primary-cluster-id aragora-redis-002 \
  --apply-immediately
```

---

## Data Recovery

### From RDB Snapshot

```bash
# Stop Redis
kubectl scale statefulset redis-master -n aragora --replicas=0

# Copy RDB file
kubectl cp backup/dump.rdb redis-master-0:/data/dump.rdb -n aragora

# Start Redis
kubectl scale statefulset redis-master -n aragora --replicas=1
```

### From AOF

```bash
# Stop Redis
kubectl scale statefulset redis-master -n aragora --replicas=0

# Copy AOF file
kubectl cp backup/appendonly.aof redis-master-0:/data/appendonly.aof -n aragora

# Start Redis
kubectl scale statefulset redis-master -n aragora --replicas=1
```

### From ElastiCache Snapshot

```bash
aws elasticache create-replication-group \
  --replication-group-id aragora-redis-restored \
  --replication-group-description "Restored from snapshot" \
  --snapshot-name aragora-redis-snapshot-20240101
```

---

## Common Issues

### Split Brain

When both nodes think they're master:

```bash
# 1. Identify true master (one with more data)
redis-cli -h node1.aragora DBSIZE
redis-cli -h node2.aragora DBSIZE

# 2. Demote wrong master
redis-cli -h node2.aragora REPLICAOF node1.aragora 6379

# 3. Verify replication
redis-cli -h node2.aragora INFO replication
```

### Replication Lag

```bash
# Check lag
redis-cli -h redis-replica.aragora INFO replication
# Look for master_repl_offset and slave_repl_offset

# If lag is growing:
# 1. Check network
kubectl exec -it redis-replica-0 -n aragora -- ping redis-master

# 2. Check memory
redis-cli -h redis-master.aragora INFO memory

# 3. Increase replication buffer
redis-cli -h redis-master.aragora CONFIG SET repl-backlog-size 128mb
```

### Memory Issues

```bash
# Check memory
redis-cli -h redis.aragora INFO memory

# Set memory limit
redis-cli -h redis.aragora CONFIG SET maxmemory 4gb
redis-cli -h redis.aragora CONFIG SET maxmemory-policy allkeys-lru

# Flush if needed (careful!)
redis-cli -h redis.aragora FLUSHDB ASYNC
```

---

## Monitoring

### Key Metrics

```yaml
# Prometheus alerts
- alert: RedisDown
  expr: redis_up == 0
  for: 1m
  labels:
    severity: critical

- alert: RedisReplicationBroken
  expr: redis_connected_slaves < 1
  for: 5m
  labels:
    severity: warning

- alert: RedisMemoryHigh
  expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.9
  for: 5m
  labels:
    severity: warning

- alert: RedisReplicationLag
  expr: redis_replication_lag > 10
  for: 5m
  labels:
    severity: warning
```

### Dashboard Panels

- Connected clients
- Memory usage
- Replication lag
- Commands per second
- Cache hit ratio

---

## Application Configuration

### Connection String for HA

```python
# Using Sentinel
REDIS_SENTINELS = [
    ("redis-sentinel-0.aragora", 26379),
    ("redis-sentinel-1.aragora", 26379),
    ("redis-sentinel-2.aragora", 26379),
]
REDIS_MASTER_NAME = "mymaster"

# Using Redis Cluster
REDIS_CLUSTER_NODES = [
    {"host": "redis-0.aragora", "port": 6379},
    {"host": "redis-1.aragora", "port": 6379},
    {"host": "redis-2.aragora", "port": 6379},
]
```

### Retry Logic

```python
from redis.sentinel import Sentinel
from redis.exceptions import ConnectionError, TimeoutError

sentinel = Sentinel(REDIS_SENTINELS, socket_timeout=0.5)

def get_redis_client():
    return sentinel.master_for(REDIS_MASTER_NAME, socket_timeout=0.5)

def redis_operation_with_retry(operation, max_retries=3):
    for attempt in range(max_retries):
        try:
            client = get_redis_client()
            return operation(client)
        except (ConnectionError, TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
```

---

## Verification After Failover

```bash
# 1. Check new master
redis-cli -h redis.aragora ROLE

# 2. Check replication
redis-cli -h redis.aragora INFO replication

# 3. Test write
redis-cli -h redis.aragora SET test:failover "$(date)"
redis-cli -h redis.aragora GET test:failover

# 4. Check application connectivity
curl http://aragora.company.com/health

# 5. Monitor for errors
kubectl logs -f deployment/aragora-api -n aragora | grep -i redis
```

---

## See Also

- [Incident Response Runbook](./incident-response-procedures)
- [Scaling Runbook](./scaling)
- [Monitoring Setup Runbook](./monitoring-setup)
