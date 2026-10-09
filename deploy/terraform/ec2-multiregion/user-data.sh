#!/bin/bash
# =============================================================================
# Amazon Linux 2023 Bootstrap Script for Aragora
# This script runs at instance launch via EC2 user data
#
# Template variables (filled by Terraform):
#   - environment: ${environment}
#   - role: ${role}
#   - region: ${region}
# =============================================================================

set -ex

# Log all output
exec > >(tee /var/log/user-data.log) 2>&1

echo "=== Starting Aragora bootstrap at $(date) ==="
echo "Environment: ${environment}"
echo "Role: ${role}"
echo "Region: ${region}"

# =============================================================================
# System Updates
# =============================================================================

echo "=== Updating system packages ==="
dnf update -y

# =============================================================================
# Core System Packages
# =============================================================================

echo "=== Installing core packages ==="
dnf install -y \
    python3.11 \
    python3.11-devel \
    python3.11-pip \
    gcc \
    gcc-c++ \
    make \
    cmake \
    git \
    curl \
    wget \
    nginx \
    jq \
    htop \
    unzip \
    tar \
    gzip

# =============================================================================
# Database and Cache Client Libraries
# =============================================================================

echo "=== Installing database libraries ==="
dnf install -y \
    libpq-devel \
    postgresql15 \
    openssl-devel

# =============================================================================
# Optional Feature Dependencies
# =============================================================================

echo "=== Installing optional dependencies ==="

# Audio/Video processing (for TTS broadcast feature)
dnf install -y ffmpeg --allowerasing || echo "ffmpeg not available, skipping"

# Image processing (for document features)
dnf install -y \
    libjpeg-devel \
    libpng-devel || echo "Image libraries not available, skipping"

# XML processing (for document features)
dnf install -y \
    libxml2-devel \
    libxslt-devel || echo "XML libraries not available, skipping"

# =============================================================================
# Application User and Directories
# =============================================================================

echo "=== Creating application user and directories ==="
useradd -r -s /sbin/nologin aragora || echo "User aragora already exists"

mkdir -p /opt/aragora
mkdir -p /var/log/aragora
mkdir -p /etc/aragora
mkdir -p /opt/aragora/backups

# =============================================================================
# Python Environment
# =============================================================================

echo "=== Setting up Python virtual environment ==="
python3.11 -m venv /opt/aragora/venv
source /opt/aragora/venv/bin/activate

# Upgrade pip and install build tools
pip install --upgrade pip wheel setuptools

# =============================================================================
# Install Aragora
# =============================================================================

echo "=== Installing Aragora ==="
pip install "aragora"

# Set ownership
chown -R aragora:aragora /opt/aragora /var/log/aragora /etc/aragora

# =============================================================================
# Nginx Configuration
# =============================================================================

echo "=== Configuring nginx ==="
cat > /etc/nginx/conf.d/aragora.conf << 'NGINX_CONFIG'
# Aragora API Server Configuration
# Reverse proxy for API and WebSocket endpoints

upstream aragora_api {
    server 127.0.0.1:8080;
    keepalive 32;
}

upstream aragora_ws {
    server 127.0.0.1:8765;
    keepalive 32;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Health check endpoint (no rate limit for Cloudflare checks)
    location /api/health {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
    }

    # WebSocket endpoint
    location /ws {
        proxy_pass http://aragora_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # API endpoints
    location / {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;

        # Increase buffer sizes for large responses
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }

    # Deny access to hidden files
    location ~ /\. {
        deny all;
    }
}
NGINX_CONFIG

# Remove default nginx config
rm -f /etc/nginx/conf.d/default.conf || true

# Test nginx config
nginx -t

# Enable and start nginx
systemctl enable nginx
systemctl start nginx

# =============================================================================
# Systemd Services
# =============================================================================

echo "=== Creating systemd services ==="

# Main API Server
cat > /etc/systemd/system/aragora.service << 'SERVICE_CONFIG'
[Unit]
Description=Aragora Unified API + WebSocket Server
Documentation=https://github.com/aragora/aragora
After=network.target
Wants=network.target

[Service]
Type=simple
User=aragora
Group=aragora
WorkingDirectory=/opt/aragora
Environment="PATH=/opt/aragora/venv/bin"
EnvironmentFile=-/etc/aragora/env
ExecStart=/opt/aragora/venv/bin/aragora serve --api-port 8080 --ws-port 8765 --host 127.0.0.1
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/log/aragora /opt/aragora
PrivateTmp=yes

# Resource limits
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
SERVICE_CONFIG

# Reload systemd
systemctl daemon-reload

# =============================================================================
# CloudWatch Agent
# =============================================================================

echo "=== Installing CloudWatch agent ==="
dnf install -y amazon-cloudwatch-agent || echo "CloudWatch agent not available"

# Create CloudWatch agent config
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'CW_CONFIG'
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/aragora/*.log",
            "log_group_name": "aragora-${environment}",
            "log_stream_name": "{instance_id}/aragora",
            "retention_in_days": 30
          },
          {
            "file_path": "/var/log/nginx/access.log",
            "log_group_name": "aragora-${environment}",
            "log_stream_name": "{instance_id}/nginx-access",
            "retention_in_days": 14
          },
          {
            "file_path": "/var/log/nginx/error.log",
            "log_group_name": "aragora-${environment}",
            "log_stream_name": "{instance_id}/nginx-error",
            "retention_in_days": 14
          }
        ]
      }
    }
  },
  "metrics": {
    "namespace": "Aragora/${environment}",
    "metrics_collected": {
      "cpu": {
        "measurement": ["cpu_usage_idle", "cpu_usage_user", "cpu_usage_system"],
        "metrics_collection_interval": 60
      },
      "mem": {
        "measurement": ["mem_used_percent"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["disk_used_percent"],
        "resources": ["/"],
        "metrics_collection_interval": 60
      }
    }
  }
}
CW_CONFIG

# Start CloudWatch agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json || echo "CloudWatch agent config failed"

# =============================================================================
# Environment File Template
# =============================================================================

echo "=== Creating environment file template ==="
cat > /etc/aragora/env.template << 'ENV_TEMPLATE'
# Aragora Environment Configuration
# Copy to /etc/aragora/env and fill in values

# Required: Database connection
DATABASE_URL=postgresql://user:password@host:5432/aragora

# Required: Redis connection
ARAGORA_REDIS_URL=redis://host:6379

# Required: API keys (at least one)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Optional: Additional providers
OPENROUTER_API_KEY=
MISTRAL_API_KEY=
GEMINI_API_KEY=

# Optional: Monitoring
SENTRY_DSN=
PROMETHEUS_ENABLED=true

# Instance metadata
ARAGORA_INSTANCE_ROLE=${role}
ARAGORA_REGION=${region}
ARAGORA_ENVIRONMENT=${environment}
ENV_TEMPLATE

# Create empty env file if doesn't exist
touch /etc/aragora/env
chown aragora:aragora /etc/aragora/env
chmod 600 /etc/aragora/env

# =============================================================================
# Final Setup
# =============================================================================

echo "=== Setting final permissions ==="
chown -R aragora:aragora /opt/aragora /var/log/aragora /etc/aragora

# Log completion
echo "=== Bootstrap complete at $(date) ==="
echo "Instance Role: ${role}"
echo "Region: ${region}"
echo "Environment: ${environment}"
echo ""
echo "Next steps:"
echo "1. Populate /etc/aragora/env with secrets"
echo "2. Start service: systemctl start aragora"
echo "3. Verify health: curl http://localhost/api/health"
