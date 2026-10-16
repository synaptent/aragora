---
title: Scaling Runbook
description: Scaling Runbook
---

# Scaling Runbook

Procedures for horizontal and vertical scaling of Aragora services.

## When to Scale

### Scale Up Indicators

- API response time > 500ms (p95)
- CPU utilization > 70% sustained
- Memory utilization > 80%
- Queue depth growing consistently
- Error rate > 1%

### Scale Down Indicators

- CPU utilization < 30% sustained
- Memory utilization < 40%
- Queue consistently empty
- Off-peak hours (if applicable)

---

## Docker Compose Scaling

### Scale Workers

```bash
# Check current state
docker compose ps

# Scale workers
docker compose up -d --scale aragora-worker=5

# Verify
docker compose ps
```

### Scale API (with nginx)

Edit `docker-compose.prod.yml`:

```yaml
services:
  aragora-api:
    deploy:
      replicas: 3
```

Then:

```bash
docker compose up -d
```

### Vertical Scaling

```bash
# Stop services
docker compose down

# Edit resource limits in docker-compose.prod.yml
# services.aragora-api.deploy.resources.limits

# Restart
docker compose up -d
```

---

## Kubernetes Scaling

### Manual Scaling

```bash
# Scale API replicas
kubectl scale deployment aragora-api -n aragora --replicas=5

# Scale workers
kubectl scale deployment aragora-worker -n aragora --replicas=10

# Verify
kubectl get pods -n aragora
```

### Horizontal Pod Autoscaler

```bash
# Create HPA
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: aragora-api-hpa
  namespace: aragora
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: aragora-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF

# Check HPA status
kubectl get hpa -n aragora
kubectl describe hpa aragora-api-hpa -n aragora
```

### Vertical Pod Autoscaler

```bash
# Install VPA
kubectl apply -f https://github.com/kubernetes/autoscaler/releases/download/vertical-pod-autoscaler-0.14.0/vpa-rbac.yaml

# Create VPA
kubectl apply -f - <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: aragora-api-vpa
  namespace: aragora
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: aragora-api
  updatePolicy:
    updateMode: "Auto"
EOF
```

### Cluster Autoscaler

```bash
# For EKS
eksctl create nodegroup \
  --cluster=aragora \
  --name=aragora-workers \
  --nodes-min=3 \
  --nodes-max=20 \
  --node-type=m5.xlarge \
  --enable-autoscaling

# For GKE
gcloud container clusters update aragora \
  --enable-autoscaling \
  --min-nodes=3 \
  --max-nodes=20 \
  --node-pool=default-pool
```

---

## Database Scaling

### Read Replicas

```bash
# AWS RDS
aws rds create-db-instance-read-replica \
  --db-instance-identifier aragora-replica \
  --source-db-instance-identifier aragora-primary

# Update connection string for read-heavy workloads
DATABASE_READ_URL=postgresql://user:pass@replica.rds.amazonaws.com/aragora
```

### Vertical Scaling (PostgreSQL)

```bash
# AWS RDS
aws rds modify-db-instance \
  --db-instance-identifier aragora \
  --db-instance-class db.r6g.xlarge \
  --apply-immediately

# GCP Cloud SQL
gcloud sql instances patch aragora \
  --tier=db-custom-4-15360
```

### Connection Pooling

```bash
# Install PgBouncer
helm install pgbouncer bitnami/pgbouncer \
  --set databases.aragora="host=postgres port=5432 dbname=aragora" \
  --set users.aragora="password=xxx" \
  --set poolSize=100
```

---

## Redis Scaling

### Memory Increase

```bash
# AWS ElastiCache
aws elasticache modify-cache-cluster \
  --cache-cluster-id aragora-redis \
  --cache-node-type cache.r6g.large \
  --apply-immediately
```

### Redis Cluster (for HA)

```bash
# Kubernetes
helm upgrade aragora-redis bitnami/redis \
  --set cluster.enabled=true \
  --set cluster.slaveCount=2
```

---

## Verification Steps

After any scaling operation:

```bash
# 1. Check pod/container status
kubectl get pods -n aragora
# or
docker compose ps

# 2. Check service health
curl http://aragora.company.com/health

# 3. Check metrics
kubectl top pods -n aragora
# or
docker stats

# 4. Monitor logs for errors
kubectl logs -f deployment/aragora-api -n aragora
# or
docker compose logs -f aragora-api

# 5. Run smoke tests
curl -X POST http://aragora.company.com/api/v1/debates/test

# 6. Check queue depth
redis-cli -h redis.aragora LLEN aragora:queue:default
```

---

## Rollback Procedures

### Kubernetes

```bash
# Revert to previous replica count
kubectl rollout undo deployment/aragora-api -n aragora

# Or set specific revision
kubectl rollout undo deployment/aragora-api -n aragora --to-revision=3
```

### Docker Compose

```bash
# Restore previous state
docker compose up -d --scale aragora-worker=3
```

---

## Emergency Scaling

For sudden traffic spikes:

```bash
# Kubernetes - immediate scale
kubectl scale deployment aragora-api -n aragora --replicas=20

# Disable non-critical features
kubectl set env deployment/aragora-api \
  FEATURE_ANALYTICS=false \
  FEATURE_EXPORT=false

# Increase resource limits temporarily
kubectl patch deployment aragora-api -n aragora -p '
spec:
  template:
    spec:
      containers:
      - name: aragora-api
        resources:
          limits:
            cpu: "8"
            memory: "16Gi"
'
```

---

## See Also

- [Incident Response Runbook](./incident-response-procedures)
- [Monitoring Setup Runbook](./monitoring-setup)
- [Deployment Decision Matrix](../deployment/decision-matrix)
