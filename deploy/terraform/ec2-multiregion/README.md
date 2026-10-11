# Aragora EC2 Multi-Region Terraform Module

Deploy Aragora API servers on Amazon Linux 2023 across multiple AWS regions with Cloudflare load balancing.

## Architecture

```
                    ┌─────────────────┐
                    │  Cloudflare LB  │
                    │ api.aragora.ai  │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│    us-east-2    │ │    us-east-2    │ │    eu-west-1    │
│     Primary     │ │    Secondary    │ │       DR        │
│   t3.large      │ │   t3.large      │ │   t3.large      │
└─────────────────┘ └─────────────────┘ └─────────────────┘
     Weight: 1           Weight: 1          Weight: 0.5
```

## Prerequisites

- Terraform >= 1.5.0
- AWS CLI configured with appropriate credentials
- Cloudflare account with Load Balancing enabled

## Quick Start

### 1. Initialize Terraform

```bash
cd deploy/terraform/ec2-multiregion
terraform init
```

### 2. Deploy Primary Region (us-east-2)

```bash
# Create workspace
terraform workspace new us-east-2-primary || terraform workspace select us-east-2-primary

# Plan
terraform plan \
  -var="region=us-east-2" \
  -var="role=primary" \
  -var="environment=production"

# Apply
terraform apply \
  -var="region=us-east-2" \
  -var="role=primary" \
  -var="environment=production"
```

### 3. Deploy Secondary Instance (us-east-2)

```bash
terraform workspace new us-east-2-secondary || terraform workspace select us-east-2-secondary

terraform apply \
  -var="region=us-east-2" \
  -var="role=secondary" \
  -var="environment=production"
```

### 4. Deploy DR Instance (eu-west-1)

```bash
terraform workspace new eu-west-1-dr || terraform workspace select eu-west-1-dr

terraform apply \
  -var="region=eu-west-1" \
  -var="role=dr" \
  -var="environment=production"
```

## Configuration

Copy `terraform.tfvars.example` to `terraform.tfvars` and customize:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

### Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `region` | AWS region | `us-east-2` |
| `role` | Instance role: primary, secondary, dr | `primary` |
| `environment` | Environment: production, staging, development | `production` |
| `instance_type` | EC2 instance type | `t3.large` |
| `root_volume_size` | Root EBS volume size (GB) | `50` |
| `vpc_id` | VPC ID (empty for default VPC) | `""` |
| `subnet_id` | Subnet ID (empty for auto-select) | `""` |
| `admin_cidr_blocks` | CIDR blocks for SSH access | `[]` |
| `key_name` | EC2 key pair name (SSM preferred) | `""` |

## What Gets Deployed

### Per Instance
- EC2 instance with Amazon Linux 2023
- Elastic IP for static addressing
- Security group (Cloudflare IPs only for HTTP)
- IAM role with SSM and Secrets Manager access

### Software Stack
- Python 3.11 with virtual environment
- The base `aragora` package. Optional extras are defined in `pyproject.toml`
  `[project.optional-dependencies]` (`gateway`, `enterprise`, `connectors`,
  `blockchain`, `experimental`, `all`); add the ones a deployment needs to the
  `pip install` lines in `user-data.sh` and in [Update Aragora](#update-aragora).
- nginx reverse proxy
- CloudWatch agent for logs/metrics
- systemd service (aragora)

## Post-Deployment Setup

### 1. Configure Secrets

Connect via SSM Session Manager:

```bash
# Get the SSM command from terraform output
terraform output ssm_start_session

# Or manually:
aws ssm start-session --target <instance-id> --region <region>
```

Create the environment file:

```bash
sudo nano /etc/aragora/env
```

Required variables:
```bash
DATABASE_URL=postgresql://user:password@host:5432/aragora
ARAGORA_REDIS_URL=redis://host:6379
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
```

### 2. Start Services

```bash
sudo systemctl start aragora
sudo systemctl enable aragora
```

### 3. Verify Health

```bash
curl http://localhost/api/health
```

### 4. Add to Cloudflare Load Balancer

Get the Elastic IP:
```bash
terraform output public_ip
```

Add as origin to Cloudflare pool (see `deploy/cloudflare-lb-setup.md`).

## Outputs

| Output | Description |
|--------|-------------|
| `instance_id` | EC2 instance ID |
| `public_ip` | Elastic IP (use for Cloudflare) |
| `private_ip` | Private IP |
| `ssm_start_session` | SSM connection command |
| `health_check_url` | Direct health check URL |
| `cloudflare_origin` | Origin config for Cloudflare |

## Secrets (Optional)

### Supermemory API Key (AWS Secrets Manager)

Use a dedicated secret (`aragora/api/supermemory`) replicated across regions.

```hcl
provider "aws" {
  region = "us-east-1"
}

resource "aws_secretsmanager_secret" "supermemory" {
  name                    = "aragora/api/supermemory"
  recovery_window_in_days = 7

  replica {
    region = "us-east-2"
  }
}

resource "aws_secretsmanager_secret_version" "supermemory" {
  secret_id     = aws_secretsmanager_secret.supermemory.id
  secret_string = jsonencode({ SUPERMEMORY_API_KEY = var.supermemory_api_key })
}

variable "supermemory_api_key" {
  type      = string
  sensitive = true
}
```

## Security

### Network Security
- HTTP (80) only accessible from Cloudflare IP ranges
- SSH (22) only if `admin_cidr_blocks` specified (prefer SSM)
- All egress allowed

### Instance Security
- IAM role with least-privilege policies
- SSM Session Manager for shell access (no SSH keys needed)
- Secrets stored in AWS Secrets Manager
- systemd services run as non-root `aragora` user
- SecuritySystem hardening enabled

## Cost Estimate

| Resource | Monthly Cost (approx) |
|----------|----------------------|
| EC2 t3.large (3x) | ~$180 |
| EBS 50GB gp3 (3x) | ~$12 |
| Elastic IPs (3x) | ~$11 |
| Data transfer | ~$50-100 |
| **Total** | **~$250-300** |

## Maintenance

### Update Aragora

```bash
# Connect via SSM
aws ssm start-session --target <instance-id>

# Update
sudo -u aragora /opt/aragora/venv/bin/pip install --upgrade aragora

# Restart
sudo systemctl restart aragora
```

### View Logs

```bash
# Application logs
sudo journalctl -u aragora -f

# nginx logs
sudo tail -f /var/log/nginx/access.log
```

## Disaster Recovery

The DR instance in `eu-west-1` provides:
- Geographic redundancy
- Single-region failure resilience
- Lower weight (0.5) in Cloudflare pool for normal traffic distribution

### Failover Testing

1. Disable primary origins in Cloudflare pool
2. Verify traffic routes to DR instance
3. Check application functionality
4. Re-enable primary origins

### Recovery Procedure

If primary region fails:
1. Cloudflare automatically routes to DR
2. Scale up DR instance if needed (`instance_type` variable)
3. Deploy additional instances in alternate region if extended outage

## Troubleshooting

### Instance Not Healthy

```bash
# Check services
sudo systemctl status aragora nginx

# Check logs
sudo journalctl -u aragora --since "10 minutes ago"

# Check environment
sudo cat /etc/aragora/env
```

### Cloudflare 521 Error

- Verify security group includes latest Cloudflare IPs
- Check nginx is running: `sudo systemctl status nginx`
- Verify aragora is responding: `curl localhost:8080/api/health`

### SSM Connection Failed

- Verify IAM role has `AmazonSSMManagedInstanceCore` policy
- Check SSM agent is running: `sudo systemctl status amazon-ssm-agent`
- Ensure instance has outbound internet access

## Standalone Bootstrap

For manual installation without Terraform, use:

```bash
curl -O https://raw.githubusercontent.com/aragora/aragora/main/deploy/scripts/al2023-bootstrap.sh
chmod +x al2023-bootstrap.sh
sudo ./al2023-bootstrap.sh production primary us-east-2
```

See `deploy/scripts/al2023-bootstrap.sh` for details.
