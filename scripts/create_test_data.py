import boto3
import random
import string
from datetime import datetime

BUCKET_NAME = "cost-optimizer-test"
REGION = "us-west-2"

def random_string(length = 10):
    return ''.join(random.choices(string.ascii_lowercase, k = length))

def create_bucket(s3_client):
    """Create the test bucket if it doesn't exist"""
    try:
        if REGION == "us-east-1":
            s3_client.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3_client.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )

        print(f"Created Bucket: {BUCKET_NAME}")

    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print(f"Bucket Already Exists: {BUCKET_NAME}")
    except Exception as e:
        print(f"Error creating bucket: {e}")
        raise

def create_old_large_files(s3_client):
    """Create old, large files that should recommend GLacier transition"""
    print("\nCreating old large files (should recommend Glacier)...")

    files = [
        ("archive/quarterly-report-2022-q1.csv", 15),
        ("archive/quarterly-report-2022-q2.csv", 12),
        ("archive/backup-jan-2023.tar.gz", 50),
        ("archive/legacy-data-export.json", 25),
        ("data/old-analytics-2022.parquet", 30),
    ]

    for key, size_mb in files:
        body = b"x" * (size_mb * 1024 * 1024)
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=body,
            Metadata={"Created": "2022-06-15"}
        )
        print(f"Created {key} ({size_mb} MB)")

def create_small_log_files(s3_client):
    """Create many small log files that should recommend lifecycle policy."""
    print("\nCreating small log files (should recommend lifecycle policy)...")

    for month in range(1, 13):
        for day in [1, 15]:
            key = f"logs/2023/{month:02d}/app-log-{day:02d}.log"
            body = f"Log entry for 2023-{month:02d}-{day:02d}\n" * 100
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=key,
                Body=body.encode()
            )

    print(f"Created 24 log files in logs/2023/")

def create_incomplete_multipart_uploads(s3_client):
    """Create incomplete multipart uploads that should be cleaned up."""
    print("\nCreating incomplete multipart uploads (should recommend abort)...")

    uploads = [
        "uploads/failed-video-upload.mp4",
        "uploads/incomplete-backup.tar.gz",
        "uploads/abandoned-dataset.csv",
    ]

    for key in uploads:
        response = s3_client.create_multipart_upload(
            Bucket=BUCKET_NAME,
            Key=key
        )
        print(f"Created incomplete upload: {key} (ID: {response['UploadId'][:8]}...)")

def create_standard_recent_files(s3_client):
    """Create recent files that should NOT generate recommendations."""
    print("\nCreating recent files (should NOT generate recommendations)...")

    files = [
        "current/active-config.json",
        "current/latest-report.pdf",
        "current/user-data.csv",
    ]

    for key in files:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=b"This is recent, active data should not be moved."
        )
        print(f"Created {key} (recent, should keep)")

def print_summary(s3_client):
    """Print summary of what was created."""
    print("\n" + "=" * 50)
    print("TEST DATA SUMMARY")
    print("=" * 50)

    # Count objects
    response = s3_client.list_objects_v2(Bucket=BUCKET_NAME)
    objects = response.get("Contents", [])

    total_size = sum(obj["Size"] for obj in objects)

    print(f"Bicket: {BUCKET_NAME}")
    print(f"Total objects: {len(objects)}")
    print(f"Total size: {total_size / (1024*1024):.2f} MB")

    mp_response = s3_client.list_multipart_uploads(Bucket=BUCKET_NAME)
    uploads = mp_response.get("Uploads", [])
    print(f"Incomplete multipart uploads: {len(uploads)}")

    print("\n Expected recommendations:")
    print(" - 5 storage class changes (old large files -> Glacier)")
    print(" - 1 lifecycle policy (for logs/ prefix)")
    print(" - 3 multipart upload cleanups")
    print("=" * 50)

def main():
    print("=" * 50)
    print("S3 COST OPTIMZER - TEST DATA SETUP")
    print("=" * 50)

    # Create S3 Client
    s3_client = boto3.client("s3", region_name=REGION)

    # Create test data
    create_bucket(s3_client)
    create_old_large_files(s3_client)
    create_small_log_files(s3_client)
    create_incomplete_multipart_uploads(s3_client)
    create_standard_recent_files(s3_client)

    # Print summary
    print_summary(s3_client)

    print("\nTest data created successfully!")
    print(f"\nNext step: Run the scanner against bucket '{BUCKET_NAME}'")

if __name__ == "__main__":
    main()