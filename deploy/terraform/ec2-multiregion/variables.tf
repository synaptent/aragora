# =============================================================================
# Input Variables for Aragora EC2 Multi-Region Infrastructure
# =============================================================================

variable "region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-2"

  validation {
    condition     = contains(["us-east-2", "eu-west-1", "ap-south-1"], var.region)
    error_message = "Region must be one of: us-east-2, eu-west-1, ap-south-1."
  }
}

variable "environment" {
  description = "Environment name (production, staging, development)"
  type        = string
  default     = "production"
}

variable "role" {
  description = "Instance role: primary, secondary, or dr"
  type        = string
  default     = "primary"

  validation {
    condition     = contains(["primary", "secondary", "dr"], var.role)
    error_message = "Role must be one of: primary, secondary, dr."
  }
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.large"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 50
}

variable "key_name" {
  description = "SSH key pair name (optional - use SSM instead)"
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID (leave empty for default VPC)"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID (leave empty for auto-selection)"
  type        = string
  default     = ""
}

variable "admin_cidr_blocks" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = []  # Empty = no SSH access, use SSM
}

variable "alarm_sns_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms"
  type        = string
  default     = ""
}

variable "enable_detailed_monitoring" {
  description = "Enable detailed monitoring (1-minute intervals)"
  type        = bool
  default     = true
}
