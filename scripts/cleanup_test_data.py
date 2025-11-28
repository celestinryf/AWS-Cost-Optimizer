#!/usr/bin/env python3
"""
Clean up test S3 buckets created by create_test_data.py
"""

import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def cleanup_test_data(prefix: str):
    """Delete all test buckets with the given prefix."""
    s3 = boto3.client("s3")
    
    print(f"Cleaning up buckets with prefix: {prefix}")
    print("=" * 50)
    
    # List all buckets
    response = s3.list_buckets()
    buckets_to_delete = [
        b["Name"] for b in response["Buckets"] 
        if b["Name"].startswith(prefix)
    ]
    
    if not buckets_to_delete:
        print("No matching buckets found.")
        return
    
    print(f"Found {len(buckets_to_delete)} buckets to delete:\n")
    
    for bucket in buckets_to_delete:
        print(f"Deleting: {bucket}")
        
        try:
            # Delete all objects
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    print(f"  Deleted object: {obj['Key']}")
            
            # Delete all versions (for versioned buckets)
            try:
                paginator = s3.get_paginator("list_object_versions")
                for page in paginator.paginate(Bucket=bucket):
                    for version in page.get("Versions", []):
                        s3.delete_object(
                            Bucket=bucket, 
                            Key=version["Key"],
                            VersionId=version["VersionId"]
                        )
                    for marker in page.get("DeleteMarkers", []):
                        s3.delete_object(
                            Bucket=bucket,
                            Key=marker["Key"],
                            VersionId=marker["VersionId"]
                        )
            except ClientError:
                pass  # Bucket might not be versioned
            
            # Abort incomplete multipart uploads
            mpu_response = s3.list_multipart_uploads(Bucket=bucket)
            for upload in mpu_response.get("Uploads", []):
                s3.abort_multipart_upload(
                    Bucket=bucket,
                    Key=upload["Key"],
                    UploadId=upload["UploadId"]
                )
                print(f"  Aborted multipart upload: {upload['Key']}")
            
            # Delete the bucket
            s3.delete_bucket(Bucket=bucket)
            print(f"  ✓ Bucket deleted\n")
            
        except ClientError as e:
            print(f"  ✗ Error: {e}\n")
    
    print("=" * 50)
    print("Cleanup complete!")


def main():
    if len(sys.argv) > 1:
        prefix = sys.argv[1]
    else:
        # Try to read from saved prefix file
        prefix_file = Path("reports/test_prefix.txt")
        if prefix_file.exists():
            prefix = prefix_file.read_text().strip()
            print(f"Using saved prefix: {prefix}\n")
        else:
            print("Usage: python scripts/cleanup_test_data.py <prefix>")
            print("\nOr run after create_test_data.py to use saved prefix.")
            sys.exit(1)
    
    cleanup_test_data(prefix)


if __name__ == "__main__":
    main()