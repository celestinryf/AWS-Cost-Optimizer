#!/usr/bin/env python3
"""
Create test S3 buckets and objects for testing the cost optimizer.

WARNING: This will create real AWS resources that may incur charges.
Run cleanup_test_data.py when done testing.
"""

import io
import random
import string
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


def random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def create_bucket_in_region(s3, bucket_name: str, region: str):
    """Create a bucket with proper region handling."""
    if region == "us-east-1":
        # us-east-1 doesn't use LocationConstraint
        s3.create_bucket(Bucket=bucket_name)
    else:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": region}
        )


def create_test_data():
    """Create test buckets and objects."""
    session = boto3.session.Session()
    region = session.region_name or "us-west-2"
    s3 = boto3.client("s3", region_name=region)
    
    print(f"Using region: {region}")
    
    # Generate unique bucket prefix
    prefix = f"cost-optimizer-test-{random_string(6)}"
    
    print(f"Creating test data with prefix: {prefix}")
    print("=" * 50)
    
    buckets_created = []
    
    try:
        # Bucket 1: Old objects in STANDARD (should recommend Glacier)
        bucket1 = f"{prefix}-old-objects"
        print(f"\n1. Creating bucket: {bucket1}")
        
        try:
            create_bucket_in_region(s3, bucket1, region)
        except ClientError as e:
            if "BucketAlreadyOwnedByYou" not in str(e):
                raise
        
        buckets_created.append(bucket1)
        
        # Add some "old" objects (we can't fake LastModified, but we can create objects)
        for i in range(20):
            size = random.randint(1024 * 1024, 10 * 1024 * 1024)  # 1-10 MB
            content = b"x" * size
            key = f"data/archive/file_{i:03d}.dat"
            s3.put_object(Bucket=bucket1, Key=key, Body=content)
            print(f"   Created: {key} ({size / (1024*1024):.1f} MB)")
        
        # Bucket 2: No lifecycle policy (should recommend adding one)
        bucket2 = f"{prefix}-no-lifecycle"
        print(f"\n2. Creating bucket: {bucket2}")
        
        try:
            create_bucket_in_region(s3, bucket2, region)
        except ClientError as e:
            if "BucketAlreadyOwnedByYou" not in str(e):
                raise
        
        buckets_created.append(bucket2)
        
        # Add some objects
        for i in range(50):
            size = random.randint(100 * 1024, 5 * 1024 * 1024)  # 100KB - 5MB
            content = b"y" * size
            key = f"uploads/document_{i:03d}.pdf"
            s3.put_object(Bucket=bucket2, Key=key, Body=content)
            print(f"   Created: {key} ({size / (1024*1024):.2f} MB)")
        
        # Bucket 3: With lifecycle policy (for comparison)
        bucket3 = f"{prefix}-with-lifecycle"
        print(f"\n3. Creating bucket: {bucket3}")
        
        try:
            create_bucket_in_region(s3, bucket3, region)
        except ClientError as e:
            if "BucketAlreadyOwnedByYou" not in str(e):
                raise
        
        buckets_created.append(bucket3)
        
        # Add lifecycle policy
        lifecycle_config = {
            "Rules": [
                {
                    "ID": "MoveToGlacier",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Transitions": [
                        {
                            "Days": 90,
                            "StorageClass": "GLACIER"
                        }
                    ],
                    "AbortIncompleteMultipartUpload": {
                        "DaysAfterInitiation": 7
                    }
                }
            ]
        }
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket3, 
            LifecycleConfiguration=lifecycle_config
        )
        print("   Added lifecycle policy")
        
        # Add some objects
        for i in range(10):
            size = random.randint(1024, 1024 * 1024)
            content = b"z" * size
            key = f"data/file_{i:03d}.txt"
            s3.put_object(Bucket=bucket3, Key=key, Body=content)
            print(f"   Created: {key}")
        
        # Bucket 4: With incomplete multipart upload
        bucket4 = f"{prefix}-multipart"
        print(f"\n4. Creating bucket: {bucket4}")
        
        try:
            create_bucket_in_region(s3, bucket4, region)
        except ClientError as e:
            if "BucketAlreadyOwnedByYou" not in str(e):
                raise
        
        buckets_created.append(bucket4)
        
        # Start a multipart upload but don't complete it
        mpu = s3.create_multipart_upload(
            Bucket=bucket4, 
            Key="large_upload_incomplete.zip"
        )
        upload_id = mpu["UploadId"]
        
        # Upload one part
        s3.upload_part(
            Bucket=bucket4,
            Key="large_upload_incomplete.zip",
            UploadId=upload_id,
            PartNumber=1,
            Body=b"x" * (5 * 1024 * 1024)  # 5 MB
        )
        print(f"   Created incomplete multipart upload: {upload_id[:8]}...")
        
        print("\n" + "=" * 50)
        print("Test data created successfully!")
        print(f"\nBuckets created: {len(buckets_created)}")
        for b in buckets_created:
            print(f"  - {b}")
        
        print("\nTo clean up, run:")
        print(f"  python scripts/cleanup_test_data.py {prefix}")
        
        # Save prefix for cleanup
        with open("reports/test_prefix.txt", "w") as f:
            f.write(prefix)
        
        return buckets_created
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        print("\nCleaning up created buckets...")
        for bucket in buckets_created:
            try:
                # Delete all objects first
                paginator = s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=bucket):
                    for obj in page.get("Contents", []):
                        s3.delete_object(Bucket=bucket, Key=obj["Key"])
                
                # Abort multipart uploads
                mpu_response = s3.list_multipart_uploads(Bucket=bucket)
                for upload in mpu_response.get("Uploads", []):
                    s3.abort_multipart_upload(
                        Bucket=bucket,
                        Key=upload["Key"],
                        UploadId=upload["UploadId"]
                    )
                
                s3.delete_bucket(Bucket=bucket)
                print(f"  Deleted: {bucket}")
            except Exception as cleanup_error:
                print(f"  Failed to delete {bucket}: {cleanup_error}")
        
        sys.exit(1)


if __name__ == "__main__":
    create_test_data()