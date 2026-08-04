# AWS provider — Route 53 DNS for the staging environment.
#
# Credentials are never stored here. The CD pipeline provides them via GitHub
# secrets (aws-actions/configure-aws-credentials); local runs use the standard
# AWS credential chain.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
