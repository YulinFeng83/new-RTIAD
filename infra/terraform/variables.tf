variable "client_name" {
  description = "Short client identifier (lowercase, no spaces) - used in resource names"
  type        = string
}

variable "client_display_name" {
  description = "Human-readable client name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)"
  type        = string
  default     = "prod"
}

variable "capacity_id" {
  description = "Fabric capacity ID to assign to the created workspace"
  type        = string
}
