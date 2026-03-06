# Canary Deploy Configuration

## Current Architecture

```
                    ┌──────────────┐
   Internet ──────▶ │  Cloudflare  │
                    │   LB: api.   │
                    │ aragora.ai   │
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │  Pool:       │
                    │  aaee5146... │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌─────────────┐          ┌─────────────┐
     │  Production  │          │  Staging x3  │
     │ 3.143.224.156│          │ (not in LB)  │
     │ i-07e538...  │          │              │
     └─────────────┘          └─────────────┘
```

## Prerequisites (Human Steps Required)

The Cloudflare API token in `aragora/cloudflare` (AWS Secrets Manager) currently has
**zone-level** Load Balancing read access but lacks **account-level** pool edit permission.

### Step 1: Upgrade Cloudflare API Token (5 min)

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Go to **My Profile** → **API Tokens** → find the token starting with `pXpad8o0`
3. Click **Edit** (or create a new token)
4. Add these permissions:
   - **Account** → **Load Balancing: Edit**
   - **Account** → **Load Balancing: Read** (if not already present)
5. Click **Save**
6. Update the secret in AWS:
   ```bash
   aws secretsmanager update-secret \
     --secret-id aragora/cloudflare \
     --secret-string '{"CLOUDFLARE_API_TOKEN":"<new-or-same-token>"}'
   ```
7. Also add it to GitHub Secrets:
   - Go to https://github.com/synaptent/aragora/settings/secrets/actions
   - Add secret: `CLOUDFLARE_API_TOKEN` with the token value

### Step 2: Tag a Second Production Instance (2 min)

Currently only 1 instance is tagged `Environment=production`. For rolling canary,
we need at least 2. Promote one staging instance:

```bash
# Promote staging instance to production
aws ec2 create-tags \
  --resources i-0823e60c7c4b924e1 \
  --tags Key=Environment,Value=production

# Verify
aws ec2 describe-instances \
  --filters "Name=tag:Environment,Values=production" \
    "Name=tag:Application,Values=aragora" \
    "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress]' \
  --output table
```

### Step 3: Add Second Origin to Cloudflare Pool (3 min)

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Go to **aragora.ai** → **Traffic** → **Load Balancing** → **Pools**
3. Edit the pool `aaee5146...`
4. Add a new origin:
   - **Name:** `aragora-prod-2`
   - **Address:** `3.141.170.60` (the promoted instance)
   - **Weight:** `1`
   - **Enabled:** Yes
5. Click **Save**

### Step 4: Verify Health Monitor (1 min)

Ensure the pool has a health monitor configured:

1. In the pool settings, check **Health Check**
2. If not set, create one:
   - **Type:** HTTP
   - **Path:** `/api/v1/health`
   - **Expected codes:** 200
   - **Interval:** 60 seconds
   - **Retries:** 2

## How Canary Deploy Works (After Setup)

Once configured, the `deploy-secure.yml` production job will:

1. **Get all production instance IDs** (now 2+)
2. **Deploy to first instance only** (canary)
3. **Wait 60s**, verify health via Cloudflare LB
4. **If healthy**, deploy to remaining instances
5. **If unhealthy**, rollback canary, skip remaining

The Cloudflare LB health monitor automatically removes unhealthy origins,
so even if the canary fails, traffic routes to the healthy instance.

## Manual Canary Deploy

To test the canary pattern manually:

```bash
# 1. Deploy to canary instance only
CANARY_ID="i-07e538fafbe61696d"
aws ssm send-command \
  --instance-ids "$CANARY_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ec2-user/aragora && git pull && source venv/bin/activate && pip install -e . --quiet && sudo systemctl restart aragora"]'

# 2. Wait and verify
sleep 60
curl -sf https://api.aragora.ai/api/v1/health

# 3. If healthy, deploy to remaining instances
REMAINING_IDS="i-0823e60c7c4b924e1"
aws ssm send-command \
  --instance-ids "$REMAINING_IDS" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ec2-user/aragora && git pull && source venv/bin/activate && pip install -e . --quiet && sudo systemctl restart aragora"]'
```

## Rollback

If a deploy goes wrong:

```bash
# Rollback all production instances to previous commit
INSTANCE_IDS="i-07e538fafbe61696d,i-0823e60c7c4b924e1"
aws ssm send-command \
  --instance-ids ${INSTANCE_IDS//,/ } \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ec2-user/aragora && source /tmp/aragora_deploy_state && git checkout $PREVIOUS_COMMIT && source venv/bin/activate && pip install -e . --quiet && sudo systemctl restart aragora"]'
```
