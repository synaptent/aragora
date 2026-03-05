# Aragora Production Runbook

This runbook provides operational procedures for managing the Aragora production environment.

## Infrastructure Overview

| Component | Service | Region | Notes |
|-----------|---------|--------|-------|
| API Server #1 | EC2 `i-0823e60c7c4b924e1` | us-east-2 | aragora-api-server-al2023 (AL2023) |
| API Server #2 | EC2 `i-07e538fafbe61696d` | us-east-2 | aragora-api-2-al2023 (AL2023) |
| Database | Supabase PostgreSQL | - | Transaction pooler mode |
| Cache | Upstash Redis | us-east-2 | TLS enabled |
| CDN/WAF | Cloudflare | - | SSL termination, load balancing |
| Secrets | AWS Secrets Manager | us-east-2 | `aragora/production` |
| Monitoring | CloudWatch | us-east-2 | CPU and status alarms |

## Common Operations

### Check Service Status

```bash
# Via AWS SSM (recommended)
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["systemctl status aragora --no-pager"]' \
  --output text --query "Command.CommandId"

# Get command result
aws ssm get-command-invocation --command-id "<COMMAND_ID>" --instance-id "i-0823e60c7c4b924e1"
```

### Check Health Endpoint

```bash
# External (via Cloudflare)
curl -s https://api.aragora.ai/api/health | jq

# Internal (via SSM)
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -s http://localhost:8080/api/health | jq"]' \
  --output text --query "Command.CommandId"
```

### View Service Logs

```bash
# Recent logs (last 100 lines)
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -n 100 --no-pager"]' \
  --output text --query "Command.CommandId"

# Follow logs (for debugging)
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo journalctl -u aragora -f --no-pager | head -200"]' \
  --output text --query "Command.CommandId"
```

### Restart Service

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo systemctl restart aragora && sleep 5 && systemctl status aragora --no-pager | head -15"]' \
  --output text --query "Command.CommandId"
```

### Deploy Updates

```bash
# Manual deploy to single instance
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/home/ec2-user",
    "cd /home/ec2-user/aragora",
    "git config --global --add safe.directory /home/ec2-user/aragora",
    "git pull origin main",
    "source venv/bin/activate",
    "pip install -e . --quiet",
    "sudo systemctl restart aragora",
    "sleep 5",
    "curl -s http://localhost:8080/api/health | jq .status"
  ]' \
  --output text --query "Command.CommandId"

# Deploy to both instances
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" "i-07e538fafbe61696d" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[...]'
```

## Authentication

### Generate API Token

```bash
# On the server via SSM
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/home/ec2-user",
    "cd /home/ec2-user/aragora",
    "source venv/bin/activate",
    "export $(grep Environment /etc/systemd/system/aragora.service.d/env.conf | sed -e \"s/Environment=//g\" -e \"s/\\\"//g\" | tr \" \" \"\\n\" | grep ARAGORA_API_TOKEN) 2>/dev/null",
    "python3 -c \"from aragora.server.auth import auth_config; auth_config.configure_from_env(); print(auth_config.generate_token('admin', 3600))\""
  ]' \
  --output text --query "Command.CommandId"
```

Token format: `{loop_id}:{expires_timestamp}:{hmac_signature}`

### Test Authenticated Request

```bash
TOKEN="<your_token>"
curl -s -X POST "https://api.aragora.ai/api/debates" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"question":"Test question","config":{"rounds":1}}'
```

## Database Operations

### Check PostgreSQL Connection

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -s http://localhost:8080/api/health | jq .checks.database"]' \
  --output text --query "Command.CommandId"
```

### Initialize PostgreSQL Stores

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/home/ec2-user",
    "cd /home/ec2-user/aragora",
    "source venv/bin/activate",
    "export ARAGORA_USE_SECRETS_MANAGER=true",
    "python scripts/init_postgres_db.py"
  ]' \
  --output text --query "Command.CommandId"
```

### Supabase Dashboard

- URL: https://supabase.com/dashboard
- Backups: Settings > Database > Backups
- Connection pooling: Settings > Database > Connection pooling

## Redis Operations

### Check Redis Connection

```bash
aws ssm send-command \
  --instance-ids "i-0823e60c7c4b924e1" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -s http://localhost:8080/api/health | jq .checks.redis"]' \
  --output text --query "Command.CommandId"
```

### Redis Configuration

- Service: Upstash Redis
- URL stored in: AWS Secrets Manager (`aragora/production`)
- Environment variable: `REDIS_URL` (with `rediss://` for TLS)

## Monitoring & Alerts

### CloudWatch Dashboard

**Dashboard URL**: https://us-east-2.console.aws.amazon.com/cloudwatch/home?region=us-east-2#dashboards:name=Aragora-Production

Features:
- CPU utilization for both servers
- Network in/out metrics
- Status check failures
- Recent error logs
- Request rate graph
- HTTP error code distribution

### CloudWatch Alarms

| Alarm Name | Metric | Threshold | Action |
|------------|--------|-----------|--------|
| `aragora-api-server-cpu-high` | CPUUtilization > 80% | 5 min | Email alert |
| `aragora-api-server-status-check` | StatusCheckFailed | 1 | Email alert |
| `aragora-api-2-cpu-high` | CPUUtilization > 80% | 5 min | Email alert |
| `aragora-api-2-status-check` | StatusCheckFailed | 1 | Email alert |
| `aragora-high-error-rate` | ErrorCount > 50 | 10 min | Email alert |
| `aragora-http-5xx-errors` | HTTP5xxErrors > 10 | 10 min | Email alert |
| `aragora-http-4xx-errors` | HTTP4xxErrors > 100 | 15 min | Email alert |

### Check Alarm Status

```bash
aws cloudwatch describe-alarms --alarm-names \
  "aragora-api-server-cpu-high" \
  "aragora-api-server-status-check" \
  "aragora-api-2-cpu-high" \
  "aragora-api-2-status-check" \
  "aragora-high-error-rate" \
  "aragora-http-5xx-errors" \
  "aragora-http-4xx-errors" \
  --query 'MetricAlarms[*].[AlarmName,StateValue]' \
  --output table
```

## Incident Response

### Service Down

1. Check health endpoint: `curl https://api.aragora.ai/api/health`
2. Check CloudWatch alarms
3. Check service status via SSM
4. View service logs for errors
5. Restart service if needed
6. Verify health after restart

### High CPU Usage

1. Check active debates: Review recent debate creation
2. Check for runaway processes via SSM
3. Consider scaling horizontally (add instances)
4. Review rate limiting settings

### Database Connection Issues

1. Check Supabase status page
2. Verify connection pooler settings
3. Check if IP is whitelisted (IPv6 required)
4. Review connection pool size

### Authentication Failures

1. Verify token format: `{loop_id}:{expires}:{signature}`
2. Check token expiration
3. Regenerate token if needed
4. Verify `ARAGORA_API_TOKEN` in secrets

## Maintenance Windows

### Recommended Maintenance Time

- **Best time**: UTC 06:00-08:00 (low traffic)
- **Avoid**: UTC 14:00-22:00 (peak usage)

### Pre-Maintenance Checklist

- [ ] Notify stakeholders
- [ ] Create backup/checkpoint
- [ ] Verify rollback procedure
- [ ] Have monitoring dashboards open

### Post-Maintenance Checklist

- [ ] Verify health endpoints
- [ ] Test debate creation
- [ ] Check CloudWatch metrics
- [ ] Confirm no error spikes in logs

## Secrets Management

### View Secret Keys (not values)

```bash
aws secretsmanager get-secret-value \
  --secret-id aragora/production \
  --query SecretString --output text | jq 'keys'
```

### Update Secret

```bash
# Get current secret
aws secretsmanager get-secret-value \
  --secret-id aragora/production \
  --query SecretString --output text > /tmp/secret.json

# Edit /tmp/secret.json

# Update secret
aws secretsmanager put-secret-value \
  --secret-id aragora/production \
  --secret-string file:///tmp/secret.json

# Restart services to pick up new secrets
# (Services read secrets at startup)
```

### Supermemory API Key Rotation

Supermemory keys are stored in AWS Secrets Manager (recommended path: `aragora/api/supermemory`)
and replicated across `us-east-1` and `us-east-2`. Rotate manually and update both regions.

```bash
# Rotate via secrets manager script (prompts for new key)
python scripts/secrets_manager.py rotate SUPERMEMORY_API_KEY

# Optional: verify regions after rotation
aws secretsmanager get-secret-value --region us-east-1 --secret-id aragora/api/supermemory
aws secretsmanager get-secret-value --region us-east-2 --secret-id aragora/api/supermemory
```

If you still use the bundled secret (`aragora/production`), ensure the same key is also updated
there for backward compatibility.

### GovInfo + NICE API Key Rotation

GovInfo and NICE keys are stored in AWS Secrets Manager using individual paths:
`aragora/api/govinfo` and `aragora/api/nice`. Rotate manually and update both
`us-east-1` and `us-east-2`.

```bash
# Rotate via secrets manager script (prompts for new key)
python scripts/secrets_manager.py rotate GOVINFO_API_KEY
python scripts/secrets_manager.py rotate NICE_API_KEY

# Optional: verify regions after rotation
aws secretsmanager get-secret-value --region us-east-1 --secret-id aragora/api/govinfo
aws secretsmanager get-secret-value --region us-east-2 --secret-id aragora/api/govinfo
aws secretsmanager get-secret-value --region us-east-1 --secret-id aragora/api/nice
aws secretsmanager get-secret-value --region us-east-2 --secret-id aragora/api/nice
```

## Load Balancing

### Current Setup

Cloudflare load balancing distributes traffic between two EC2 instances:

| Origin | IP | Instance ID |
|--------|-----|-------------|
| aragora-api-server | 3.141.158.91 | i-0823e60c7c4b924e1 |
| aragora-api-2 | 18.222.130.110 | i-07e538fafbe61696d |

### Health Checks

- **Endpoint**: `/api/health` on port 8080
- **Interval**: 60 seconds
- **Timeout**: 5 seconds
- **Expected**: HTTP 200 (accepts both "healthy" and "degraded" status)

### Setup Load Balancing

```bash
# Set credentials
export CLOUDFLARE_API_TOKEN="your_token"
export CLOUDFLARE_ZONE_ID="your_zone_id"

# Run setup script
./scripts/setup_cloudflare_lb.sh
```

### Monitor Load Balancer

- **Dashboard**: https://dash.cloudflare.com/[account_id]/aragora.ai/traffic/load-balancing
- **Pool health**: Check origin status and latency
- **Failover**: Automatic when health check fails

### Failover Behavior

- If one origin fails health checks, traffic routes to healthy origin
- Minimum 1 origin required (configured in pool)
- Notification email sent on origin failure

## Log Aggregation

### CloudWatch Log Streams

All logs are aggregated to CloudWatch log group `/aragora/production`:

| Log Stream | Source | Retention |
|------------|--------|-----------|
| `{instance_id}/system` | `/var/log/messages` | 30 days |
| `{instance_id}/nginx-access` | `/var/log/nginx/access.log` | 30 days |
| `{instance_id}/nginx-error` | `/var/log/nginx/error.log` | 30 days |

### View Logs in CloudWatch

```bash
# List log streams
aws logs describe-log-streams \
  --log-group-name "/aragora/production" \
  --query 'logStreams[*].logStreamName'

# Get recent logs from a stream
aws logs get-log-events \
  --log-group-name "/aragora/production" \
  --log-stream-name "i-0823e60c7c4b924e1/nginx-access" \
  --limit 50

# Search across all streams
aws logs filter-log-events \
  --log-group-name "/aragora/production" \
  --filter-pattern "ERROR" \
  --start-time $(date -d '1 hour ago' +%s)000
```

### CloudWatch Agent Configuration

Agent config location: `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.d/`

```bash
# Check agent status
sudo systemctl status amazon-cloudwatch-agent

# Restart agent
sudo systemctl restart amazon-cloudwatch-agent

# View agent logs
tail -f /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
```

## SSL Certificates

- **Managed by**: Cloudflare
- **Auto-renewal**: Yes (30 days before expiration)
- **Current expiry**: April 2026

### Check Certificate

```bash
echo | openssl s_client -servername api.aragora.ai -connect api.aragora.ai:443 2>/dev/null | openssl x509 -noout -dates
```

## Contact Information

- **Infrastructure**: [Your team/contact]
- **On-call**: [Rotation/schedule]
- **Escalation**: [Escalation path]

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-21 | 1.0 | Initial production runbook |
