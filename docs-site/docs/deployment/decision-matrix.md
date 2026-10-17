---
title: Deployment Decision Matrix
description: Deployment Decision Matrix
---

# Deployment Decision Matrix

Choose the right deployment strategy for your environment.

## Quick Comparison

| Criteria | Docker Compose | Kubernetes | Cloud Managed |
|----------|---------------|------------|---------------|
| **Complexity** | Low | High | Medium |
| **Scalability** | Limited | Excellent | Excellent |
| **Cost (small)** | $50-200/mo | $200-500/mo | $100-300/mo |
| **Cost (large)** | $200-500/mo | $500-2000/mo | $500-3000/mo |
| **Setup Time** | 1-2 hours | 1-2 days | 2-4 hours |
| **Team Size** | 1-10 users | 10-1000+ users | 1-100 users |
| **HA Support** | Manual | Built-in | Built-in |
| **Best For** | Dev/Small teams | Enterprise | Mid-size orgs |

---

## Decision Flowchart

```
                    START
                      │
                      ▼
           ┌─────────────────────┐
           │ Team size > 50 or   │
           │ need auto-scaling?  │
           └──────────┬──────────┘
                      │
            ┌────NO───┴───YES────┐
            │                    │
            ▼                    ▼
  ┌─────────────────┐  ┌─────────────────┐
  │ Need HA/DR?     │  │ Existing K8s?   │
  └────────┬────────┘  └────────┬────────┘
           │                    │
     ┌─NO──┴──YES─┐       ┌─NO──┴──YES─┐
     │            │       │            │
     ▼            ▼       ▼            ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Docker  │ │ Cloud   │ │ Cloud   │ │Kubernetes│
│ Compose │ │ Managed │ │ Managed │ │          │
└─────────┘ └─────────┘ └─────────┘ └─────────┘
```

---

## Option 1: Docker Compose

**Best for:** Development, small teams, proof-of-concept.

### Requirements

- Linux server with 4+ CPU, 16GB RAM
- Docker 24.0+
- Docker Compose v2.20+
- 100GB SSD storage

### Quick Start

```bash
# Clone and configure
git clone https://github.com/company/aragora.git
cd aragora
cp .env.example .env

# Edit configuration
nano .env

# Start services
docker compose -f docker-compose.prod.yml up -d

# Verify
docker compose ps
curl http://localhost:8080/health
```

### Services

| Service | Port | Purpose |
|---------|------|---------|
| aragora-api | 8080 | Main API server |
| aragora-worker | - | Background jobs |
| postgres | 5432 | Database |
| redis | 6379 | Cache/queue |
| nginx | 80/443 | Reverse proxy |

### Scaling

```bash
# Scale workers
docker compose up -d --scale aragora-worker=3
```

### Limitations

- Single-host only
- Manual failover
- No auto-scaling
- Limited monitoring

---

## Option 2: Kubernetes

**Best for:** Enterprise, large teams, high availability requirements.

### Requirements

- Kubernetes 1.28+
- Helm 3.12+
- kubectl configured
- 3+ node cluster (production)

### Quick Start

```bash
# Add Helm repo
helm repo add aragora https://charts.aragora.io
helm repo update

# Install
helm install aragora aragora/aragora \
  --namespace aragora \
  --create-namespace \
  --values values-production.yaml

# Verify
kubectl get pods -n aragora
kubectl get svc -n aragora
```

### Helm Values (values-production.yaml)

```yaml
replicaCount:
  api: 3
  worker: 5

resources:
  api:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "4"
      memory: "8Gi"

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20
  targetCPUUtilization: 70

postgresql:
  enabled: true
  primary:
    persistence:
      size: 100Gi

redis:
  enabled: true
  master:
    persistence:
      size: 10Gi

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: aragora.company.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: aragora-tls
      hosts:
        - aragora.company.com

monitoring:
  enabled: true
  prometheus:
    enabled: true
  grafana:
    enabled: true
```

### High Availability

```yaml
# Multiple replicas across zones
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: aragora-api
        topologyKey: topology.kubernetes.io/zone

# Pod disruption budget
podDisruptionBudget:
  enabled: true
  minAvailable: 2
```

---

## Option 3: Cloud Managed

**Best for:** Teams wanting managed infrastructure with minimal ops overhead.

### AWS

```bash
# ECS deployment
aws cloudformation create-stack \
  --stack-name aragora \
  --template-body file://cloudformation/aragora-ecs.yaml \
  --parameters \
    ParameterKey=Environment,ParameterValue=production \
    ParameterKey=DBInstanceClass,ParameterValue=db.r6g.large

# Or use CDK
cdk deploy AragoraStack
```

**Services Used:**
- ECS Fargate / EKS
- RDS PostgreSQL
- ElastiCache Redis
- ALB
- CloudWatch

**Estimated Cost:** $300-1500/month

### GCP

```bash
# Cloud Run deployment
gcloud run deploy aragora \
  --image gcr.io/aragora/api:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="DATABASE_URL=$DATABASE_URL"

# Or use GKE
gcloud container clusters create aragora \
  --num-nodes=3 \
  --machine-type=e2-standard-4
```

**Services Used:**
- Cloud Run / GKE
- Cloud SQL
- Memorystore
- Cloud Load Balancing
- Cloud Monitoring

**Estimated Cost:** $250-1200/month

### Azure

```bash
# Container Apps deployment
az containerapp create \
  --name aragora \
  --resource-group aragora-rg \
  --environment aragora-env \
  --image aragora.azurecr.io/api:latest \
  --target-port 8080 \
  --ingress external
```

**Services Used:**
- Container Apps / AKS
- Azure Database for PostgreSQL
- Azure Cache for Redis
- Application Gateway
- Azure Monitor

**Estimated Cost:** $280-1300/month

---

## Resource Sizing

### Small (1-10 users)

| Component | CPU | Memory | Storage |
|-----------|-----|--------|---------|
| API | 2 cores | 4GB | - |
| Worker | 1 core | 2GB | - |
| PostgreSQL | 2 cores | 4GB | 50GB |
| Redis | 1 core | 2GB | 10GB |

### Medium (10-100 users)

| Component | CPU | Memory | Storage |
|-----------|-----|--------|---------|
| API (x3) | 4 cores | 8GB | - |
| Worker (x5) | 2 cores | 4GB | - |
| PostgreSQL | 4 cores | 16GB | 200GB |
| Redis | 2 cores | 8GB | 20GB |

### Large (100-1000 users)

| Component | CPU | Memory | Storage |
|-----------|-----|--------|---------|
| API (x10) | 8 cores | 16GB | - |
| Worker (x20) | 4 cores | 8GB | - |
| PostgreSQL | 16 cores | 64GB | 1TB |
| Redis Cluster | 8 cores | 32GB | 50GB |

---

## Checklist Before Deployment

### Security

- [ ] TLS certificates configured
- [ ] Secrets management (Vault/AWS Secrets Manager)
- [ ] Network policies/security groups
- [ ] WAF rules configured
- [ ] Vulnerability scanning enabled

### Monitoring

- [ ] Prometheus/CloudWatch metrics
- [ ] Log aggregation (ELK/CloudWatch Logs)
- [ ] Alerting rules configured
- [ ] Uptime monitoring

### Backup

- [ ] Database backup schedule
- [ ] Backup retention policy
- [ ] Disaster recovery plan tested

### Performance

- [ ] Load testing completed
- [ ] CDN configured for static assets
- [ ] Database connection pooling
- [ ] Redis caching enabled

---

## See Also

- [Scaling Runbook](../operations/scaling)
- [Database Migration Runbook](../operations/database-migration)
- [Incident Response Runbook](../operations/incident-response-procedures)
- [Monitoring Setup Runbook](../operations/monitoring-setup)
