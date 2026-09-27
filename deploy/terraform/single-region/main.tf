# Aragora Single-Region AWS Infrastructure
# A simplified production-ready setup for single-region deployments
#
# Usage:
#   1. Copy terraform.tfvars.example to terraform.tfvars
#   2. Edit terraform.tfvars with your values
#   3. Run: terraform init && terraform plan && terraform apply

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment for remote state (recommended for production)
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "aragora/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

# ============================================================================
# Variables
# ============================================================================

variable "region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., production, staging)"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "aragora"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium" # Cost-effective for small deployments
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 50
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.small" # Cost-effective for small deployments
}

variable "eks_instance_types" {
  description = "EKS node instance types"
  type        = list(string)
  default     = ["t3.medium", "t3.large"]
}

variable "eks_min_nodes" {
  description = "Minimum number of EKS nodes"
  type        = number
  default     = 2
}

variable "eks_max_nodes" {
  description = "Maximum number of EKS nodes"
  type        = number
  default     = 10
}

variable "eks_desired_nodes" {
  description = "Desired number of EKS nodes"
  type        = number
  default     = 2
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection for RDS"
  type        = bool
  default     = true
}

variable "noncurrent_version_retention_days" {
  description = "Days to retain noncurrent (superseded) S3 object versions before expiration"
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 1
    error_message = "noncurrent_version_retention_days must be >= 1."
  }
}

variable "monthly_budget_limit" {
  description = "Monthly AWS cost budget in USD; alerts fire at 50/80/100% actual and 100% forecasted"
  type        = number
  default     = 2500
}

variable "budget_alert_emails" {
  description = "Email addresses to notify when budget thresholds are crossed (empty list disables the budget)"
  type        = list(string)
  default     = []
}

# ============================================================================
# Locals
# ============================================================================

locals {
  name = "${var.project_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ============================================================================
# Provider Configuration
# ============================================================================

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# ============================================================================
# VPC
# ============================================================================

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = local.name
  cidr = var.vpc_cidr

  azs              = local.azs
  private_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets   = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 4)]
  database_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway     = true
  single_nat_gateway     = var.environment != "production" # Cost savings for non-prod
  one_nat_gateway_per_az = var.environment == "production"

  enable_dns_hostnames = true
  enable_dns_support   = true

  # VPC Flow Logs (optional, recommended for security)
  enable_flow_log                      = var.environment == "production"
  create_flow_log_cloudwatch_log_group = var.environment == "production"
  create_flow_log_cloudwatch_iam_role  = var.environment == "production"

  # Tags for EKS
  public_subnet_tags = {
    "kubernetes.io/cluster/${local.name}" = "shared"
    "kubernetes.io/role/elb"              = 1
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${local.name}" = "shared"
    "kubernetes.io/role/internal-elb"     = 1
  }

  tags = local.tags
}

# ============================================================================
# EKS Cluster
# ============================================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = local.name
  cluster_version = "1.29"

  cluster_endpoint_public_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Managed node group
  eks_managed_node_groups = {
    default = {
      name = "${local.name}-nodes"

      instance_types = var.eks_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.eks_min_nodes
      max_size     = var.eks_max_nodes
      desired_size = var.eks_desired_nodes

      labels = {
        environment = var.environment
      }

      tags = {
        "k8s.io/cluster-autoscaler/enabled"      = "true"
        "k8s.io/cluster-autoscaler/${local.name}" = "owned"
      }
    }
  }

  # OIDC for IRSA (IAM Roles for Service Accounts)
  enable_irsa = true

  # Essential addons
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
    aws-ebs-csi-driver = {
      most_recent = true
    }
  }

  tags = local.tags
}

# ============================================================================
# RDS PostgreSQL
# ============================================================================

module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"

  identifier = local.name

  engine               = "postgres"
  engine_version       = "16.1"
  family               = "postgres16"
  major_engine_version = "16"
  instance_class       = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 4

  db_name  = "aragora"
  username = "aragora"
  port     = 5432

  # Generate random password
  manage_master_user_password = true

  # High availability for production
  multi_az = var.environment == "production"

  # Networking
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [module.sg_rds.security_group_id]

  # Backup
  backup_retention_period = var.environment == "production" ? 30 : 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Security
  deletion_protection       = var.enable_deletion_protection
  storage_encrypted         = true
  skip_final_snapshot       = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${local.name}-final-snapshot" : null

  # Performance Insights (free tier for 7 days)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Enhanced monitoring
  create_monitoring_role = true
  monitoring_interval    = 60

  tags = local.tags
}

# ============================================================================
# ElastiCache Redis
# ============================================================================

resource "aws_elasticache_subnet_group" "default" {
  name       = local.name
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = local.name
  description          = "Redis cluster for ${local.name}"

  engine               = "redis"
  engine_version       = "7.0"
  node_type            = var.redis_node_type
  num_cache_clusters   = var.environment == "production" ? 2 : 1
  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name  = aws_elasticache_subnet_group.default.name
  security_group_ids = [module.sg_redis.security_group_id]

  # Failover
  automatic_failover_enabled = var.environment == "production"
  multi_az_enabled           = var.environment == "production"

  # Encryption
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  # Snapshots
  snapshot_retention_limit = var.environment == "production" ? 7 : 1
  snapshot_window          = "05:00-06:00"

  tags = local.tags
}

# ============================================================================
# Security Groups
# ============================================================================

module "sg_rds" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "~> 5.0"

  name        = "${local.name}-rds"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = module.vpc.vpc_id

  ingress_with_source_security_group_id = [
    {
      from_port                = 5432
      to_port                  = 5432
      protocol                 = "tcp"
      source_security_group_id = module.eks.cluster_security_group_id
      description              = "PostgreSQL from EKS"
    }
  ]

  tags = local.tags
}

module "sg_redis" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "~> 5.0"

  name        = "${local.name}-redis"
  description = "Security group for ElastiCache Redis"
  vpc_id      = module.vpc.vpc_id

  ingress_with_source_security_group_id = [
    {
      from_port                = 6379
      to_port                  = 6379
      protocol                 = "tcp"
      source_security_group_id = module.eks.cluster_security_group_id
      description              = "Redis from EKS"
    }
  ]

  tags = local.tags
}

# ============================================================================
# S3 Bucket for Backups
# ============================================================================

resource "aws_s3_bucket" "backup" {
  bucket = "${local.name}-backups-${data.aws_caller_identity.current.account_id}"

  tags = local.tags
}

resource "aws_s3_bucket_versioning" "backup" {
  bucket = aws_s3_bucket.backup.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = var.environment == "production" ? 365 : 90
    }

    # With versioning enabled, `expiration` above only creates delete markers;
    # noncurrent versions otherwise accumulate in STANDARD forever (the Feb-Apr
    # 2026 TimedStorage-ByteHrs runaway). No noncurrent transition tier: at the
    # default 30-day retention it would coincide with expiration (S3 requires
    # expiration strictly after transition) and IA minimum-storage charges
    # would negate the savings for such short-lived versions.
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "purge-expired-delete-markers"
    status = "Enabled"

    expiration {
      expired_object_delete_marker = true
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket = aws_s3_bucket.backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ============================================================================
# Cost Guardrails — AWS Budgets
# ============================================================================
# Alerting-only (does not stop resources). Root-caused from the Feb-Apr 2026
# S3 storage runaway that went unnoticed until the invoices arrived.

resource "aws_budgets_budget" "monthly_cost" {
  count = length(var.budget_alert_emails) > 0 ? 1 : 0

  name         = "${local.name}-monthly-cost-guardrail"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_limit)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_certificate_authority" {
  description = "EKS cluster certificate authority data"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.db_instance_endpoint
}

output "rds_secret_arn" {
  description = "ARN of the Secrets Manager secret containing RDS credentials"
  value       = module.rds.db_instance_master_user_secret_arn
}

output "redis_endpoint" {
  description = "Redis primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "backup_bucket" {
  description = "S3 backup bucket name"
  value       = aws_s3_bucket.backup.bucket
}

output "configure_kubectl" {
  description = "Command to configure kubectl"
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
