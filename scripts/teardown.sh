#!/bin/bash
# scripts/teardown.sh
# Remove cost optimizer infrastructure from AWS
#
# Usage:
#   ./scripts/teardown.sh [environment]
#
# Examples:
#   ./scripts/teardown.sh dev
#   ./scripts/teardown.sh prod

set -e

ENVIRONMENT=${1:-dev}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_DIR/infrastructure"

echo "=========================================="
echo "AWS Cost Optimizer - Teardown"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo ""

# Check for required tools
command -v terraform >/dev/null 2>&1 || { echo "Error: terraform is required but not installed."; exit 1; }

# Navigate to infrastructure directory
cd "$INFRA_DIR"

# Check if terraform state exists
if [ ! -f "terraform.tfstate" ] && [ ! -d ".terraform" ]; then
    echo "No Terraform state found. Nothing to destroy."
    exit 0
fi

# Show what will be destroyed
echo "Planning destruction..."
terraform plan -destroy -var="environment=$ENVIRONMENT"

# Confirm destruction
echo ""
echo "WARNING: This will permanently delete all resources!"
read -p "Are you sure you want to destroy all resources? (type 'yes' to confirm): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo "Teardown cancelled."
    exit 0
fi

# Destroy resources
echo ""
echo "Destroying resources..."
terraform destroy -var="environment=$ENVIRONMENT" -auto-approve

echo ""
echo "=========================================="
echo "Teardown Complete!"
echo "=========================================="