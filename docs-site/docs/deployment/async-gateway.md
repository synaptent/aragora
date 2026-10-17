---
title: Async Gateway Deployment
description: Async Gateway Deployment
---

# Async Gateway Deployment

This document describes deploying Aragora behind an async gateway for production workloads.

## Background

The built-in `ThreadingHTTPServer` is suitable for development but has limitations under load:
- Fixed thread pool can be exhausted by long-running requests
- No HTTP/2 support
- Limited connection handling capabilities

For production, deploy Aragora behind an async gateway or use ASGI workers.

## Recommended Architectures

### 1. Nginx + Gunicorn (Recommended)

Best for high-throughput production deployments.

```nginx
# /etc/nginx/conf.d/aragora.conf

upstream aragora_api {
    server 127.0.0.1:8080;
    keepalive 32;
}

upstream aragora_ws {
    server 127.0.0.1:8766;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api.aragora.ai;

    ssl_certificate /etc/ssl/certs/aragora.crt;
    ssl_certificate_key /etc/ssl/private/aragora.key;

    # API endpoints
    location /api/ {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts for long-running operations
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    # WebSocket endpoints
    location /ws {
        proxy_pass http://aragora_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # WebSocket timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
    }

    # Health checks (no auth required)
    location /health {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
    }
}
```

**Gunicorn configuration:**

```python
# gunicorn.conf.py

import multiprocessing

# Bind
bind = "127.0.0.1:8080"

# Workers
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"  # or "gevent" for async
worker_connections = 1000

# Timeouts
timeout = 300  # 5 minutes for long debates
graceful_timeout = 30
keepalive = 5

# Limits
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "aragora"

# Preload for faster worker spawning
preload_app = True
```

**Start command:**

```bash
gunicorn "aragora.server.wsgi:application" \
    --config gunicorn.conf.py \
    --workers 4 \
    --timeout 300
```

### 2. Uvicorn (ASGI)

For ASGI-based deployments with HTTP/2 support.

```bash
# Direct uvicorn
uvicorn aragora.server.asgi:application \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 4 \
    --limit-concurrency 1000 \
    --timeout-keep-alive 5

# With Gunicorn manager
gunicorn aragora.server.asgi:application \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 4 \
    --bind 0.0.0.0:8080 \
    --timeout 300
```

### 3. Kubernetes Ingress

For Kubernetes deployments, use an Ingress controller with WebSocket support.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aragora
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    # WebSocket support
    nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
    nginx.ingress.kubernetes.io/upstream-hash-by: "$remote_addr"
    # Connection pooling
    nginx.ingress.kubernetes.io/upstream-keepalive-connections: "32"
spec:
  tls:
    - hosts:
        - api.aragora.ai
      secretName: aragora-tls
  rules:
    - host: api.aragora.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: aragora
                port:
                  number: 8080
```

## Docker Compose Production Setup

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/ssl:ro
    depends_on:
      - aragora

  aragora:
    image: aragora/aragora:latest
    command: >
      gunicorn aragora.server.wsgi:application
        --bind 0.0.0.0:8080
        --workers 4
        --timeout 300
        --access-logfile -
    environment:
      - ARAGORA_ENV=production
      - DATABASE_URL=postgresql://...
      - ARAGORA_REDIS_URL=redis://redis:6379/0
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 512M

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

## Performance Tuning

### Worker Count

- **CPU-bound workloads:** `workers = CPU_COUNT`
- **I/O-bound workloads:** `workers = CPU_COUNT * 2 + 1`
- **Mixed workloads:** `workers = CPU_COUNT * 2`

### Timeouts

| Setting | Development | Production |
|---------|-------------|------------|
| Request timeout | 120s | 300s |
| WebSocket timeout | 600s | 3600s |
| Keep-alive | 5s | 5s |
| Graceful shutdown | 10s | 30s |

### Connection Limits

```bash
# System limits (add to /etc/security/limits.conf)
aragora soft nofile 65535
aragora hard nofile 65535

# Or in Docker
docker run --ulimit nofile=65535:65535 ...
```

## Health Checks

Configure load balancer health checks:

```yaml
# Kubernetes
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

## Monitoring

### Prometheus Metrics

Expose metrics endpoint for Prometheus scraping:

```yaml
# ServiceMonitor for prometheus-operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: aragora
spec:
  selector:
    matchLabels:
      app: aragora
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
```

### Key Metrics

| Metric | Alert Threshold |
|--------|-----------------|
| Request rate | > 1000/s (scale up) |
| Error rate | > 1% (investigate) |
| p99 latency | > 5s (optimize) |
| Active connections | > 800 (scale up) |
| Worker utilization | > 80% (add workers) |

## Graceful Shutdown

Ensure graceful shutdown for zero-downtime deployments:

```bash
# Graceful restart
kill -HUP $(cat /var/run/aragora.pid)

# Graceful stop
kill -TERM $(cat /var/run/aragora.pid)
```

## Security Considerations

1. **Never expose ThreadingHTTPServer directly to the internet**
2. **Always terminate TLS at the gateway (nginx/ingress)**
3. **Use private networks between gateway and application**
4. **Rate limit at the gateway level**
5. **Enable request logging for audit**

## Related Documentation

- [SCALING.md](./scaling) - Horizontal scaling guidelines
- [CONTAINER_VOLUMES.md](./container-volumes) - Volume requirements
- [DISASTER_RECOVERY.md](./disaster-recovery) - Recovery procedures
