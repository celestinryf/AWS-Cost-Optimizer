# AWS Cost Optimizer

Automated S3 cost optimization tool that scans buckets, identifies savings opportunities, and safely executes optimizations with rollback support.

## Phase 1: Scanner

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
python scanner.py
```

Output will be saved to `reports/scan_results.json`

## Project Structure
```
aws-cost-optimizer/
├── README.md
├── requirements.txt
├── scanner.py              # Main scanner script
├── config.py               # Configuration settings
├── analyzers/
│   ├── __init__.py
│   ├── storage_class.py    # Storage class analyzer
│   ├── access_patterns.py  # Last accessed analyzer
│   ├── lifecycle.py        # Lifecycle policy analyzer
│   └── multipart.py        # Incomplete uploads analyzer
├── models/
│   ├── __init__.py
│   └── recommendation.py   # Recommendation data model
├── scripts/
│   └── create_test_data.py # Generate test S3 data
└── reports/
    └── .gitkeep
```