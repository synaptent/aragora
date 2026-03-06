# Aragora EC2 Fleet Operational Runbook

This runbook covers day-to-day operations, deployment procedures, incident response, and monitoring for the Aragora production EC2 fleet.

**Last updated:** 2026-02-14

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Instance Inventory](#2-instance-inventory)
3. [Deploy Procedures](#3-deploy-procedures)
4. [Health Checks](#4-health-checks)
5. [Incident Response](#5-incident-response)
6. [Monitoring](#6-monitoring)
7. [Common SSM Commands](#7-common-ssm-commands)
8. [Instance Configuration](#8-instance-configuration)
9. [Secrets Management](#9-secrets-management)
10. [Maintenance Windows](#10-maintenance-windows)

---

## 1. Architecture Overview

```
                    Internet
                       |
              +--------v--------+
              |   Cloudflare    |
              |  (LB + WAF)    |
              |  api.aragora.ai |
              |  Random steering|
              |  IP cookie aff. |
              +--------+--------+
                       |
        +--------------+--------------+
        |              |              |
   +----v----+   +----v----+   +----v----+   +----------+
   | aragora |   | aragora |   | aragora |   | aragora  |
   | api-    |   | api-2   |   | al2023-1|   | al2023-2 |
   | server  |   |         |   |         |   |          |
   | (orig)  |   | (orig)  |   | (AL2023)|   | (AL2023) |
   +---------+   +---------+   +---------+   +----------+
        |              |              |              |
        +--------------+--------------+--------------+
                       |
              +--------v--------+
              |  Supabase PG    |
              |  (txn pooler)   |
              +-----------------+
              |  Upstash Redis  |
              |  (TLS, us-east-2)|
              +-----------------+
```

**Traffic flow:**

1. Clients hit `https://api.aragora.ai` (Cloudflare-managed DNS).
2. Cloudflare terminates TLS, applies WAF rules, and forwards HTTP to EC2 origins on port 80 (nginx).
3. Cloudflare load balancer uses **random** steering with **IP cookie session affinity** (TTL 1800s) to distribute requests across the origin pool.
4. nginx on each EC2 proxies to the Aragora unified server on port 8080 (HTTP API) and port 8765 (WebSocket).
5. All instances share state via Supabase PostgreSQL (transaction pooler mode) and Upstash Redis (TLS).

**Key properties:**

| Property | Value |
|----------|-------|
| AWS Region | us-east-2 (Ohio) |
| Load Balancer | Cloudflare (origin pool: `aragora-api-pool`) |
| Steering Policy | Random (equal weight) |
| Session Affinity | IP Cookie, 30-minute TTL |
| Health Check Path | `/api/health` on port 80, 60s interval, 5s timeout |
| Minimum Origins | 1 (pool stays active if at least one origin is healthy) |
| SSL Termination | Cloudflare (auto-renewing certificates) |
| Instance Access | AWS SSM only (no SSH) |
| Secrets | AWS Secrets Manager (`aragora/production`) |

---

## 2. Instance Inventory

### Production Instances

| Name | Instance ID | AMI | Role | Notes |
|------|-------------|-----|------|-------|
| aragora-api-server-al2023 | `i-0823e60c7c4b924e1` | Amazon Linux 2023 | Staging | Replaced AL2 `i-0823e60c7c4b924e1` (stopped) |
| aragora-api-2-al2023 | `i-07e538fafbe61696d` | Amazon Linux 2023 | Production | Replaced AL2 `i-07e538fafbe61696d` (stopped) |
| aragora-al2023-1 | *(check AWS console)* | Amazon Linux 2023 | Primary (AL2023) | `/home/ec2-user/aragora` |
| aragora-al2023-2 | *(check AWS console)* | Amazon Linux 2023 | Secondary (AL2023) | `/home/ec2-user/aragora` |

**To retrieve current instance IDs dynamically:**

```bash
aws ec2 describe-instances \
  --filters \
    "Name=tag:Application,Values=aragora" \
    "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],State.Name,LaunchTime]' \
  --output table \
  --region us-east-2
```

### Convenience Variables

Set these in your shell for the runbook commands below. The original two instance IDs are known:

```bash
export ORIG_1="i-0823e60c7c4b924e1"   # aragora-api-server-al2023
export ORIG_2="i-07e538fafbe61696d"   # aragora-api-2-al2023
export REGION="us-east-2"

# Discover AL2023 IDs dynamically
export AL2023_IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:Application,Values=aragora" \
            "Name=instance-state-name,Values=running" \
            "Name=tag:Name,Values=aragora-al2023*" \
  --query 'Reservations[].Instances[].InstanceId' \
  --output text --region $REGION)

# All four instances
export ALL_IDS="$ORIG_1 $ORIG_2 $AL2023_IDS"
```

### Supporting Services

| Component | Service | Region | Details |
|-----------|---------|--------|---------|
| Database | Supabase PostgreSQL | - | Transaction pooler mode |
| Cache | Upstash Redis | us-east-2 | TLS enabled (`rediss://`) |
| CDN/WAF | Cloudflare | Global | SSL termination, LB, WAF |
| Secrets | AWS Secrets Manager | us-east-2 | `aragora/production`, `aragora/staging` |
| Monitoring | CloudWatch | us-east-2 | CPU alarms, status checks, log groups |
| CI/CD | GitHub Actions | - | `.github/workflows/deploy-secure.yml` |

---

## 3. Deploy Procedures

### 3.1 Standard Deploy via CI (GitHub Actions)

The canonical deploy path is the `deploy-secure.yml` workflow. It triggers automatically on pushes to `main` that touch `aragora/`, `deploy/`, `requirements.txt`, or `pyproject.toml`.

**Flow:**

```
Push to main
    |
    v
[test] -- Run quick tests (pytest)
    |
    v
[deploy-ec2-staging] -- Deploy to staging instances via SSM
    |                    (tagged Environment=staging)
    v
[deploy-ec2-production] -- Deploy to production instances via SSM
    |                       (tagged Environment=production)
    |                       Requires GitHub Environment approval
    v
[deploy-cloudflare] -- Deploy frontend to Cloudflare Pages
    |
    v
[notify] -- Post deployment summary
```

**What the deploy does on each instance (via SSM `AWS-RunShellScript`):**

1. `git stash --include-untracked` (save any local changes)
2. `git fetch origin main && git reset --hard origin/main`
3. `pip install -e . --quiet --no-cache-dir`
4. Validate import: `python -c "from aragora.server.unified_server import UnifiedServer"`
5. Write systemd drop-in `/etc/systemd/system/aragora.service.d/secrets.conf`
6. `systemctl daemon-reload && systemctl restart aragora`
7. Wait 5s, verify `systemctl is-active --quiet aragora`
8. Run `scripts/seed_agents.py` and `scripts/validate_production.py --quick`

**Manual dispatch:** Go to Actions > "Deploy (Secure)" > Run workflow. Choose environment: `all`, `cloudflare`, `ec2-staging`, or `ec2-production`.

**Authentication:** Uses AWS OIDC federation (no long-lived AWS credentials in GitHub). The IAM role is assumed via `sts:AssumeRoleWithWebIdentity`.

### 3.2 Hotfix Deploy via SSM (Single Instance)

For urgent fixes that cannot wait for CI, deploy directly via SSM. Deploy to one instance first, verify, then roll to the rest.

```bash
# Step 1: Deploy to one instance
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --comment "Hotfix deploy - <describe change>" \
  --parameters 'commands=[
    "set -e",
    "export HOME=/root",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "PREVIOUS_COMMIT=$(git rev-parse HEAD)",
    "echo \"PREVIOUS_COMMIT=$PREVIOUS_COMMIT\" > /tmp/aragora_deploy_state",
    "sudo -u ec2-user git stash --include-untracked || true",
    "sudo chown -R ec2-user:ec2-user /home/ec2-user/aragora/.git || true",
    "sudo -u ec2-user git fetch origin main",
    "sudo -u ec2-user git reset --hard origin/main",
    "source venv/bin/activate",
    "pip install -e . --quiet --no-cache-dir",
    "python -c \"from aragora.server.unified_server import UnifiedServer; print(\\\"Import OK\\\")\"",
    "sudo systemctl daemon-reload",
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl is-active --quiet aragora && echo DEPLOY_OK || echo DEPLOY_FAIL",
    "curl -sf http://localhost:8080/api/health | jq .status"
  ]' \
  --timeout-seconds 300 \
  --output text --query "Command.CommandId" \
  --region us-east-2

# Step 2: Get the result
aws ssm get-command-invocation \
  --command-id "<COMMAND_ID>" \
  --instance-id "i-0823e60c7c4b924e1" \
  --query '[Status,StandardOutputContent]' \
  --output text \
  --region us-east-2
```

**Step 3: If successful, deploy to remaining instances:**

```bash
aws ssm send-command \
  --instance-ids "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --comment "Hotfix deploy - rolling to instance 2" \
  --parameters 'commands=[...]' \
  --timeout-seconds 300 \
  --region us-east-2
```

Repeat for each AL2023 instance. Adjust the working directory if the AL2023 instances use `/opt/aragora` instead of `/home/ec2-user/aragora`.

### 3.3 Deploy to All Instances Simultaneously

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --comment "Fleet deploy to all instances" \
  --parameters 'commands=[
    "set -e",
    "export HOME=/root",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "PREVIOUS_COMMIT=$(git rev-parse HEAD)",
    "echo \"PREVIOUS_COMMIT=$PREVIOUS_COMMIT\" > /tmp/aragora_deploy_state",
    "sudo -u ec2-user git stash --include-untracked || true",
    "sudo chown -R ec2-user:ec2-user /home/ec2-user/aragora/.git || true",
    "sudo -u ec2-user git fetch origin main",
    "sudo -u ec2-user git reset --hard origin/main",
    "source venv/bin/activate",
    "pip install -e . --quiet --no-cache-dir",
    "sudo systemctl daemon-reload",
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl is-active --quiet aragora && echo DEPLOY_OK || echo DEPLOY_FAIL"
  ]' \
  --timeout-seconds 300 \
  --region us-east-2
```

Add the AL2023 instance IDs to the `--instance-ids` list as needed.

### 3.4 Rollback Procedure

The deploy script writes the previous commit hash to `/tmp/aragora_deploy_state` on each instance. To rollback:

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --comment "Rollback aragora to previous commit" \
  --parameters 'commands=[
    "set -e",
    "export HOME=/root",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "if [ -f /tmp/aragora_deploy_state ]; then source /tmp/aragora_deploy_state; fi",
    "if [ -z \"$PREVIOUS_COMMIT\" ]; then echo \"No rollback point found\"; exit 1; fi",
    "echo \"Rolling back to $PREVIOUS_COMMIT\"",
    "sudo -u ec2-user git checkout $PREVIOUS_COMMIT",
    "source venv/bin/activate",
    "pip install -e . --quiet --no-cache-dir",
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl is-active --quiet aragora && echo ROLLBACK_OK || echo ROLLBACK_FAIL",
    "rm -f /tmp/aragora_deploy_state",
    "echo \"Rolled back to: $(git rev-parse HEAD)\""
  ]' \
  --timeout-seconds 120 \
  --region us-east-2
```

**If `/tmp/aragora_deploy_state` is missing** (e.g., instance was rebooted), roll back to a specific commit:

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "set -e",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "sudo -u ec2-user git checkout <COMMIT_SHA>",
    "source venv/bin/activate",
    "pip install -e . --quiet --no-cache-dir",
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl is-active --quiet aragora && echo OK || echo FAIL"
  ]' \
  --timeout-seconds 120 \
  --region us-east-2
```

**CI auto-rollback:** The `deploy-secure.yml` workflow automatically triggers rollback if the deploy step fails or the post-deploy health check fails. It restores `PREVIOUS_COMMIT`, reinstalls, and restarts the service.

---

## 4. Health Checks

### 4.1 Endpoints

| Endpoint | Auth Required | Returns |
|----------|--------------|---------|
| `GET /api/health` | No (minimal) / Yes (full) | `{"status":"healthy","timestamp":"..."}` (public) or full checks, version, uptime (authenticated) |
| `GET /healthz` | No | `200 OK` liveness probe |
| `GET /readyz` | No | `200 OK` readiness probe |
| `GET /api/health/detailed` | Yes (`system.health.read`) | Detailed subsystem checks |
| `GET /api/health/deep` | Yes | Deep health including slow checks |
| `GET /api/health/stores` | Yes | Database store health |
| `GET /api/health/database` | Yes | Schema and migration health |
| `GET /api/openapi.json` | No | OpenAPI spec (validates server is serving routes) |
| `GET /api/auth/status` | No | Auth system status |

### 4.2 External Health Check (via Cloudflare)

```bash
# Quick check -- returns status from whichever instance Cloudflare routes to
curl -s https://api.aragora.ai/api/health | jq .

# Full check -- returns healthy/degraded from OpenAPI validation
curl -sf https://api.aragora.ai/api/openapi.json | jq '.info.title, .info.version'

# Auth status
curl -s https://api.aragora.ai/api/auth/status | jq .
```

### 4.3 Per-Instance Health Check (via SSM)

Check health on a specific instance by running curl locally via SSM:

```bash
# Single instance
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -s http://localhost:8080/api/health | jq"]' \
  --output text --query "Command.CommandId" \
  --region us-east-2

# Retrieve output
aws ssm get-command-invocation \
  --command-id "<COMMAND_ID>" \
  --instance-id "i-0823e60c7c4b924e1" \
  --query 'StandardOutputContent' \
  --output text \
  --region us-east-2
```

### 4.4 Verify All Instances Are on the Same Version

Run the version check across all instances and compare the git SHA:

```bash
# Check deployed git commit on all instances
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --comment "Version check across fleet" \
  --parameters 'commands=[
    "HOSTNAME=$(hostname)",
    "cd /home/ec2-user/aragora 2>/dev/null || cd /opt/aragora",
    "git config --global --add safe.directory $(pwd)",
    "COMMIT=$(git rev-parse --short HEAD)",
    "BRANCH=$(git branch --show-current 2>/dev/null || echo detached)",
    "echo \"$HOSTNAME: commit=$COMMIT branch=$BRANCH\"",
    "source venv/bin/activate 2>/dev/null",
    "python -c \"from aragora import __version__; print(f\\\"package_version={__version__}\\\")\" 2>/dev/null || echo \"package_version=unknown\""
  ]' \
  --timeout-seconds 30 \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

Add AL2023 instance IDs to the `--instance-ids` list. Then retrieve output per instance:

```bash
# Check each instance's output
for INSTANCE in i-0823e60c7c4b924e1 i-07e538fafbe61696d; do
  echo "=== $INSTANCE ==="
  aws ssm get-command-invocation \
    --command-id "<COMMAND_ID>" \
    --instance-id "$INSTANCE" \
    --query 'StandardOutputContent' \
    --output text \
    --region us-east-2
done
```

**Version drift** exists when instances report different commit SHAs. See [Section 5.2](#52-version-drift) for remediation.

### 4.5 SSL Certificate Check

Certificates are managed by Cloudflare with auto-renewal.

```bash
echo | openssl s_client -servername api.aragora.ai -connect api.aragora.ai:443 2>/dev/null \
  | openssl x509 -noout -dates -subject
```

---

## 5. Incident Response

### 5.1 Instance Not Responding

**Symptoms:** Cloudflare returns 521/522/523 errors, health check failures in Cloudflare dashboard.

**Diagnosis steps:**

```bash
# 1. Check instance state in AWS
aws ec2 describe-instance-status \
  --instance-ids "i-0823e60c7c4b924e1" \
  --query 'InstanceStatuses[*].[InstanceId,InstanceState.Name,SystemStatus.Status,InstanceStatus.Status]' \
  --output table \
  --region us-east-2

# 2. Check SSM agent connectivity
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=i-0823e60c7c4b924e1" \
  --query 'InstanceInformationList[*].[InstanceId,PingStatus,LastPingDateTime,PlatformName]' \
  --output table \
  --region us-east-2

# 3. If SSM is reachable, check the service
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "systemctl status aragora --no-pager",
    "echo ---",
    "systemctl status nginx --no-pager",
    "echo ---",
    "curl -sf http://localhost:8080/api/health || echo HEALTH_FAIL",
    "echo ---",
    "free -m",
    "echo ---",
    "df -h /",
    "echo ---",
    "uptime"
  ]' \
  --timeout-seconds 30 \
  --region us-east-2

# 4. Check recent service logs for crash reasons
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -n 50 --no-pager"]' \
  --timeout-seconds 30 \
  --region us-east-2

# 5. Check if the process is actually running and listening
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "ss -tlnp | grep -E \"8080|8765|80\"",
    "echo ---",
    "ps aux | grep aragora | grep -v grep"
  ]' \
  --timeout-seconds 30 \
  --region us-east-2
```

**If SSM is unreachable:**

- The instance may be stopped, terminated, or the SSM agent crashed.
- Check EC2 console for instance state.
- If the instance is running but SSM is down, you may need to reboot via EC2 console.
- Cloudflare will automatically route traffic away from the unhealthy instance.

**Resolution checklist:**

1. If `aragora` service is stopped/failed: restart it (see [Section 5.3](#53-service-crash)).
2. If nginx is down: `sudo systemctl restart nginx`.
3. If disk is full: clear old logs with `sudo journalctl --vacuum-size=500M`.
4. If OOM: check `dmesg | grep -i oom` and consider instance type upgrade.

### 5.2 Version Drift

**Symptoms:** Different instances return different behavior, some instances have bugs already fixed.

**Detection:**

```bash
# Run the version check from Section 4.4 and compare commit SHAs
# Or check via Cloudflare by hitting the API multiple times:
for i in {1..10}; do
  curl -s https://api.aragora.ai/api/health | jq -r '.version // .status'
done
```

**Remediation:**

Deploy the correct version to the drifted instance(s):

```bash
# Identify which instance is behind
# Then deploy to that specific instance:
aws ssm send-command \
  --instance-ids "<DRIFTED_INSTANCE_ID>" \
  --document-name "AWS-RunShellScript" \
  --comment "Fix version drift" \
  --parameters 'commands=[
    "set -e",
    "export HOME=/root",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "sudo -u ec2-user git fetch origin main",
    "sudo -u ec2-user git reset --hard origin/main",
    "source venv/bin/activate",
    "pip install -e . --quiet --no-cache-dir",
    "sudo systemctl restart aragora",
    "sleep 5",
    "echo COMMIT: $(git rev-parse --short HEAD)",
    "curl -sf http://localhost:8080/api/health | jq .status"
  ]' \
  --timeout-seconds 300 \
  --region us-east-2
```

Or re-run the CI deploy to all instances: Go to Actions > "Deploy (Secure)" > Run workflow > `ec2-production`.

### 5.3 Service Crash

**Symptoms:** `systemctl status aragora` shows `failed` or `inactive`.

**Quick restart:**

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl is-active --quiet aragora && echo SERVICE_OK || echo SERVICE_FAIL",
    "systemctl status aragora --no-pager | head -20"
  ]' \
  --timeout-seconds 60 \
  --region us-east-2
```

**If the service keeps crashing (crash loop):**

The systemd unit has `StartLimitBurst=5` within `StartLimitIntervalSec=300`, meaning 5 failures in 5 minutes will stop restart attempts.

```bash
# Check crash loop status and reset
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "sudo journalctl -u aragora -n 100 --no-pager | tail -50",
    "echo === RECENT CRASHES ===",
    "sudo journalctl -u aragora --since \"1 hour ago\" | grep -c \"Main process exited\" || echo 0",
    "echo === RESETTING FAILURE COUNT ===",
    "sudo systemctl reset-failed aragora",
    "sudo systemctl start aragora",
    "sleep 5",
    "systemctl status aragora --no-pager | head -15"
  ]' \
  --timeout-seconds 60 \
  --region us-east-2
```

**Common crash causes and fixes:**

| Cause | Log Pattern | Fix |
|-------|------------|-----|
| Import error after deploy | `ModuleNotFoundError` | Re-run `pip install -e .` |
| Port already in use | `Address already in use :8080` | Kill stale process: `sudo fuser -k 8080/tcp` |
| Missing secrets | `ARAGORA_USE_SECRETS_MANAGER` error | Verify systemd drop-in and Secrets Manager |
| Out of memory | `MemoryError` or OOM in dmesg | Increase instance type or add swap |
| Disk full | `OSError: No space left` | Clean logs and temp files |

### 5.4 Log Retrieval

**Recent application logs (journalctl via SSM):**

```bash
# Last 200 lines
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -n 200 --no-pager"]' \
  --timeout-seconds 30 \
  --region us-east-2

# Logs since a specific time
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora --since \"2 hours ago\" --no-pager | tail -500"]' \
  --timeout-seconds 60 \
  --region us-east-2

# Error-only logs
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -p err --since \"1 hour ago\" --no-pager"]' \
  --timeout-seconds 30 \
  --region us-east-2

# nginx access logs
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo tail -100 /var/log/nginx/access.log"]' \
  --timeout-seconds 30 \
  --region us-east-2

# nginx error logs
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo tail -50 /var/log/nginx/error.log"]' \
  --timeout-seconds 30 \
  --region us-east-2
```

**CloudWatch log aggregation:**

```bash
# List log streams
aws logs describe-log-streams \
  --log-group-name "/aragora/production" \
  --query 'logStreams[*].logStreamName' \
  --region us-east-2

# Search for errors across all streams
aws logs filter-log-events \
  --log-group-name "/aragora/production" \
  --filter-pattern "ERROR" \
  --start-time $(date -v-1H +%s)000 \
  --region us-east-2
```

### 5.5 Complete Outage (All Instances Down)

1. **Verify Cloudflare is not the problem:**
   - Check [Cloudflare Status](https://www.cloudflarestatus.com/).
   - Try bypassing Cloudflare by curling an instance IP directly: `curl -H "Host: api.aragora.ai" http://<INSTANCE_EIP>/api/health`.

2. **Check AWS region status:** [AWS Health Dashboard](https://health.aws.amazon.com/).

3. **Restart all instances simultaneously:**

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --comment "Emergency fleet restart" \
  --parameters 'commands=[
    "sudo systemctl restart nginx",
    "sudo systemctl restart aragora",
    "sleep 8",
    "systemctl is-active --quiet aragora && echo OK || echo FAIL",
    "curl -sf http://localhost:8080/api/health | jq .status || echo HEALTH_FAIL"
  ]' \
  --timeout-seconds 120 \
  --region us-east-2
```

4. **If SSM is unreachable on all instances**, reboot via EC2 console:

```bash
aws ec2 reboot-instances \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --region us-east-2
```

---

## 6. Monitoring

### 6.1 Cloudflare Analytics

**Dashboard:** `https://dash.cloudflare.com/<ACCOUNT_ID>/aragora.ai/traffic/load-balancing`

Key metrics to watch:

| Metric | Where to Find | Alert Threshold |
|--------|---------------|-----------------|
| Origin health | Traffic > Load Balancing > Pools | Any origin marked unhealthy |
| Request rate | Analytics & Logs > Traffic | Sudden drop >50% from baseline |
| Error rate (5xx) | Analytics & Logs > Traffic | >1% of requests |
| WAF blocks | Security > Events | Spike in blocked requests |
| Cache hit ratio | Analytics & Logs > Cache | Drop below 30% |

### 6.2 CloudWatch Alarms

| Alarm Name | Metric | Threshold | Period |
|------------|--------|-----------|--------|
| `aragora-api-server-cpu-high` | CPUUtilization > 80% | 5 min | Email |
| `aragora-api-server-status-check` | StatusCheckFailed | 1 | Email |
| `aragora-api-2-cpu-high` | CPUUtilization > 80% | 5 min | Email |
| `aragora-api-2-status-check` | StatusCheckFailed | 1 | Email |
| `aragora-high-error-rate` | ErrorCount > 50 | 10 min | Email |
| `aragora-http-5xx-errors` | HTTP5xxErrors > 10 | 10 min | Email |
| `aragora-http-4xx-errors` | HTTP4xxErrors > 100 | 15 min | Email |

**Check alarm status:**

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix "aragora-" \
  --query 'MetricAlarms[*].[AlarmName,StateValue,StateUpdatedTimestamp]' \
  --output table \
  --region us-east-2
```

**CloudWatch dashboard URL:**
`https://us-east-2.console.aws.amazon.com/cloudwatch/home?region=us-east-2#dashboards:name=Aragora-Production`

### 6.3 Instance-Level Health Monitoring

Check resource utilization on a specific instance:

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "echo === CPU & MEMORY ===",
    "uptime",
    "free -m",
    "echo === DISK ===",
    "df -h / /home /tmp",
    "echo === TOP PROCESSES ===",
    "ps aux --sort=-%mem | head -10",
    "echo === CONNECTIONS ===",
    "ss -s",
    "echo === ARAGORA SERVICE ===",
    "systemctl status aragora --no-pager | head -10",
    "echo === NGINX ===",
    "systemctl status nginx --no-pager | head -5"
  ]' \
  --timeout-seconds 30 \
  --region us-east-2
```

### 6.4 CloudWatch Agent

The CloudWatch agent runs on each instance and sends logs to the `/aragora/production` log group.

```bash
# Check CloudWatch agent status
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo systemctl status amazon-cloudwatch-agent --no-pager | head -10"]' \
  --timeout-seconds 15 \
  --region us-east-2
```

Agent config location: `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.d/`

---

## 7. Common SSM Commands

All commands below use `AWS-RunShellScript` and should include `--region us-east-2`. Replace the instance ID as needed.

### 7.1 Check Version

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ec2-user/aragora 2>/dev/null || cd /opt/aragora",
    "git config --global --add safe.directory $(pwd)",
    "echo commit=$(git rev-parse --short HEAD)",
    "echo branch=$(git branch --show-current 2>/dev/null || echo detached)",
    "echo last_commit_date=$(git log -1 --format=%ci)",
    "source venv/bin/activate 2>/dev/null",
    "python -c \"from aragora import __version__; print(f\\\"version={__version__}\\\")\" 2>/dev/null || echo version=unknown"
  ]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.2 Restart Service

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "sudo systemctl restart aragora",
    "sleep 5",
    "systemctl status aragora --no-pager | head -15",
    "curl -sf http://localhost:8080/api/health | jq .status"
  ]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.3 View Logs

```bash
# Last 100 lines
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -n 100 --no-pager"]' \
  --output text --query "Command.CommandId" \
  --region us-east-2

# Streaming tail (captures ~200 lines then exits)
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -f --no-pager | head -200"]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.4 Deploy Code

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/home/ec2-user",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "sudo -u ec2-user git pull origin main",
    "source venv/bin/activate",
    "pip install -e . --quiet",
    "sudo systemctl restart aragora",
    "sleep 5",
    "curl -s http://localhost:8080/api/health | jq .status"
  ]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.5 Check Systemd Drop-ins

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "echo === SERVICE FILE ===",
    "cat /etc/systemd/system/aragora.service 2>/dev/null || systemctl cat aragora",
    "echo === DROP-INS ===",
    "ls -la /etc/systemd/system/aragora.service.d/ 2>/dev/null || echo \"No drop-in directory\"",
    "echo === DROP-IN CONTENTS ===",
    "cat /etc/systemd/system/aragora.service.d/*.conf 2>/dev/null || echo \"No drop-in files\"",
    "echo === EFFECTIVE CONFIG ===",
    "systemctl show aragora --property=Environment --no-pager"
  ]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.6 Check Database and Redis Connectivity

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "curl -s http://localhost:8080/api/health | jq \"{database: .checks.database, redis: .checks.redis}\""
  ]' \
  --output text --query "Command.CommandId" \
  --region us-east-2
```

### 7.7 Interactive SSM Session

For interactive troubleshooting, use SSM Session Manager instead of Run Command:

```bash
aws ssm start-session \
  --target "i-0823e60c7c4b924e1" \
  --region us-east-2
```

This drops you into a shell on the instance. No SSH keys needed.

### 7.8 Retrieve SSM Command Output

All `send-command` calls return a Command ID. To get the output:

```bash
# Wait for completion and get output
aws ssm get-command-invocation \
  --command-id "<COMMAND_ID>" \
  --instance-id "<INSTANCE_ID>" \
  --query '{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}' \
  --output json \
  --region us-east-2
```

---

## 8. Instance Configuration

### 8.1 Service Architecture

Each EC2 instance runs:

| Service | Port | Managed By |
|---------|------|------------|
| nginx | 80 (HTTP) | systemd (`nginx.service`) |
| Aragora HTTP API | 8080 | systemd (`aragora.service`) |
| Aragora WebSocket | 8765 | systemd (`aragora.service`, same process) |
| SSM Agent | - | systemd (`amazon-ssm-agent.service`) |
| CloudWatch Agent | - | systemd (`amazon-cloudwatch-agent.service`) |

nginx proxies port 80 traffic to the Aragora server on ports 8080/8765.

### 8.2 Systemd Service Unit

The base service file is at `/etc/systemd/system/aragora.service`. On the original instances it typically looks like:

```ini
[Unit]
Description=Aragora API Server (HTTP + WebSocket)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/aragora
Environment="PATH=/home/ec2-user/aragora/venv/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=-/home/ec2-user/aragora/.env
ExecStart=/home/ec2-user/aragora/venv/bin/python -m aragora.server \
    --host 0.0.0.0 \
    --http-port 8080 \
    --port 8765 \
    --nomic-dir /home/ec2-user/aragora/.nomic
Restart=always
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=aragora
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

On AL2023 instances bootstrapped via `deploy/scripts/al2023-bootstrap.sh`, the paths use `/opt/aragora` and the user may be `aragora`.

### 8.3 Systemd Drop-in Directory

Drop-in configs override or extend the base unit file. They live in:

```
/etc/systemd/system/aragora.service.d/
```

**Standard drop-ins deployed by CI:**

| File | Purpose |
|------|---------|
| `secrets.conf` | Enables AWS Secrets Manager, sets region and secret name |
| `distributed.conf` | Enforces distributed mode (multi-instance shared state via PG/Redis) |

**`secrets.conf` contents (written by deploy-secure.yml):**

```ini
[Service]
Environment=ARAGORA_USE_SECRETS_MANAGER=true
Environment=AWS_REGION=us-east-2
Environment=ARAGORA_SECRET_NAME=aragora/production
Environment=ARAGORA_DB_BACKEND=postgres
Environment=ARAGORA_ENV=production
Environment=ARAGORA_SECRETS_STRICT=false
```

**`distributed.conf` contents (for multi-instance deployments):**

```ini
[Service]
Environment="ARAGORA_REQUIRE_DISTRIBUTED=true"
Environment="ARAGORA_MULTI_INSTANCE=true"
Environment="ARAGORA_ENV=production"
Environment="ARAGORA_SINGLE_INSTANCE=false"
Environment="ARAGORA_REQUIRE_DATABASE=true"
```

**After modifying drop-ins:**

```bash
sudo systemctl daemon-reload
sudo systemctl restart aragora
```

### 8.4 Environment Variables

Secrets are loaded at startup from AWS Secrets Manager (`aragora/production`). The key environment variables:

| Variable | Source | Purpose |
|----------|--------|---------|
| `ARAGORA_USE_SECRETS_MANAGER` | Drop-in | Enables loading secrets from AWS SM |
| `ARAGORA_SECRET_NAME` | Drop-in | SM secret ID (`aragora/production`) |
| `AWS_REGION` | Drop-in | AWS region for SM lookups |
| `ARAGORA_ENV` | Drop-in | Environment identifier (`production`) |
| `ARAGORA_DB_BACKEND` | Drop-in | Storage backend (`postgres`) |
| `ARAGORA_REQUIRE_DISTRIBUTED` | Drop-in | Enforces shared-state mode |
| `ARAGORA_MULTI_INSTANCE` | Drop-in | Marks multi-instance deployment |
| `ANTHROPIC_API_KEY` | SM secret | Anthropic/Claude API key |
| `OPENAI_API_KEY` | SM secret | OpenAI API key |
| `OPENROUTER_API_KEY` | SM secret | OpenRouter fallback key |
| `DATABASE_URL` | SM secret | Supabase PostgreSQL connection string |
| `REDIS_URL` | SM secret | Upstash Redis URL (`rediss://`) |
| `ARAGORA_API_TOKEN` | SM secret | API authentication token |

### 8.5 Filesystem Layout (Original Instances)

```
/home/ec2-user/aragora/
  ├── aragora/          # Application source
  ├── venv/             # Python virtual environment
  ├── scripts/          # Operational scripts
  ├── deploy/           # Deploy configurations
  ├── .nomic/           # Nomic state directory
  ├── .env              # Local env overrides (optional)
  └── .git/             # Git repository
```

### 8.6 Filesystem Layout (AL2023 Instances)

```
/opt/aragora/
  ├── venv/             # Python virtual environment
  ├── backups/          # Local backups
  └── .nomic/           # Nomic state directory
/etc/aragora/
  ├── env               # Environment variables file (chmod 600)
  └── env.template      # Template for reference
/var/log/aragora/       # Application logs
```

---

## 9. Secrets Management

### 9.1 View Secret Keys (Not Values)

```bash
aws secretsmanager get-secret-value \
  --secret-id aragora/production \
  --query SecretString --output text \
  --region us-east-2 | jq 'keys'
```

### 9.2 Update a Secret

```bash
# 1. Get current secret to a temp file
aws secretsmanager get-secret-value \
  --secret-id aragora/production \
  --query SecretString --output text \
  --region us-east-2 > /tmp/aragora_secret.json

# 2. Edit the file
# (use your preferred editor)

# 3. Push the updated secret
aws secretsmanager put-secret-value \
  --secret-id aragora/production \
  --secret-string file:///tmp/aragora_secret.json \
  --region us-east-2

# 4. Restart services on all instances to pick up new secrets
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo systemctl restart aragora"]' \
  --region us-east-2

# 5. Clean up
rm -f /tmp/aragora_secret.json
```

### 9.3 API Key Rotation

See `docs/deployment/PRODUCTION_RUNBOOK.md` for detailed key rotation procedures for Supermemory, GovInfo, and NICE API keys.

---

## 10. Maintenance Windows

### Recommended Schedule

| Window | UTC Time | Local (US Eastern) | Use For |
|--------|----------|---------------------|---------|
| Best | 06:00-08:00 | 01:00-03:00 AM | Major updates, migrations |
| Acceptable | 10:00-14:00 | 05:00-09:00 AM | Routine maintenance |
| Avoid | 14:00-22:00 | 09:00 AM-05:00 PM | Peak usage |

### Pre-Maintenance Checklist

- [ ] Notify stakeholders of upcoming maintenance window
- [ ] Verify rollback procedure works (check `/tmp/aragora_deploy_state` exists)
- [ ] Open CloudWatch dashboard and Cloudflare analytics
- [ ] Confirm all instances are healthy: `curl -s https://api.aragora.ai/api/health`
- [ ] Record current commit SHA from each instance for rollback reference

### Post-Maintenance Checklist

- [ ] Verify health endpoints return `"status":"healthy"` on all instances
- [ ] Confirm all instances are on the same commit (Section 4.4)
- [ ] Test debate creation: `POST /api/debates` with a simple question
- [ ] Check CloudWatch for error spikes in the 15 minutes post-deploy
- [ ] Confirm Cloudflare LB shows all origins healthy
- [ ] Verify no error spikes in `journalctl -u aragora --since "15 min ago"`

---

## Appendix A: Quick Reference Card

| Task | Command |
|------|---------|
| External health | `curl -s https://api.aragora.ai/api/health \| jq .` |
| Instance health | SSM: `curl -s http://localhost:8080/api/health \| jq` |
| View logs | SSM: `sudo journalctl -u aragora -n 100 --no-pager` |
| Restart service | SSM: `sudo systemctl restart aragora` |
| Check version | SSM: `cd /home/ec2-user/aragora && git rev-parse --short HEAD` |
| Restart nginx | SSM: `sudo systemctl restart nginx` |
| Interactive shell | `aws ssm start-session --target <INSTANCE_ID> --region us-east-2` |
| Deploy (CI) | Push to `main` or Actions > Deploy (Secure) > Run workflow |
| Check alarms | `aws cloudwatch describe-alarms --alarm-name-prefix aragora- --output table` |
| Check LB health | Cloudflare Dashboard > Traffic > Load Balancing > Pools |

## Appendix B: Related Documentation

| Document | Path | Purpose |
|----------|------|---------|
| Existing production runbook | `docs/deployment/PRODUCTION_RUNBOOK.md` | Original runbook with auth, DB ops, Redis details |
| Cloudflare LB setup guide | `deploy/cloudflare-lb-setup.md` | Full LB configuration, DR, WebSocket setup |
| Deploy workflow | `.github/workflows/deploy-secure.yml` | CI/CD pipeline definition |
| AL2023 bootstrap script | `deploy/scripts/al2023-bootstrap.sh` | Instance provisioning for AL2023 |
| Service installer | `deploy/scripts/install-service.sh` | Systemd service setup (auto-detects env) |
| Base service unit | `deploy/aragora.service` | Template systemd unit file |
| Secrets drop-in | `deploy/systemd/aragora.service.d/secrets.conf` | Secrets Manager configuration |
| Distributed drop-in | `deploy/systemd/distributed.conf` | Multi-instance enforcement |
| IAM deploy policy | `deploy/aws/deploy-role-policy.json` | IAM permissions for CI deploy role |
| OIDC trust policy | `deploy/aws/oidc-trust-policy.json` | GitHub Actions OIDC federation |
| Pre-deploy checklist | `scripts/pre_deploy_check.sh` | Local pre-deploy validation script |
| Production validator | `scripts/validate_production.py` | Post-deploy production validation |
| Health watchdog | `deploy/scripts/healthcheck-watchdog.sh` | Auto-restart on health failure |
| Terraform multi-region | `deploy/terraform/ec2-multiregion/` | IaC for EC2 fleet provisioning |
