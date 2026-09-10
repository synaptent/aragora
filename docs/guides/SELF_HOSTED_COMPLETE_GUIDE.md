# Aragora Self-Hosted Complete Guide

**Version:** 2.10.0
**Last Updated:** 2026-09-04

The definitive guide for deploying Aragora on your own infrastructure—from 5-minute quick starts to enterprise-grade high availability.

---

## Table of Contents

- [Part 1: Planning Your Deployment](#part-1-planning-your-deployment)
- [Part 2: Simple Profile (SQLite)](#part-2-simple-profile-sqlite)
- [Part 3: SME Profile (PostgreSQL + Redis)](#part-3-sme-profile-postgresql--redis)
- [Part 4: Production Profile (Kubernetes HA)](#part-4-production-profile-kubernetes-ha)
- [Part 5: Security & TLS](#part-5-security--tls)
- [Part 6: Monitoring & Observability](#part-6-monitoring--observability)
- [Part 7: Operations](#part-7-operations)
- [Part 8: Troubleshooting](#part-8-troubleshooting)
- [Appendices](#appendices)

---

# Part 1: Planning Your Deployment

## 1.1 Deployment Profiles Overview

Aragora offers three deployment profiles optimized for different scales and requirements:

| Profile | Use Case | Database | Setup Time | Complexity |
|---------|----------|----------|------------|------------|
| **Simple** | Personal use, testing, demos | SQLite | 5 minutes | Low |
| **SME** | Small businesses, teams up to 50 | PostgreSQL + Redis | 30 minutes | Medium |
| **Production** | Enterprise, high availability | PostgreSQL HA + Redis + Kubernetes | 2-4 hours | High |

### Profile Feature Comparison

| Feature | Simple | SME | Production |
|---------|--------|-----|------------|
| Concurrent debates | 1-5 | 5-20 | 50+ |
| Data persistence | Docker volume | Managed DB | HA cluster |
| Horizontal scaling | No | Limited | Yes |
| TLS | Optional | Recommended | Required |
| Monitoring | Logs only | Prometheus | Full stack |
| Backup automation | Manual | Scheduled | Continuous |
| High availability | No | No | Yes |
| Recovery time objective | Hours | 1 hour | < 15 min |

## 1.2 Hardware Requirements

### Minimum Requirements by Profile

| Resource | Simple | SME | Production (per node) |
|----------|--------|-----|----------------------|
| CPU | 1 core | 2 cores | 4 cores |
| Memory | 2 GB | 4 GB | 8 GB |
| Storage | 5 GB | 20 GB | 50 GB SSD |
| Network | 10 Mbps | 100 Mbps | 1 Gbps |

### Recommended Requirements

| Resource | Simple | SME | Production (per node) |
|----------|--------|-----|----------------------|
| CPU | 2 cores | 4 cores | 8 cores |
| Memory | 4 GB | 8 GB | 16 GB |
| Storage | 20 GB SSD | 100 GB SSD | 200 GB NVMe |
| Network | 100 Mbps | 1 Gbps | 10 Gbps |

### Scaling Guidelines

| Concurrent Debates | Replicas | CPU (total) | Memory (total) |
|-------------------|----------|-------------|----------------|
| 1-5 | 1 | 1 core | 2 GB |
| 5-20 | 2-3 | 4 cores | 8 GB |
| 20-50 | 3-5 | 8 cores | 16 GB |
| 50+ | 5-10 | 16+ cores | 32+ GB |

## 1.3 Decision Matrix

### Choose Simple Profile If:
- You're evaluating Aragora
- Personal or hobby project
- Single user or small team (< 5)
- No high availability requirement
- Limited infrastructure expertise

### Choose SME Profile If:
- Small business or startup
- Team of 5-50 users
- Need PostgreSQL for data integrity
- Want scheduled backups
- Moderate availability needs

### Choose Production Profile If:
- Enterprise deployment
- 50+ concurrent users
- High availability required (99.9%+ uptime)
- Compliance requirements (SOC 2, GDPR)
- Multi-region deployment needed

## 1.4 Pre-Deployment Checklist

### All Profiles

- [ ] Docker 20.10+ installed (`docker --version`)
- [ ] Docker Compose 2.0+ installed (`docker compose version`)
- [ ] At least one AI provider API key obtained:
  - Anthropic: https://console.anthropic.com
  - OpenAI: https://platform.openai.com
  - OpenRouter: https://openrouter.ai (recommended as fallback)
- [ ] Git installed for cloning repository
- [ ] Firewall allows outbound HTTPS (port 443)

### SME Profile Additional

- [ ] Domain name registered (for TLS)
- [ ] DNS configured to point to server
- [ ] Adequate disk space for PostgreSQL (20+ GB)

### Production Profile Additional

- [ ] Kubernetes cluster 1.25+ available
- [ ] `kubectl` configured and working
- [ ] Helm 3.x installed (optional)
- [ ] cert-manager for TLS automation
- [ ] Container registry access
- [ ] Load balancer provisioned

---

# Part 2: Simple Profile (SQLite)

**Time to complete: 5 minutes**

The Simple profile uses SQLite for storage, requiring no external dependencies.

## 2.1 Quick Start

### Step 1: Clone Repository

```bash
git clone https://github.com/synaptent/aragora.git
cd aragora
```

### Step 2: Configure Environment

```bash
# Copy the example configuration
cp .env.example .env

# Edit with your API key
nano .env  # or vim, code, etc.
```

Add at least one API key:

```bash
# .env - Minimum configuration
ANTHROPIC_API_KEY=sk-ant-api03-...

# OR use OpenAI
OPENAI_API_KEY=sk-...

# RECOMMENDED: Add OpenRouter as fallback
OPENROUTER_API_KEY=sk-or-...
```

### Step 3: Start Aragora

```bash
docker compose -f docker-compose.simple.yml up -d
```

### Step 4: Verify Installation

```bash
# Check container is running
docker compose -f docker-compose.simple.yml ps

# Check health endpoint
curl http://localhost:8080/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "2.10.0",
  "database": "connected",
  "agents_available": 15
}
```

### Step 5: Run Your First Debate

```bash
# Via API
curl -X POST http://localhost:8080/api/debates \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "What is the best programming language for beginners?",
    "rounds": 2
  }'
```

**Aragora is now running at http://localhost:8080**

## 2.2 Simple Profile Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | One of | - | Anthropic Claude API key |
| `OPENAI_API_KEY` | these | - | OpenAI API key |
| `OPENROUTER_API_KEY` | - | - | OpenRouter fallback key |
| `ARAGORA_PORT` | No | `8080` | HTTP server port |
| `ARAGORA_LOG_LEVEL` | No | `INFO` | Logging verbosity |
| `ARAGORA_DEFAULT_ROUNDS` | No | `9` | Default debate rounds |
| `ARAGORA_DEBATE_TIMEOUT` | No | `600` | Debate timeout (seconds) |

### docker-compose.simple.yml Overview

```yaml
services:
  aragora:
    build: .
    ports:
      - "8080:8080"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
      - ARAGORA_DB_BACKEND=sqlite
    volumes:
      - aragora-data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  aragora-data:
```

## 2.3 Data Persistence

Data is stored in the `aragora-data` Docker volume:

| Path | Contents |
|------|----------|
| `/app/data/aragora.db` | SQLite database |
| `/app/data/elo_ratings.json` | Agent ELO ratings |
| `/app/data/memory/` | Continuum memory tiers |
| `/app/data/backups/` | Manual backups |

### Manual Backup

```bash
# Create backup
docker compose -f docker-compose.simple.yml exec aragora \
  sqlite3 /app/data/aragora.db ".backup /app/data/backups/backup_$(date +%Y%m%d).db"

# Copy backup to host
docker cp $(docker compose -f docker-compose.simple.yml ps -q aragora):/app/data/backups/ ./backups/
```

### Restore from Backup

```bash
# Stop Aragora
docker compose -f docker-compose.simple.yml down

# Replace database
docker run --rm -v aragora-data:/data -v $(pwd)/backups:/backups alpine \
  cp /backups/backup_20260127.db /data/aragora.db

# Restart
docker compose -f docker-compose.simple.yml up -d
```

## 2.4 Upgrading to SME Profile

When you outgrow the Simple profile:

1. **Export your data:**
```bash
docker compose -f docker-compose.simple.yml exec aragora \
  python scripts/export_to_postgres.py --output /app/data/export.sql
```

2. **Stop Simple deployment:**
```bash
docker compose -f docker-compose.simple.yml down
```

3. **Continue with SME Profile setup below**

4. **Import data to PostgreSQL:**
```bash
docker compose -f docker-compose.sme.yml exec postgres \
  psql -U aragora aragora < /app/data/export.sql
```

---

# Part 3: SME Profile (PostgreSQL + Redis)

**Time to complete: 30 minutes**

The SME profile adds PostgreSQL for robust data storage, Redis for caching, and optional worker containers for parallel processing.

## 3.1 Setup Guide

### Step 1: Configure Environment

```bash
cp .env.example .env
nano .env
```

**SME Configuration:**

```bash
# .env

# Environment
ARAGORA_ENV=production
ARAGORA_ENVIRONMENT=production

# AI Providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...  # Recommended fallback

# Database (PostgreSQL)
POSTGRES_USER=aragora
POSTGRES_PASSWORD=your-secure-password-here  # CHANGE THIS!
POSTGRES_DB=aragora
ARAGORA_DB_BACKEND=postgres
ARAGORA_POSTGRES_DSN=postgresql://aragora:your-secure-password-here@postgres:5432/aragora

# Redis
REDIS_URL=redis://redis:6379/0

# Security
ARAGORA_JWT_SECRET=your-jwt-secret-minimum-32-characters  # GENERATE THIS!
ARAGORA_ALLOWED_ORIGINS=https://your-domain.com

# Performance
ARAGORA_MAX_CONCURRENT_DEBATES=10
ARAGORA_DB_POOL_SIZE=20
```

**Generate secure secrets:**

```bash
# Generate JWT secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate database password
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### Step 2: Start Services

```bash
# Start PostgreSQL and Redis first
docker compose -f docker-compose.sme.yml up -d postgres redis

# Wait for databases to be ready
sleep 10

# Initialize database schema
docker compose -f docker-compose.sme.yml run --rm aragora \
  python scripts/init_postgres_db.py

# Start all services
docker compose -f docker-compose.sme.yml up -d
```

### Step 3: Verify Installation

```bash
# Check all services are running
docker compose -f docker-compose.sme.yml ps

# Health check
curl http://localhost:8080/api/health

# Database health
curl http://localhost:8080/api/health/db
```

### Step 4: Enable Workers (Optional)

For parallel debate processing:

```bash
docker compose -f docker-compose.sme.yml --profile with-workers up -d
```

## 3.2 PostgreSQL Configuration

### Connection Tuning

Edit `deploy/postgres/postgresql.conf`:

```ini
# Connection settings
max_connections = 100
shared_buffers = 256MB
work_mem = 16MB
maintenance_work_mem = 64MB

# Write-ahead log
wal_level = replica
max_wal_size = 1GB
min_wal_size = 80MB

# Query planning
effective_cache_size = 768MB
random_page_cost = 1.1
```

### Connection Pooling

For high connection counts, add PgBouncer:

```yaml
# Add to docker-compose.sme.yml
pgbouncer:
  image: edoburu/pgbouncer:latest
  environment:
    DATABASE_URL: postgresql://aragora:${POSTGRES_PASSWORD}@postgres:5432/aragora
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 200
    DEFAULT_POOL_SIZE: 20
  ports:
    - "6432:5432"
  depends_on:
    postgres:
      condition: service_healthy
```

Update `ARAGORA_POSTGRES_DSN` to use PgBouncer:
```bash
ARAGORA_POSTGRES_DSN=postgresql://aragora:password@pgbouncer:5432/aragora
```

## 3.3 Redis Configuration

### Memory Management

```bash
# In docker-compose.sme.yml, Redis is configured with:
redis:
  command: >
    redis-server
    --appendonly yes
    --maxmemory 512mb
    --maxmemory-policy volatile-lru
```

### Redis Persistence

Redis data is stored in the `redis-data` volume with:
- **AOF (Append-Only File)**: For durability
- **LRU eviction**: Automatically removes old cache entries

## 3.4 Backup Configuration

### Automated PostgreSQL Backups

Create `scripts/backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}

# Create backup
pg_dump -U aragora aragora | gzip > "${BACKUP_DIR}/aragora_${TIMESTAMP}.sql.gz"

# Clean old backups
find ${BACKUP_DIR} -name "aragora_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "Backup completed: aragora_${TIMESTAMP}.sql.gz"
```

Add backup service to docker-compose:

```yaml
backup:
  image: postgres:16-alpine
  environment:
    PGHOST: postgres
    PGUSER: aragora
    PGPASSWORD: ${POSTGRES_PASSWORD}
  volumes:
    - ./scripts/backup.sh:/backup.sh:ro
    - ./backups:/backups
  entrypoint: /bin/sh
  command: -c "while true; do /backup.sh; sleep 86400; done"
  depends_on:
    postgres:
      condition: service_healthy
```

### Manual Backup

```bash
# Create immediate backup
docker compose -f docker-compose.sme.yml exec postgres \
  pg_dump -U aragora aragora > backup_$(date +%Y%m%d).sql

# Backup with compression
docker compose -f docker-compose.sme.yml exec postgres \
  pg_dump -U aragora aragora | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Restore from Backup

```bash
# Stop Aragora (keep database running)
docker compose -f docker-compose.sme.yml stop aragora

# Restore
cat backup.sql | docker compose -f docker-compose.sme.yml exec -T postgres \
  psql -U aragora aragora

# Restart Aragora
docker compose -f docker-compose.sme.yml start aragora
```

---

# Part 4: Production Profile (Kubernetes HA)

**Time to complete: 2-4 hours**

The Production profile provides enterprise-grade deployment with high availability, auto-scaling, and comprehensive monitoring.

## 4.1 Architecture Overview

```
                    ┌─────────────────┐
                    │   Ingress/LB    │
                    │   (Traefik)     │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
        │  Aragora  │  │  Aragora  │  │  Aragora  │
        │ Replica 1 │  │ Replica 2 │  │ Replica 3 │
        │  Zone A   │  │  Zone B   │  │  Zone C   │
        └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
  ┌─────▼─────┐        ┌─────▼─────┐        ┌─────▼─────┐
  │PostgreSQL │        │   Redis   │        │  Workers  │
  │  Primary  │        │  Cluster  │        │  (2-5)    │
  └───────────┘        └───────────┘        └───────────┘
```

## 4.2 Kubernetes Deployment

### Step 1: Create Namespace

```bash
kubectl create namespace aragora
```

### Step 2: Configure Secrets

```bash
# Create API key secrets
kubectl create secret generic aragora-api-keys \
  --namespace aragora \
  --from-literal=ANTHROPIC_API_KEY='sk-ant-api03-...' \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --from-literal=OPENROUTER_API_KEY='sk-or-...'

# Create database secrets
kubectl create secret generic aragora-db \
  --namespace aragora \
  --from-literal=POSTGRES_PASSWORD='your-secure-password' \
  --from-literal=DATABASE_URL='postgresql://aragora:password@postgres:5432/aragora'

# Create Redis secrets
kubectl create secret generic aragora-redis \
  --namespace aragora \
  --from-literal=REDIS_URL='redis://redis:6379'

# Create JWT secret
kubectl create secret generic aragora-jwt \
  --namespace aragora \
  --from-literal=ARAGORA_JWT_SECRET='your-32-char-jwt-secret'
```

### Step 3: Deploy Core Components

```bash
# Apply all Kubernetes manifests
kubectl apply -k deploy/kubernetes/

# Watch deployment progress
kubectl -n aragora rollout status deployment/aragora

# Verify pods are running
kubectl -n aragora get pods -o wide
```

### Step 4: Configure Ingress

Edit `deploy/kubernetes/ingress.yaml` with your domain:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aragora
  namespace: aragora
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    # WebSocket support
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "aragora-affinity"
spec:
  tls:
    - hosts:
        - api.your-domain.com
      secretName: aragora-tls
  rules:
    - host: api.your-domain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: aragora
                port:
                  number: 80
```

Apply ingress:
```bash
kubectl apply -f deploy/kubernetes/ingress.yaml
```

## 4.3 PostgreSQL High Availability

### Option 1: Managed Database (Recommended)

Use cloud-managed PostgreSQL for production:

**AWS RDS:**
```bash
DATABASE_URL=postgresql://aragora:pass@aragora.xxxxx.us-east-1.rds.amazonaws.com:5432/aragora?sslmode=require
```

**Google Cloud SQL:**
```bash
# Use Cloud SQL Auth Proxy
DATABASE_URL=postgresql://aragora:pass@localhost:5432/aragora
```

**Supabase:**
```bash
DATABASE_URL=postgresql://postgres.xxxx:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

### Option 2: Self-Managed StatefulSet

```yaml
# deploy/kubernetes/postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: aragora
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_USER
              value: aragora
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: aragora-db
                  key: POSTGRES_PASSWORD
            - name: POSTGRES_DB
              value: aragora
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "4Gi"
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: ssd
        resources:
          requests:
            storage: 100Gi
```

## 4.4 Auto-Scaling

### Horizontal Pod Autoscaler

```yaml
# deploy/kubernetes/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: aragora
  namespace: aragora
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: aragora
  minReplicas: 3
  maxReplicas: 10
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
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
    scaleUp:
      stabilizationWindowSeconds: 60
```

### Pod Disruption Budget

```yaml
# deploy/kubernetes/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: aragora
  namespace: aragora
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: aragora
```

### Topology Spread

```yaml
# In deployment spec
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app: aragora
```

## 4.5 Docker Compose Production Alternative

For production without Kubernetes, use `docker-compose.production.yml`:

```bash
# Configure production environment
cp .env.production.example .env.production

# Edit with your domain and secrets
nano .env.production

# Start production stack
docker compose -f docker-compose.production.yml up -d
```

This includes:
- **Traefik**: Reverse proxy with auto-TLS
- **PostgreSQL 16**: With tuned configuration
- **Redis 7**: With persistence
- **Prometheus + Grafana**: Full monitoring
- **Loki + Promtail**: Log aggregation
- **Automatic backups**: S3-compatible storage

---

# Part 5: Security & TLS

## 5.1 TLS Configuration by Environment

| Environment | TLS Required | Certificate Type | Method |
|-------------|--------------|------------------|--------|
| Development | Optional | Self-signed | OpenSSL |
| Staging | Yes | Let's Encrypt staging | Certbot/cert-manager |
| Production | **Required** | Let's Encrypt / Commercial | Traefik/cert-manager |

## 5.2 Let's Encrypt with Traefik (Docker)

Traefik automatically handles TLS in production Docker deployments:

```yaml
# docker-compose.production.yml (excerpt)
traefik:
  command:
    # Let's Encrypt configuration
    - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"
    - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    - "--certificatesresolvers.letsencrypt.acme.httpchallenge=true"
    - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
```

Required environment variables:
```bash
DOMAIN=api.your-domain.com
ACME_EMAIL=admin@your-domain.com
```

## 5.3 Let's Encrypt with cert-manager (Kubernetes)

### Install cert-manager

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# Verify installation
kubectl wait --for=condition=ready pod -l app=cert-manager -n cert-manager --timeout=120s
```

### Create ClusterIssuer

```yaml
# cluster-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@your-domain.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - http01:
          ingress:
            class: nginx
```

```bash
kubectl apply -f cluster-issuer.yaml
```

### Verify Certificate Issuance

```bash
# Check certificate status
kubectl -n aragora get certificate

# Describe for details
kubectl -n aragora describe certificate aragora-tls

# Verify HTTPS works
curl -v https://api.your-domain.com/api/health
```

## 5.4 Manual TLS with Nginx

For environments without Traefik:

```nginx
# /etc/nginx/sites-available/aragora
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;

    ssl_certificate /etc/letsencrypt/live/api.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-domain.com/privkey.pem;

    # Modern TLS configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;

    # HSTS (enable after testing)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name api.your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

## 5.5 Security Hardening Checklist

### Production Required

- [ ] `ARAGORA_ENV=production` set
- [ ] `ARAGORA_JWT_SECRET` is 32+ random characters
- [ ] `ARAGORA_ALLOWED_ORIGINS` configured (no wildcards)
- [ ] TLS/HTTPS enabled with valid certificate
- [ ] Rate limiting enabled
- [ ] API authentication enabled

### Network Security

```bash
# Firewall rules (example for ufw)
ufw allow 443/tcp   # HTTPS
ufw allow 80/tcp    # HTTP (redirect to HTTPS)
ufw deny 8080/tcp   # Block direct API access
ufw deny 5432/tcp   # Block PostgreSQL
ufw deny 6379/tcp   # Block Redis
```

### Container Security

```yaml
# Security context for pods
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
```

---

# Part 6: Monitoring & Observability

## 6.1 Health Endpoints

| Endpoint | Description | Expected Response |
|----------|-------------|-------------------|
| `GET /api/health` | Basic health check | `{"status": "healthy"}` |
| `GET /api/health/db` | Database connectivity | `{"database": "connected"}` |
| `GET /api/health/redis` | Redis connectivity | `{"redis": "connected"}` |
| `GET /api/health/ready` | Full readiness check | 200 if ready |
| `GET /metrics` | Prometheus metrics | Prometheus format |

### Health Check Script

```bash
#!/bin/bash
# health-check.sh

API_URL="${1:-http://localhost:8080}"

check_endpoint() {
    response=$(curl -sf "$API_URL/api/$1" 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "✓ $1: OK"
    else
        echo "✗ $1: FAILED"
        return 1
    fi
}

echo "Checking Aragora health..."
check_endpoint "health"
check_endpoint "health/db"
check_endpoint "health/ready"
```

## 6.2 Prometheus Configuration

### Prometheus Scrape Config

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'aragora'
    static_configs:
      - targets: ['aragora:8080']
    metrics_path: '/metrics'
    scrape_interval: 30s
```

### Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `aragora_debates_total` | Total debates run | - |
| `aragora_debate_duration_seconds` | Debate duration histogram | p95 > 5min |
| `aragora_agent_errors_total` | Agent error count | > 10/min |
| `aragora_consensus_rate` | Consensus achievement rate | < 0.7 |
| `aragora_http_requests_total` | HTTP request count | - |
| `aragora_http_request_duration_seconds` | Request latency | p99 > 2s |

### Alerting Rules

```yaml
# alerts.yml
groups:
  - name: aragora
    rules:
      - alert: AragoraHighErrorRate
        expr: |
          sum(rate(aragora_http_requests_total{status=~"5.."}[5m]))
          / sum(rate(aragora_http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate (> 5%)"

      - alert: AragoraSlowDebates
        expr: |
          histogram_quantile(0.95, sum(rate(aragora_debate_duration_seconds_bucket[15m])) by (le)) > 300
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Debate p95 latency > 5 minutes"

      - alert: AragoraAgentFailures
        expr: rate(aragora_agent_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent failure rate elevated"
```

## 6.3 Grafana Dashboards

### Access Grafana

**Docker Production:**
```
https://your-domain.com/grafana
Default credentials: admin / (set via GRAFANA_ADMIN_PASSWORD)
```

**Kubernetes:**
```bash
kubectl -n monitoring port-forward svc/grafana 3000:3000
# Open http://localhost:3000
```

### Pre-built Dashboards

Import from `deploy/observability/grafana/dashboards/`:

1. **aragora-overview.json**: API performance, debate throughput
2. **aragora-agents.json**: Agent response times, error rates
3. **aragora-resources.json**: Memory, CPU, connections

### Useful PromQL Queries

```promql
# Error rate (%)
sum(rate(aragora_http_requests_total{status=~"5.."}[5m]))
/ sum(rate(aragora_http_requests_total[5m])) * 100

# P95 latency
histogram_quantile(0.95,
  sum(rate(aragora_http_request_duration_seconds_bucket[5m])) by (le))

# Active debates
aragora_active_debates

# Memory usage (GB)
process_resident_memory_bytes{job="aragora"} / 1024 / 1024 / 1024
```

## 6.4 Log Aggregation

### Docker Logs

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f aragora

# Last 100 lines
docker compose logs --tail 100 aragora
```

### Kubernetes Logs

```bash
# All pods
kubectl -n aragora logs -l app=aragora --tail=100

# Specific pod
kubectl -n aragora logs aragora-xxxxx -f

# Previous pod (after restart)
kubectl -n aragora logs aragora-xxxxx --previous
```

### Loki + Promtail (Production)

Included in `docker-compose.production.yml`:
- **Loki**: Log aggregation backend
- **Promtail**: Log collector from containers
- **Grafana**: Log visualization via Explore tab

---

# Part 7: Operations

## 7.1 Backup & Restore

### PostgreSQL Backup

```bash
# Create backup with timestamp
docker compose exec postgres pg_dump -U aragora aragora > \
  "backup_$(date +%Y%m%d_%H%M%S).sql"

# Compressed backup
docker compose exec postgres pg_dump -U aragora aragora | gzip > \
  "backup_$(date +%Y%m%d).sql.gz"
```

### PostgreSQL Restore

```bash
# Stop application
docker compose stop aragora

# Restore from backup
cat backup.sql | docker compose exec -T postgres psql -U aragora aragora

# Restart application
docker compose start aragora
```

### Knowledge Mound Export/Import

```bash
# Export knowledge base
curl -X POST http://localhost:8080/api/knowledge/export \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -o knowledge_backup.json

# Import knowledge base
curl -X POST http://localhost:8080/api/knowledge/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @knowledge_backup.json
```

### Automated Backup Script

```bash
#!/bin/bash
# /opt/aragora/backup.sh

BACKUP_DIR="/backups/aragora"
S3_BUCKET="${BACKUP_S3_BUCKET:-}"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# PostgreSQL backup
docker compose exec -T postgres pg_dump -U aragora aragora | \
  gzip > "${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz"

# Upload to S3 (if configured)
if [ -n "$S3_BUCKET" ]; then
  aws s3 cp "${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz" \
    "s3://${S3_BUCKET}/aragora/postgres_${TIMESTAMP}.sql.gz"
fi

# Clean old backups
find $BACKUP_DIR -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: postgres_${TIMESTAMP}.sql.gz"
```

Add to crontab:
```bash
0 2 * * * /opt/aragora/backup.sh >> /var/log/aragora-backup.log 2>&1
```

## 7.2 Rolling Updates

### Docker Compose

```bash
# Pull latest images
docker compose pull

# Recreate containers with new images
docker compose up -d --force-recreate

# Verify health
curl http://localhost:8080/api/health
```

### Kubernetes

```bash
# Update image
kubectl -n aragora set image deployment/aragora \
  aragora=ghcr.io/synaptent/aragora/backend:2.10.0

# Watch rollout
kubectl -n aragora rollout status deployment/aragora

# Verify
kubectl -n aragora get pods
```

### Zero-Downtime Deployment

The production Docker Compose uses rolling updates:

```yaml
deploy:
  update_config:
    parallelism: 1
    delay: 10s
    order: start-first  # New container starts before old stops
    failure_action: rollback
```

## 7.3 Rollback Procedures

### Docker Compose Rollback

```bash
# Stop current deployment
docker compose down

# Checkout previous stable version
git checkout v2.8.0

# Rebuild and start
docker compose up -d --build
```

### Kubernetes Rollback

```bash
# View rollout history
kubectl -n aragora rollout history deployment/aragora

# Rollback to previous version
kubectl -n aragora rollout undo deployment/aragora

# Rollback to specific revision
kubectl -n aragora rollout undo deployment/aragora --to-revision=2

# Verify rollback
kubectl -n aragora rollout status deployment/aragora
```

### Database Rollback

```bash
# Rollback one Alembic migration
docker compose exec aragora alembic downgrade -1

# Rollback to specific revision
docker compose exec aragora alembic downgrade abc123

# Restore from backup (if major issue)
cat pre_upgrade_backup.sql | docker compose exec -T postgres psql -U aragora aragora
```

## 7.4 Maintenance Windows

### Pre-Maintenance Checklist

- [ ] Notify users 48 hours in advance
- [ ] Create fresh database backup
- [ ] Document current version and state
- [ ] Prepare rollback plan
- [ ] Schedule maintenance window in monitoring

### Maintenance Procedure

```bash
# 1. Disable new debate creation
curl -X POST http://localhost:8080/api/admin/maintenance/enable \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Wait for active debates to complete (or timeout)
watch 'curl -s http://localhost:8080/api/admin/stats | jq .active_debates'

# 3. Create backup
./scripts/backup.sh

# 4. Apply updates
docker compose pull
docker compose up -d

# 5. Run migrations
docker compose exec aragora alembic upgrade head

# 6. Verify health
curl http://localhost:8080/api/health

# 7. Disable maintenance mode
curl -X POST http://localhost:8080/api/admin/maintenance/disable \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

# Part 8: Troubleshooting

## 8.1 Quick Diagnostics

```bash
# Check all services
docker compose ps

# View recent logs
docker compose logs --tail=100

# Check resource usage
docker stats

# Test API health
curl -v http://localhost:8080/api/health
```

## 8.2 Common Issues

### Container Won't Start

**Symptoms:** Container exits immediately, CrashLoopBackOff

**Diagnosis:**
```bash
# Check logs
docker compose logs aragora

# Check exit code
docker compose ps -a
```

**Common Causes:**

1. **Missing API key:**
   ```bash
   # Verify API keys are set
   docker compose exec aragora env | grep API_KEY
   ```
   Fix: Add `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to `.env`

2. **Port conflict:**
   ```bash
   # Check if port 8080 is in use
   lsof -i :8080
   ```
   Fix: Change `ARAGORA_PORT` or stop conflicting service

3. **Insufficient memory:**
   ```bash
   # Check available memory
   free -h
   ```
   Fix: Increase Docker memory limit or server RAM

### Database Connection Failed

**Symptoms:** "Connection refused", "Authentication failed"

**Diagnosis:**
```bash
# Check PostgreSQL is running
docker compose ps postgres

# Test connection
docker compose exec postgres pg_isready -U aragora

# Check connection string
docker compose exec aragora env | grep POSTGRES
```

**Solutions:**

1. Wait for PostgreSQL to initialize (first run):
   ```bash
   sleep 30 && docker compose restart aragora
   ```

2. Verify password matches:
   ```bash
   # Password in .env must match container
   grep POSTGRES_PASSWORD .env
   ```

3. Reinitialize database:
   ```bash
   docker compose exec aragora python scripts/init_postgres_db.py
   ```

### Debate Timeouts

**Symptoms:** Debates fail after 15 minutes, "Timeout exceeded"

**Diagnosis:**
```bash
# Check current timeout settings
docker compose exec aragora env | grep TIMEOUT

# Monitor debate duration
docker compose logs aragora | grep "debate_duration"
```

**Solutions:**

1. Increase timeout:
   ```bash
   # In .env
   ARAGORA_DEBATE_TIMEOUT=1800
   ARAGORA_AGENT_TIMEOUT=480
   ```

2. Reduce debate rounds:
   ```bash
   ARAGORA_DEFAULT_ROUNDS=2
   ```

3. Check API provider rate limits

### High Memory Usage

**Symptoms:** Container OOMKilled, slow responses

**Diagnosis:**
```bash
# Check memory usage
docker stats

# Check for memory leaks in logs
docker compose logs aragora | grep -i "memory\|oom"
```

**Solutions:**

1. Reduce concurrent debates:
   ```bash
   ARAGORA_MAX_CONCURRENT_DEBATES=3
   ```

2. Add memory limits:
   ```yaml
   # In docker-compose override
   services:
     aragora:
       deploy:
         resources:
           limits:
             memory: 4G
   ```

3. Enable garbage collection tuning:
   ```bash
   PYTHONMALLOC=malloc
   MALLOC_MMAP_THRESHOLD_=65536
   ```

### API Rate Limiting (429 Errors)

**Symptoms:** "Rate limit exceeded", debates failing

**Diagnosis:**
```bash
# Check error logs
docker compose logs aragora | grep "429\|rate_limit"
```

**Solutions:**

1. Add OpenRouter fallback:
   ```bash
   OPENROUTER_API_KEY=sk-or-...
   ```

2. Reduce concurrent debates:
   ```bash
   ARAGORA_MAX_CONCURRENT_DEBATES=3
   ```

3. Check provider quotas:
   ```bash
   # Anthropic
   curl -H "x-api-key: $ANTHROPIC_API_KEY" \
     https://api.anthropic.com/v1/usage

   # OpenAI
   curl -H "Authorization: Bearer $OPENAI_API_KEY" \
     https://api.openai.com/v1/usage
   ```

### WebSocket Disconnections

**Symptoms:** Real-time updates stop, "Connection lost" errors

**Diagnosis:**
```bash
# Check WebSocket connections
docker compose logs aragora | grep "websocket"

# Test WebSocket
wscat -c ws://localhost:8080/ws
```

**Solutions:**

1. Configure proxy timeouts:
   ```nginx
   # Nginx
   proxy_read_timeout 86400;
   proxy_send_timeout 86400;
   ```

2. Enable sticky sessions (Kubernetes):
   ```yaml
   nginx.ingress.kubernetes.io/affinity: "cookie"
   ```

### TLS Certificate Issues

**Symptoms:** HTTPS not working, certificate errors

**Diagnosis:**
```bash
# Check certificate
echo | openssl s_client -connect your-domain:443 2>/dev/null | \
  openssl x509 -noout -dates

# Check cert-manager (K8s)
kubectl -n aragora describe certificate aragora-tls
```

**Solutions:**

1. Wait for certificate issuance (5-10 minutes)

2. Check DNS points to correct IP:
   ```bash
   dig +short your-domain.com
   ```

3. Verify HTTP-01 challenge path is accessible:
   ```bash
   curl http://your-domain.com/.well-known/acme-challenge/test
   ```

4. Check cert-manager logs:
   ```bash
   kubectl logs -n cert-manager deploy/cert-manager
   ```

---

# Appendices

## Appendix A: Environment Variables Reference

### Core Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_ENVIRONMENT` | `development` | Runtime environment (`development`, `production`) |
| `ARAGORA_PORT` | `8080` | HTTP server port |
| `ARAGORA_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ARAGORA_DB_BACKEND` | `sqlite` | Database backend (`sqlite`, `postgres`) |

### AI Providers

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | - | Anthropic Claude API key |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `OPENROUTER_API_KEY` | - | OpenRouter fallback key |
| `GEMINI_API_KEY` | - | Google Gemini API key |
| `XAI_API_KEY` | - | xAI Grok API key |
| `MISTRAL_API_KEY` | - | Mistral AI API key |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_POSTGRES_DSN` | - | PostgreSQL connection string |
| `DATABASE_URL` | - | Alternative connection string |
| `ARAGORA_DB_POOL_SIZE` | `10` | Connection pool size |
| `POSTGRES_USER` | `aragora` | PostgreSQL username |
| `POSTGRES_PASSWORD` | - | PostgreSQL password |
| `POSTGRES_DB` | `aragora` | PostgreSQL database name |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `ARAGORA_REDIS_URL` | - | Alternative Redis URL |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_JWT_SECRET` | - | JWT signing secret (32+ chars) |
| `ARAGORA_API_TOKEN` | - | API authentication token |
| `ARAGORA_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowed origins |
| `ARAGORA_ENCRYPTION_KEY` | - | Fernet encryption key |

### Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_MAX_CONCURRENT_DEBATES` | `5` | Max parallel debates |
| `ARAGORA_DEBATE_TIMEOUT` | `600` | Debate timeout (seconds) |
| `ARAGORA_AGENT_TIMEOUT` | `240` | Per-agent timeout (seconds) |
| `ARAGORA_DEFAULT_ROUNDS` | `9` | Default debate rounds |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OpenTelemetry collector endpoint |

See `docs/ENVIRONMENT.md` for the complete reference (70+ variables).

## Appendix B: Docker Compose Comparison

| Feature | simple.yml | sme.yml | production.yml |
|---------|------------|---------|----------------|
| Database | SQLite | PostgreSQL | PostgreSQL HA |
| Cache | None | Redis | Redis cluster |
| Workers | None | Optional | Included |
| TLS | None | Manual | Traefik auto |
| Monitoring | None | Basic | Full stack |
| Replicas | 1 | 1 | 2+ |
| Volumes | 1 | 3 | 10+ |

## Appendix C: Kubernetes Manifest Summary

| Manifest | Purpose |
|----------|---------|
| `deployment.yaml` | Core Aragora deployment |
| `service.yaml` | ClusterIP service |
| `ingress.yaml` | Ingress with TLS |
| `hpa.yaml` | Horizontal pod autoscaler |
| `pdb.yaml` | Pod disruption budget |
| `configmap.yaml` | Non-secret configuration |
| `secret.yaml` | Secret configuration (template) |
| `postgres-statefulset.yaml` | PostgreSQL StatefulSet |
| `redis-statefulset.yaml` | Redis StatefulSet |

## Appendix D: Production Readiness Checklist

### Pre-Production

- [ ] All environment variables configured
- [ ] At least one AI provider API key set
- [ ] PostgreSQL connection verified
- [ ] Redis connection verified (if applicable)
- [ ] JWT secret is 32+ random characters
- [ ] Encryption key generated (if using encryption)

### Security

- [ ] TLS/HTTPS enabled
- [ ] CORS origins restricted (no wildcards)
- [ ] Rate limiting configured
- [ ] API authentication enabled
- [ ] Firewall rules applied
- [ ] Container runs as non-root

### Infrastructure

- [ ] Health checks configured
- [ ] Resource limits set
- [ ] Persistent volumes created
- [ ] Backup automation configured
- [ ] DNS configured correctly

### Monitoring

- [ ] Prometheus scraping enabled
- [ ] Grafana dashboards imported
- [ ] Alert rules configured
- [ ] Log aggregation enabled
- [ ] Error tracking configured

### High Availability (Production)

- [ ] Minimum 2 replicas running
- [ ] HPA configured and active
- [ ] PDB prevents total outage
- [ ] Pods spread across zones
- [ ] Database replication enabled
- [ ] Load tested with expected traffic

---

## Related Documentation

- [ENVIRONMENT.md](../reference/ENVIRONMENT.md) - Complete environment variable reference
- [API_REFERENCE.md](../api/API_REFERENCE.md) - REST API documentation
- [TLS.md](../deployment/TLS.md) - Detailed TLS configuration
- [KUBERNETES.md](../deployment/KUBERNETES.md) - Kubernetes-specific details
- [RUNBOOK.md](../deployment/RUNBOOK.md) - Operational procedures
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Extended troubleshooting

---

*Version: 2.10.0 | Updated: 2026-09-04*
