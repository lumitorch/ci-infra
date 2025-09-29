"""Backend state management resources for Pulumi state storage"""

import pulumi
from pulumi import Config
import pulumi_aws as aws


def create_backend_state(
    project: str,
    environment: str,
    bucket_state_name: str = "tfstate",
    dynamo_table_name: str = "tfstate-lock"
) -> dict:
    """
    Create S3 bucket and DynamoDB table for Terraform/Pulumi state management.
    
    Args:
        project: Name of the project
        environment: Name of the environment (dev, staging, prod)
        bucket_state_name: Base name for the state bucket
        dynamo_table_name: Name for the DynamoDB lock table
    
    Returns:
        Dictionary containing the created resources
    """
    
    # Create bucket name following the same pattern as Terraform
    bucket_name = f"{bucket_state_name}-{project}-{environment}"
    
    # Create S3 bucket for state storage
    state_bucket = aws.s3.Bucket(
        "terraform-state-bucket",
        bucket=bucket_name,
        lifecycle_rules=[{
            "enabled": True,
            "noncurrent_version_expiration": {
                "days": 90
            }
        }],
        versioning={
            "enabled": True
        },
        server_side_encryption_configuration={
            "rule": {
                "apply_server_side_encryption_by_default": {
                    "sse_algorithm": "AES256"
                }
            }
        },
        tags={
            "Name": bucket_name,
            "Project": project,
            "Environment": environment,
            "Purpose": "State Storage"
        },
        opts=pulumi.ResourceOptions(
            protect=True  # Prevent accidental deletion
        )
    )
    
    # Block public access to the state bucket
    bucket_public_access_block = aws.s3.BucketPublicAccessBlock(
        "terraform-state-bucket-pab",
        bucket=state_bucket.id,
        block_public_acls=True,
        block_public_policy=True,
        ignore_public_acls=True,
        restrict_public_buckets=True
    )
    
    # Create DynamoDB table for state locking
    lock_table = aws.dynamodb.Table(
        "terraform-state-lock-table",
        name=f"{dynamo_table_name}-{project}-{environment}",
        billing_mode="PAY_PER_REQUEST",
        hash_key="LockID",
        attributes=[{
            "name": "LockID",
            "type": "S"
        }],
        tags={
            "Name": f"{dynamo_table_name}-{project}-{environment}",
            "Project": project,
            "Environment": environment,
            "Purpose": "State Locking"
        },
        opts=pulumi.ResourceOptions(
            protect=True  # Prevent accidental deletion
        )
    )
    
    return {
        "state_bucket": state_bucket,
        "bucket_public_access_block": bucket_public_access_block,
        "lock_table": lock_table,
        "bucket_name": bucket_name,
        "table_name": lock_table.name
    }