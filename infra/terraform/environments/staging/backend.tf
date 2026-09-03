# Remote state - S3 + DynamoDB locking.
#
# The bucket and lock table are provisioned once out-of-band (see
# docs/runbooks/staging-deployment.md). The values here are empty on purpose:
# the CD pipeline injects them via -backend-config from GitHub secrets, and
# local runs pass the same flags. `terraform init -backend=false` skips the
# backend entirely (used by CI validation, which never touches real state).
terraform {
  backend "s3" {
    bucket         = ""
    key            = "staging/terraform.tfstate"
    region         = ""
    dynamodb_table = ""
    encrypt        = true
  }
}
