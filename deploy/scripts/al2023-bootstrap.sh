#!/bin/bash
# =============================================================================
# Amazon Linux 2023 Bootstrap Script for Aragora
# Standalone version for manual execution on EC2 instances
#
# Usage:
#   curl -O https://raw.githubusercontent.com/aragora/aragora/main/deploy/scripts/al2023-bootstrap.sh
#   chmod +x al2023-bootstrap.sh
#   sudo ./al2023-bootstrap.sh [environment] [role] [region]
#
# Arguments:
#   environment: production, staging, development (default: production)
#   role: primary, secondary, dr (default: primary)
#   region: us-east-2, eu-west-1, ap-south-1 (default: us-east-2)
# =============================================================================

set -ex

# Parse arguments
ENVIRONMENT="${1:-production}"
ROLE="${2:-primary}"
REGION="${3:-us-east-2}"

# Log all output
LOG_FILE="/var/log/aragora-bootstrap-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "=============================================="
echo "Aragora Amazon Linux 2023 Bootstrap Script"
echo "=============================================="
echo "Started at: $(date)"
echo "Environment: $ENVIRONMENT"
echo "Role: $ROLE"
echo "Region: $REGION"
echo "Log file: $LOG_FILE"
echo "=============================================="

# Check for root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Check for Amazon Linux 2023
if ! grep -q "Amazon Linux 2023" /etc/os-release 2>/dev/null; then
    echo "WARNING: This script is designed for Amazon Linux 2023"
    echo "Current OS: $(cat /etc/os-release | grep PRETTY_NAME)"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# =============================================================================
# System Updates
# =============================================================================

echo ""
echo "=== Phase 1: System Updates ==="
dnf update -y

# =============================================================================
# Core System Packages
# =============================================================================

echo ""
echo "=== Phase 2: Core Packages ==="
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
    gzip \
    libpq-devel \
    postgresql15 \
    openssl-devel

# =============================================================================
# Optional Dependencies (may not be available in all regions)
# =============================================================================

echo ""
echo "=== Phase 3: Optional Dependencies ==="

# Audio/Video (TTS feature)
if dnf install -y ffmpeg --allowerasing 2>/dev/null; then
    echo "ffmpeg installed successfully"
else
    echo "ffmpeg not available - TTS broadcast feature may be limited"
fi

# Image processing
dnf install -y libjpeg-devel libpng-devel 2>/dev/null || echo "Image libraries skipped"

# XML processing
dnf install -y libxml2-devel libxslt-devel 2>/dev/null || echo "XML libraries skipped"

# =============================================================================
# Application Setup
# =============================================================================

echo ""
echo "=== Phase 4: Application Setup ==="

# Create user
if ! id aragora &>/dev/null; then
    useradd -r -s /sbin/nologin aragora
    echo "Created user: aragora"
else
    echo "User aragora already exists"
fi

# Create directories
mkdir -p /opt/aragora
mkdir -p /var/log/aragora
mkdir -p /etc/aragora
mkdir -p /opt/aragora/backups

# =============================================================================
# Python Environment
# =============================================================================

echo ""
echo "=== Phase 5: Python Environment ==="

python3.11 -m venv /opt/aragora/venv
source /opt/aragora/venv/bin/activate

pip install --upgrade pip wheel setuptools

echo "Installing Aragora..."
pip install "aragora"

# Verify installation
echo ""
echo "Installed packages:"
pip list | grep -E "^(aragora|fastapi|uvicorn|aiohttp|pydantic)"

chown -R aragora:aragora /opt/aragora /var/log/aragora /etc/aragora

# =============================================================================
# Nginx Configuration
# =============================================================================

echo ""
echo "=== Phase 6: Nginx Configuration ==="

cat > /etc/nginx/conf.d/aragora.conf << 'NGINX'
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

    location /api/health {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://aragora_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }

    location / {
        proxy_pass http://aragora_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
    }

    location ~ /\. { deny all; }
}
NGINX

rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
nginx -t
systemctl enable nginx
systemctl start nginx

# =============================================================================
# Systemd Services
# =============================================================================

echo ""
echo "=== Phase 7: Systemd Services ==="

cat > /etc/systemd/system/aragora.service << SERVICE
[Unit]
Description=Aragora Unified API + WebSocket Server
After=network.target

[Service]
Type=simple
User=aragora
Group=aragora
WorkingDirectory=/opt/aragora
Environment="PATH=/opt/aragora/venv/bin"
EnvironmentFile=-/etc/aragora/env
ExecStart=/opt/aragora/venv/bin/aragora serve --api-port 8080 --ws-port 8765 --host 127.0.0.1
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/log/aragora /opt/aragora
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload

# =============================================================================
# CloudWatch Agent
# =============================================================================

echo ""
echo "=== Phase 8: CloudWatch Agent ==="

if dnf install -y amazon-cloudwatch-agent 2>/dev/null; then
    echo "CloudWatch agent installed"
else
    echo "CloudWatch agent not available"
fi

# =============================================================================
# Environment Template
# =============================================================================

echo ""
echo "=== Phase 9: Environment Configuration ==="

cat > /etc/aragora/env.template << ENVTEMPLATE
# Aragora Environment Configuration
# Copy this file to /etc/aragora/env and fill in values

# Database (required)
DATABASE_URL=postgresql://user:password@host:5432/aragora

# Redis (required)
ARAGORA_REDIS_URL=redis://host:6379

# API Keys (at least one required)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Optional providers
OPENROUTER_API_KEY=
MISTRAL_API_KEY=

# Monitoring
SENTRY_DSN=
PROMETHEUS_ENABLED=true

# Instance metadata
ARAGORA_INSTANCE_ROLE=$ROLE
ARAGORA_REGION=$REGION
ARAGORA_ENVIRONMENT=$ENVIRONMENT
ENVTEMPLATE

touch /etc/aragora/env
chown aragora:aragora /etc/aragora/env
chmod 600 /etc/aragora/env

# =============================================================================
# Completion
# =============================================================================

echo ""
echo "=============================================="
echo "Bootstrap Complete!"
echo "=============================================="
echo "Completed at: $(date)"
echo ""
echo "System Information:"
echo "  OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
echo "  Python: $(python3.11 --version)"
echo "  nginx: $(nginx -v 2>&1)"
echo ""
echo "Aragora Installation:"
source /opt/aragora/venv/bin/activate
echo "  Version: $(pip show aragora 2>/dev/null | grep Version || echo 'installed')"
echo "  Location: /opt/aragora/venv"
echo ""
echo "Next Steps:"
echo "  1. Configure secrets:"
echo "     sudo nano /etc/aragora/env"
echo ""
echo "  2. Start services:"
echo "     sudo systemctl start aragora"
echo ""
echo "  3. Enable services on boot:"
echo "     sudo systemctl enable aragora"
echo ""
echo "  4. Verify health:"
echo "     curl http://localhost/api/health"
echo ""
echo "Log file: $LOG_FILE"
echo "=============================================="
