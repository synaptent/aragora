# Reverse Proxy Setup

Aragora runs on two ports:
- **HTTP API** on port `8080` (REST endpoints, health checks)
- **WebSocket** on port `8765` (real-time debate streaming)

A reverse proxy handles SSL termination and routes traffic to both.

## Nginx

```nginx
upstream aragora_api {
    server 127.0.0.1:8080;
}

upstream aragora_ws {
    server 127.0.0.1:8765;
}

server {
    listen 443 ssl http2;
    server_name aragora.yourdomain.com;

    ssl_certificate     /etc/ssl/certs/aragora.pem;
    ssl_certificate_key /etc/ssl/private/aragora.key;

    # API routes
    location / {
        proxy_pass http://aragora_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket routes
    location /ws/ {
        proxy_pass http://aragora_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket timeouts (debates can last several minutes)
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Health check (no SSL required internally)
    location /healthz {
        proxy_pass http://aragora_api/healthz;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name aragora.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

## Caddy

```
aragora.yourdomain.com {
    # API
    reverse_proxy /ws/* 127.0.0.1:8765
    reverse_proxy * 127.0.0.1:8080
}
```

Caddy handles SSL automatically via Let's Encrypt. WebSocket upgrade is automatic.

## Traefik (Docker Labels)

```yaml
# In docker-compose.yml
services:
  aragora:
    labels:
      - "traefik.enable=true"
      # API router
      - "traefik.http.routers.aragora-api.rule=Host(`aragora.yourdomain.com`)"
      - "traefik.http.routers.aragora-api.tls.certresolver=letsencrypt"
      - "traefik.http.services.aragora-api.loadbalancer.server.port=8080"
      # WebSocket router
      - "traefik.http.routers.aragora-ws.rule=Host(`aragora.yourdomain.com`) && PathPrefix(`/ws`)"
      - "traefik.http.routers.aragora-ws.tls.certresolver=letsencrypt"
      - "traefik.http.services.aragora-ws.loadbalancer.server.port=8765"
```

## AWS ALB

Use two target groups:

| Target Group | Port | Protocol | Health Check |
|-------------|------|----------|--------------|
| aragora-api | 8080 | HTTP | `/healthz` |
| aragora-ws  | 8765 | HTTP | `/` |

Listener rules:
- Path `/ws/*` -> `aragora-ws` target group (enable stickiness)
- Default -> `aragora-api` target group

Enable WebSocket support in the ALB (enabled by default for Application Load Balancers).

## Environment Variables

Set these when running behind a reverse proxy:

```bash
# Trust proxy headers (required for correct client IP logging)
ARAGORA_TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

# Set actual domain for CORS
ARAGORA_ALLOWED_ORIGINS=https://aragora.yourdomain.com
```
