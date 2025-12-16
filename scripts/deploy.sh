#!/bin/bash
# scripts/deploy.sh
# Deploy cost optimizer to AWS Lambda
#
# Usage:
#   ./scripts/deploy.sh [environment]
#
# Examples:
#   ./scripts/deploy.sh dev
#   ./scripts/deploy.sh prod

set -e

ENVIRONMENT=${1:-dev}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_DIR/infrastructure"

echo "=========================================="
echo "AWS Cost Optimizer - Deployment"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo ""

# Check for required tools
command -v terraform >/dev/null 2>&1 || { echo "Error: terraform is required but not installed."; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "Error: aws cli is required but not installed."; exit 1; }

# Check AWS credentials
echo "Checking AWS credentials..."
aws sts get-caller-identity > /dev/null || { echo "Error: AWS credentials not configured."; exit 1; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region || echo "us-east-1")
echo "AWS Account: $ACCOUNT_ID"
echo "AWS Region: $REGION"
echo ""

# Navigate to infrastructure directory
cd "$INFRA_DIR"

# Check for terraform.tfvars
if [ ! -f "terraform.tfvars" ]; then
    echo "Warning: terraform.tfvars not found."
    echo "Creating from example..."
    cp terraform.tfvars.example terraform.tfvars
    echo "Please edit terraform.tfvars and re-run."
    exit 1
fi

# Initialize Terraform
echo "Initializing Terraform..."
terraform init -upgrade

# Validate configuration
echo "Validating configuration..."
terraform validate

# Plan deployment
echo ""
echo "Planning deployment..."
terraform plan -var="environment=$ENVIRONMENT" -out=tfplan

# Confirm deployment
echo ""
read -p "Deploy to AWS? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Apply deployment
echo ""
echo "Deploying..."
terraform apply tfplan

# Clean up plan file
rm -f tfplan

# Show outputs
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
terraform output

echo ""
echo "Next steps:"
echo "  1. Verify Lambda function in AWS Console"
echo "  2. Check CloudWatch dashboard for metrics"
echo "  3. Manually invoke to test:"
echo "     aws lambda invoke --function-name cost-optimizer-$ENVIRONMENT --payload '{}' response.json"
echo ""