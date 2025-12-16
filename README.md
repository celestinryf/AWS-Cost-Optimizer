# AWS Cost Optimizer

Automated S3 cost optimization tool that scans buckets, identifies savings opportunities, scores risk, and safely executes optimizations with rollback support.

## Features

### Phase 1: Scanner
Scans your AWS S3 buckets and identifies optimization opportunities:
- Objects that haven't been accessed in 90+ days (candidates for Glacier)
- Large objects in STANDARD storage that could use Intelligent-Tiering
- Buckets missing lifecycle policies
- Incomplete multipart uploads wasting storage
- Old object versions in versioned buckets

## Setup

### 1. Prerequisites
- Python 3.9+
- AWS account
- AWS CLI configured with credentials

### 2. Install dependencies
```bash
cd aws-cost-optimizer
pip install -r requirements.txt
```

### 3. Configure AWS credentials

Option A: Use AWS CLI (recommended)
```bash
aws configure
```

Option B: Environment variables
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-west-2
```

### 4. Create IAM Policy

Create an IAM user/role with this policy:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketLocation",
                "s3:GetBucketLifecycleConfiguration",
                "s3:ListBucket",
                "s3:GetObject",
                "s3:GetObjectTagging",
                "s3:ListBucketMultipartUploads",
                "s3:ListMultipartUploadParts",
                "s3:ListBucketVersions"
            ],
            "Resource": "*"
        }
    ]
}
```

### 5. Create test data (optional)

Run the test data generator to create sample buckets:
```bash
python scripts/create_test_data.py
```

### 6. Run the scanner
```bash
python main.py scan
```

Output will be saved to `reports/scan_results.json`

### Phase 2: Risk Scoring & Dry Run

After scanning, analyze the risk of each recommendation:

```bash
# Score recommendations by risk level
python main.py score

# Validate what would happen (without making changes)
python main.py dry-run

# Include high-risk items in validation
python main.py dry-run --include-high-risk

# Generate full report
python main.py report
```

#### Risk Levels

| Level | Description | Action |
|-------|-------------|--------|
| LOW | Safe, reversible changes | Auto-execute |
| MEDIUM | Review recommended | Batch with approval |
| HIGH | Data loss possible | Manual approval only |

#### Scoring Factors

- **Reversibility** (30%) - Can the action be undone?
- **Data Loss Risk** (25%) - Could data be permanently lost?
- **Age Confidence** (20%) - How old is the object?
- **Size Impact** (15%) - How large is the affected data?
- **Access Patterns** (10%) - Do we know usage patterns?

#### Savings Calculation

Accurate cost estimates including:
- Storage class pricing differences
- One-time transition costs
- Minimum storage duration fees
- Break-even analysis

## Project Structure
```
aws-cost-optimizer/
├── README.md
├── requirements.txt
├── main.py                 # CLI entry point
├── scanner.py              # S3 bucket scanner
├── config.py               # Configuration settings
│
├── analyzers/              # Phase 1: Detection
│   ├── storage_class.py    # Storage class analyzer
│   ├── access_patterns.py  # Stale object detection
│   ├── lifecycle.py        # Lifecycle policy analyzer
│   └── multipart.py        # Incomplete uploads
│
├── models/
│   └── recommendation.py   # Data models
│
├── scoring/                # Phase 2: Risk Analysis
│   ├── risk_scorer.py      # Risk assessment engine
│   └── savings_calculator.py
│
├── executor/               # Phase 3: Execution
│   ├── executor.py         # Main execution engine
│   ├── dry_run.py          # Dry-run validation
│   ├── validator.py        # Pre-execution checks
│   ├── state_tracker.py    # Audit trail
│   └── rollback.py         # Rollback manager
│
├── lambda_function/        # Phase 4: Automation
│   ├── README.md           # Lambda documentation
│   └── handler.py          # Lambda entry point
│
├── infrastructure/         # Terraform IaC
│   ├── main.tf             # AWS resources
│   └── terraform.tfvars.example
│
├── scripts/
│   ├── deploy.sh           # Deploy to AWS
│   ├── teardown.sh         # Remove from AWS
│   ├── test_lambda_local.py
│   ├── create_test_data.py
│   └── cleanup_test_data.py
│
└── reports/
    ├── scan_results.json
    ├── scored_results.json
    └── execution_state/
```

## Roadmap

- [x] Phase 1: Scanner - Identify optimization opportunities
- [x] Phase 2: Scoring - Risk analysis and dry-run validation
- [x] Phase 3: Executor - Safe execution with rollback
- [x] Phase 4: Automation - Scheduled runs via Lambda

## CLI Commands

```bash
# Full workflow
python main.py scan       # Step 1: Find optimizations
python main.py score      # Step 2: Analyze risk & savings
python main.py dry-run    # Step 3: Validate changes
python main.py execute    # Step 4: Apply optimizations
python main.py rollback   # Step 5: Revert if needed

# Or run scanner directly
python scanner.py
```

### Execute Options

```bash
# Safe mode (default) - only low-risk, auto-approved actions
python main.py execute --mode safe

# Standard mode - low and medium risk actions
python main.py execute --mode standard

# Full mode - all actions including high-risk (with confirmations)
python main.py execute --mode full

# Skip confirmation prompts
python main.py execute --mode standard --yes

# Dry run (simulate without changes)
python main.py execute --dry-run

# Stop after N failures
python main.py execute --max-failures 5
```

### Rollback Options

```bash
# List recent execution batches
python main.py rollback

# View batch details
python main.py rollback abc123

# Rollback a batch (with confirmation)
python main.py rollback abc123

# Rollback without confirmation
python main.py rollback abc123 --yes

# View execution history
python main.py history
```

## Execution Modes

| Mode | Risk Levels | Confirmation | Use Case |
|------|-------------|--------------|----------|
| `safe` | LOW only | No | Automated runs, cron jobs |
| `standard` | LOW + MEDIUM | Yes for medium | Regular maintenance |
| `full` | All | Yes for high | Manual review sessions |

## Rollback Support

| Action | Rollback Available | How |
|--------|-------------------|-----|
| Storage class change | ✅ Yes | Copy back to original class |
| Add lifecycle policy | ✅ Yes | Remove added rules |
| Abort multipart | ❌ No | Upload data already incomplete |
| Delete object | ❌ No | Data permanently removed |
| Delete version | ❌ No | Version permanently removed |

## Safety Features

- **Pre-execution validation** - Checks permissions and preconditions
- **State snapshots** - Captures object state before changes
- **Failure threshold** - Stops after N failures (default: 3)
- **Confirmation prompts** - For medium/high risk actions
- **Audit trail** - Full execution history with batch IDs
- **Rollback support** - Revert reversible changes

## Lambda Automation (Phase 4)

Run the optimizer automatically on a schedule using AWS Lambda.

### Quick Deploy

```bash
# 1. Configure
cd infrastructure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars

# 2. Deploy
cd ..
./scripts/deploy.sh dev

# 3. Test
aws lambda invoke --function-name cost-optimizer-dev --payload '{}' response.json
```

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `execution_mode` | `dry_run`, `safe`, `standard`, `full` | `dry_run` |
| `schedule_expression` | Cron/rate expression | `rate(1 day)` |
| `notification_email` | Email for alerts | `""` |
| `slack_webhook_url` | Slack notifications | `""` |

### Schedule Examples

```hcl
# Daily at 8 AM UTC
schedule_expression = "cron(0 8 * * ? *)"

# Weekly on Monday
schedule_expression = "cron(0 9 ? * MON *)"

# Every 7 days
schedule_expression = "rate(7 days)"
```

### Local Testing

```bash
# Test Lambda handler locally
python scripts/test_lambda_local.py --mode dry_run
```

### Teardown

```bash
./scripts/teardown.sh dev
```

See [lambda_function/README.md](lambda_function/README.md) for full documentation.