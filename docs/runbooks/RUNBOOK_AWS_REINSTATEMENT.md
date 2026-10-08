# Runbook: AWS Account Reinstatement (post-suspension)

**Context:** On 2026-07-16 the production AWS account was suspended for
non-payment following an accidental S3 storage runaway (Feb–Apr 2026,
`TimedStorage-ByteHrs` on versioned buckets with no noncurrent-version
expiration). `api.aragora.ai` (EC2, us-east-2) and all EC2 self-hosted CI
runners went offline; GitHub OIDC `AssumeRoleWithWebIdentity` is rejected
while suspended. A billing dispute / goodwill-credit case is open with AWS
(operator-side; specifics live in the support case, not this public repo).

This runbook is the **ordered checklist for the moment the account is
reinstated**, so recovery is minutes of execution rather than rediscovery.
Phases 1–2 are deliberately sequenced: *preserve first, diagnose second,
restart third* — the data in the account (secrets, volumes, backups) is
inaccessible while suspended and is the only copy of some material.

---

## Phase 0 — While still suspended (operator, ongoing)

- [ ] Keep the AWS support case alive: it is set "Pending Customer Action"
      and will auto-resolve if idle. Reply every 2–3 days until resolved.
- [ ] Fix the payment-method validation error in the Billing console
      (blocks any payment from processing, including partial payment).
- [ ] Pay the undisputed (non-S3) portion of the balance as offered in the
      case — strengthens the goodwill request and shortens reinstatement.
- [ ] Billing console remains readable while suspended: use
      **Bills → S3 usage types** to split `TimedStorage-ByteHrs` vs request
      tiers per bucket region if further diagnosis is needed pre-reinstatement.
- [ ] Consider a one-month Business Support upgrade for faster finance
      review turnaround while production is down.

## Phase 1 — First hour after reinstatement: preserve

Authenticate with MFA per the credential policy (no standing keys):
`aws sso login` / MFA assume-role, verify with `aws sts get-caller-identity`.

- [ ] **Export secrets to an offline backup** (password manager / encrypted
      disk, NOT this repo). At minimum `aragora/production`, which contains
      the prod Ed25519 receipt-signing key (`ed25519-8f9014589b35ab85` —
      the identity committed to by the published well-known key; it must
      never exist only inside AWS again):

      ```bash
      aws secretsmanager list-secrets --query 'SecretList[].Name'
      aws secretsmanager get-secret-value --secret-id aragora/production \
        --query SecretString --output text   # -> store offline immediately
      ```

- [ ] **Snapshot the production and staging EC2 volumes** before any
      restart or config change (instance IDs: see private ops notes /
      `MEMORY.md`):

      ```bash
      aws ec2 describe-instances --region us-east-2 \
        --query 'Reservations[].Instances[].{id:InstanceId,state:State.Name,name:Tags[?Key==`Name`]|[0].Value}'
      aws ec2 create-snapshots --region us-east-2 \
        --instance-specification InstanceId=<prod-instance-id> \
        --description "post-reinstatement preserve $(date +%F)"
      ```

## Phase 2 — Same day: guardrails, then restart

- [ ] **Identify the runaway bucket(s)** — versioned buckets with no
      noncurrent-version expiration, sorted by size (read-only):

      ```bash
      python scripts/aws_cost_guardrails.py audit
      ```

- [ ] **Apply the promised remediation** (recorded in the AWS case:
      lifecycle policies + budget alerts). Merge-safe and idempotent:

      ```bash
      python scripts/aws_cost_guardrails.py lifecycle --apply
      python scripts/aws_cost_guardrails.py budget --email <ops-email> --limit 2500 --apply
      ```

      Terraform-managed deployments get the same via
      `deploy/terraform/single-region/main.tf`
      (`noncurrent_version_retention_days`, `budget_alert_emails`).

- [ ] If large noncurrent-version debris remains and cost pressure is
      immediate, the lifecycle rules will drain it within
      `--noncurrent-days`; do NOT bulk-delete objects by hand while the
      billing dispute is open — the usage history is evidence.
- [ ] **Restart instances** if stopped (`aws ec2 start-instances`), then
      verify origin health directly and through Cloudflare:

      ```bash
      curl -s https://api.aragora.ai/api/health
      ```

- [ ] **Re-enable the two workflows manually disabled on Jul 16**:

      ```bash
      gh workflow enable deploy-secure.yml       # also restores the Vercel frontend deploy job
      gh workflow enable production-monitor.yml
      ```

- [ ] Verify the 6 EC2 self-hosted runners re-register in GitHub
      (Settings → Actions → Runners; Hetzner + Mac runners were unaffected).
- [ ] Confirm a `deploy-secure.yml` run passes the OIDC
      `Configure AWS credentials` step (proves STS/OIDC is restored).
- [ ] Confirm `production-monitor.yml` goes green and alerts on failure
      (its timeout previously surfaced as "cancelled", which nothing
      alerted on — watch the first runs manually).

## Phase 3 — Within the week: un-defer the external-proof items

- [ ] Run the **W1 signed-prod-receipt runbook**
      (`~/.aragora/runbooks/W1_SIGNED_PROD_RECEIPT_RUNBOOK.md`, ~10 min:
      one prod decision → fetch receipt → offline verify against the
      well-known key → commit artifact).
- [ ] Update `docs/status/QUALITY_BAR.md`: remove the recorded deferral of
      the dimension-4 instrument (fresh production receipt) and the
      W1 founder-MFA prod receipt; note the reinstatement date.
- [ ] Note the resolution in the next weekly digest (the deferral is
      re-reviewed there by rule).
- [ ] Post-incident follow-ups: EC2 coverage for `fleet_health_monitor.sh`,
      and a billing-anomaly alarm independent of the (previously dead)
      runner-headcount monitor.
