# Context and Strategy Notes

This document captures architecture and roadmap decisions discussed for future execution.

## Current Scope (Why Terraform is not required today)

The current project is primarily:
- Application code: Python/FastAPI backend, React frontend, Tauri desktop shell.
- CI/CD pipelines in GitHub Actions.
- Runtime AWS API calls through `boto3` against existing AWS resources.

Conclusion:
- Terraform is optional for the current app-first/local-desktop scope.
- Terraform becomes valuable when we need repeatable cloud environments and managed infrastructure lifecycle.

## What "Provision S3 Buckets" Means

Provisioning means creating and configuring buckets via code (not manual console clicks), including:
- Bucket creation.
- Versioning.
- Encryption defaults.
- Public access blocks.
- Lifecycle rules.
- Bucket policies and IAM access controls.
- Tags (`env`, `owner`, `cost-center`).

Result:
- Consistent environments across dev/stage/prod.
- Better auditability and reproducibility.

## When Terraform Becomes High-Value for This Project

Potential Terraform use cases:
- Define/manage least-privilege IAM roles and policies for optimizer actions.
- Provision S3 buckets, lifecycle policies, and isolated test environments.
- Deploy backend to Lambda or ECS with API Gateway or ALB.
- Schedule scans with EventBridge.
- Manage app secrets in Secrets Manager or SSM Parameter Store.
- Configure CloudWatch logs/alarms and SNS notifications.
- Standardize dev/stage/prod environments.

## CI/CD and IaC Positioning

- We do have CI/CD (tests, coverage, desktop builds, release workflows in GitHub Actions).
- GitHub workflow files are pipeline-as-code.
- Full Infrastructure as Code should be claimed when infrastructure resources are declared and managed by tools like Terraform/CloudFormation/CDK.

## Multi-Cloud Expansion Feasibility (AWS, Azure, GCP, Oracle)

This is feasible, but should be phased as an architecture change, not a quick patch.

Recommended design:
- Define a provider interface: `scan`, `score`, `execute`, `rollback`.
- Keep current implementation as `AwsProvider`.
- Add providers incrementally (`GcpProvider`, `AzureProvider`, then `OracleProvider`).
- Normalize provider output into one shared recommendation model so UI and workflow remain stable.
- Implement provider-specific authentication and permission guardrails:
  IAM (AWS), RBAC (Azure), service accounts (GCP), OCI policies (Oracle).

Practical priority:
- AWS + GCP + Azure is straightforward relative to Oracle.
- Oracle is possible but typically higher integration effort.

## Long-Term Scale Direction (System-Level vs Control Plane)

For long-term, multi-account, multi-cloud scale:
- Do not rely on desktop app as the primary execution engine.
- Use a centralized control plane backend (multi-tenant API, scheduler, workers, queue, durable DB).
- Keep the desktop app as an operator client/UI.

Why:
- Desktop execution is harder to operate continuously and govern centrally.
- Enterprise usage requires stronger auditability, RBAC, and policy control.
- Multi-cloud credential rotation and background execution are safer in managed backend services.

## Recommended Future Sequence

1. Keep desktop as primary UX while hardening server-side APIs.
2. Introduce provider abstraction in backend.
3. Add GCP provider first, then Azure, then Oracle.
4. Introduce Terraform when production environment provisioning is required.
5. Move scheduled scans/execution from desktop runtime to backend workers.

## Package Distribution Status (Homebrew)

Current status:
- Homebrew install is not publicly available yet.
- Users cannot run `brew install --cask aws-cost-optimizer` until a cask is published in a tap.

What is already implemented:
- Release automation can generate a Homebrew cask file from release assets:
  - `scripts/update_homebrew_cask.sh --tag vX.Y.Z`

What is still required to go public:
1. Create and push a release tag (`vX.Y.Z`) so macOS DMG assets exist.
2. Publish `packaging/homebrew/Casks/aws-cost-optimizer.rb` to a Homebrew tap repo
   (for example: `celestinryf/homebrew-tap`).
3. End users then install with:
   - `brew tap celestinryf/tap`
   - `brew install --cask aws-cost-optimizer`

Local validation flow:
- Generate cask:
  - `bash scripts/update_homebrew_cask.sh --tag vX.Y.Z`
- Install locally from file:
  - `brew install --cask ./packaging/homebrew/Casks/aws-cost-optimizer.rb`
