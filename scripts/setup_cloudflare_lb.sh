#!/bin/bash
# Cloudflare Load Balancer Setup Script for Aragora
#
# Prerequisites:
# - CLOUDFLARE_API_TOKEN with Load Balancer permissions
# - CLOUDFLARE_ZONE_ID for aragora.ai
# - Cloudflare Pro/Business/Enterprise plan (Load Balancing is a premium feature)
#
# Usage:
#   export CLOUDFLARE_API_TOKEN="your_token"
#   export CLOUDFLARE_ZONE_ID="your_zone_id"
#   ./setup_cloudflare_lb.sh

set -e

# Configuration
POOL_NAME="aragora-api-pool"
LB_NAME="aragora-api-lb"
MONITOR_NAME="aragora-health-check"
API_BASE="https://api.cloudflare.com/client/v4"

# Origin servers
ORIGIN_1_IP="3.141.170.60"      # aragora-api-server-al2023 (i-0823e60c7c4b924e1)
ORIGIN_2_IP="3.143.224.156"    # aragora-api-2-al2023 (i-07e538fafbe61696d)

# Verify credentials
if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
    echo "Error: CLOUDFLARE_API_TOKEN not set"
    exit 1
fi

if [ -z "$CLOUDFLARE_ZONE_ID" ]; then
    echo "Error: CLOUDFLARE_ZONE_ID not set"
    echo "Get your zone ID from Cloudflare dashboard > aragora.ai > Overview (right side)"
    exit 1
fi

CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"

# Get account ID if not provided
if [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
    echo "Fetching account ID..."
    CLOUDFLARE_ACCOUNT_ID=$(curl -s -X GET "$API_BASE/zones/$CLOUDFLARE_ZONE_ID" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json" | jq -r '.result.account.id')
    echo "Account ID: $CLOUDFLARE_ACCOUNT_ID"
fi

echo "=== Cloudflare Load Balancer Setup ==="
echo "Zone ID: $CLOUDFLARE_ZONE_ID"
echo "Account ID: $CLOUDFLARE_ACCOUNT_ID"
echo "Origins: $ORIGIN_1_IP, $ORIGIN_2_IP"
echo ""

# Step 1: Create Health Monitor
echo "Step 1: Creating health monitor..."
MONITOR_RESPONSE=$(curl -s -X POST "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/load_balancers/monitors" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "type": "http",
        "description": "'"$MONITOR_NAME"'",
        "method": "GET",
        "path": "/api/health",
        "port": 80,
        "timeout": 5,
        "retries": 2,
        "interval": 60,
        "expected_codes": "200",
        "follow_redirects": true,
        "allow_insecure": false,
        "header": {
            "Host": ["api.aragora.ai"]
        }
    }')

MONITOR_ID=$(echo "$MONITOR_RESPONSE" | jq -r '.result.id // empty')
if [ -z "$MONITOR_ID" ]; then
    echo "Error creating monitor:"
    echo "$MONITOR_RESPONSE" | jq .
    # Check if monitor already exists
    EXISTING_MONITOR=$(curl -s -X GET "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/load_balancers/monitors" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq -r '.result[] | select(.description=="'"$MONITOR_NAME"'") | .id')
    if [ -n "$EXISTING_MONITOR" ]; then
        echo "Using existing monitor: $EXISTING_MONITOR"
        MONITOR_ID="$EXISTING_MONITOR"
    else
        exit 1
    fi
fi
echo "Monitor ID: $MONITOR_ID"

# Step 2: Create Origin Pool
echo ""
echo "Step 2: Creating origin pool..."
POOL_RESPONSE=$(curl -s -X POST "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/load_balancers/pools" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "'"$POOL_NAME"'",
        "description": "Aragora API servers",
        "enabled": true,
        "minimum_origins": 1,
        "monitor": "'"$MONITOR_ID"'",
        "notification_email": "anomium@gmail.com",
        "origins": [
            {
                "name": "aragora-api-server",
                "address": "'"$ORIGIN_1_IP"'",
                "enabled": true,
                "weight": 1,
                "header": {
                    "Host": ["api.aragora.ai"]
                }
            },
            {
                "name": "aragora-api-2",
                "address": "'"$ORIGIN_2_IP"'",
                "enabled": true,
                "weight": 1,
                "header": {
                    "Host": ["api.aragora.ai"]
                }
            }
        ],
        "origin_steering": {
            "policy": "random"
        }
    }')

POOL_ID=$(echo "$POOL_RESPONSE" | jq -r '.result.id // empty')
if [ -z "$POOL_ID" ]; then
    echo "Error creating pool:"
    echo "$POOL_RESPONSE" | jq .
    # Check if pool already exists
    EXISTING_POOL=$(curl -s -X GET "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/load_balancers/pools" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq -r '.result[] | select(.name=="'"$POOL_NAME"'") | .id')
    if [ -n "$EXISTING_POOL" ]; then
        echo "Using existing pool: $EXISTING_POOL"
        POOL_ID="$EXISTING_POOL"
    else
        exit 1
    fi
fi
echo "Pool ID: $POOL_ID"

# Step 3: Create Load Balancer
echo ""
echo "Step 3: Creating load balancer for api.aragora.ai..."
LB_RESPONSE=$(curl -s -X POST "$API_BASE/zones/$CLOUDFLARE_ZONE_ID/load_balancers" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "api.aragora.ai",
        "description": "'"$LB_NAME"'",
        "ttl": 30,
        "proxied": true,
        "enabled": true,
        "default_pools": ["'"$POOL_ID"'"],
        "fallback_pool": "'"$POOL_ID"'",
        "steering_policy": "random",
        "session_affinity": "ip_cookie",
        "session_affinity_ttl": 1800,
        "session_affinity_attributes": {
            "samesite": "Auto",
            "secure": "Auto"
        }
    }')

LB_ID=$(echo "$LB_RESPONSE" | jq -r '.result.id // empty')
if [ -z "$LB_ID" ]; then
    echo "Error creating load balancer:"
    echo "$LB_RESPONSE" | jq .
    # Check if LB already exists
    EXISTING_LB=$(curl -s -X GET "$API_BASE/zones/$CLOUDFLARE_ZONE_ID/load_balancers" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq -r '.result[] | select(.name=="api.aragora.ai") | .id')
    if [ -n "$EXISTING_LB" ]; then
        echo "Load balancer already exists: $EXISTING_LB"
        LB_ID="$EXISTING_LB"
    else
        exit 1
    fi
fi
echo "Load Balancer ID: $LB_ID"

# Step 4: Verify setup
echo ""
echo "Step 4: Verifying setup..."
sleep 5

# Check pool health
HEALTH=$(curl -s -X GET "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/load_balancers/pools/$POOL_ID/health" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN")
echo "Pool health:"
echo "$HEALTH" | jq '.result'

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Load Balancer Configuration:"
echo "  Name: api.aragora.ai"
echo "  Pool: $POOL_NAME ($POOL_ID)"
echo "  Monitor: $MONITOR_NAME ($MONITOR_ID)"
echo "  Origins:"
echo "    - aragora-api-server: $ORIGIN_1_IP"
echo "    - aragora-api-2: $ORIGIN_2_IP"
echo ""
echo "Traffic will now be distributed between both servers."
echo "If one server fails health checks, traffic will route to the healthy server."
echo ""
echo "Monitor in Cloudflare Dashboard:"
echo "  https://dash.cloudflare.com/$CLOUDFLARE_ACCOUNT_ID/aragora.ai/traffic/load-balancing"
