"""Backend state management for GCP - Cloud Storage buckets and Firestore for state locking"""

import pulumi
import pulumi_gcp as gcp
from pulumi import Config, Output


def deploy():
    """Deploy shared backend state infrastructure for GCP"""

    # Configuration
    config = Config()
    gcp_config = Config("gcp")

    # Get GCP project and region
    gcp_project = gcp_config.require("project")
    gcp_region = gcp_config.get("region") or "us-central1"

    # Environment configuration
    state_bucket_prefix = config.get("state_bucket_prefix_gcp") or "pytorch-ci-infra-state"

    # Create Cloud Storage bucket for Terraform/Pulumi state
    state_bucket = gcp.storage.Bucket(
        "backend-state-bucket",
        name=f"{state_bucket_prefix}-{gcp_project}",
        location=gcp_region,
        storage_class="STANDARD",
        uniform_bucket_level_access=True,
        versioning=gcp.storage.BucketVersioningArgs(
            enabled=True,
        ),
        lifecycle_rules=[
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="Delete",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    num_newer_versions=10,
                    with_state="ARCHIVED",
                ),
            ),
        ],
        labels={
            "environment": "shared",
            "purpose": "state-storage",
            "managed-by": "pulumi",
        },
        project=gcp_project,
    )

    # Create a separate bucket for state backups
    backup_bucket = gcp.storage.Bucket(
        "backend-state-backup-bucket",
        name=f"{state_bucket_prefix}-backup-{gcp_project}",
        location=gcp_region,
        storage_class="NEARLINE",
        uniform_bucket_level_access=True,
        versioning=gcp.storage.BucketVersioningArgs(
            enabled=True,
        ),
        lifecycle_rules=[
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="SetStorageClass",
                    storage_class="COLDLINE",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=30,
                ),
            ),
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="SetStorageClass",
                    storage_class="ARCHIVE",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=90,
                ),
            ),
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="Delete",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=365,
                ),
            ),
        ],
        labels={
            "environment": "shared",
            "purpose": "state-backup",
            "managed-by": "pulumi",
        },
        project=gcp_project,
    )

    # Enable Firestore API for state locking (equivalent to DynamoDB)
    firestore_api = gcp.projects.Service(
        "firestore-api",
        service="firestore.googleapis.com",
        project=gcp_project,
        disable_on_destroy=False,
    )

    # Create Firestore database for state locking
    # Note: Firestore in Native mode is created at the project level
    # and can only be created once per project
    firestore_database = gcp.firestore.Database(
        "state-lock-database",
        name="(default)",
        location_id=gcp_region,
        type="FIRESTORE_NATIVE",
        concurrency_mode="OPTIMISTIC",
        app_engine_integration_mode="DISABLED",
        project=gcp_project,
        opts=pulumi.ResourceOptions(depends_on=[firestore_api]),
    )

    # Create service account for state management
    state_management_sa = gcp.serviceaccount.Account(
        "state-management-sa",
        account_id="state-management",
        display_name="State Management Service Account",
        description="Service account for managing Terraform/Pulumi state",
        project=gcp_project,
    )

    # Grant permissions to the state management service account
    gcp.storage.BucketIAMMember(
        "state-bucket-admin",
        bucket=state_bucket.name,
        role="roles/storage.admin",
        member=Output.concat("serviceAccount:", state_management_sa.email),
    )

    gcp.storage.BucketIAMMember(
        "backup-bucket-admin",
        bucket=backup_bucket.name,
        role="roles/storage.admin",
        member=Output.concat("serviceAccount:", state_management_sa.email),
    )

    # Grant Firestore permissions for state locking
    gcp.projects.IAMMember(
        "firestore-admin",
        project=gcp_project,
        role="roles/datastore.user",
        member=Output.concat("serviceAccount:", state_management_sa.email),
    )

    # Create a Cloud Storage bucket for artifacts (similar to S3 artifacts bucket)
    artifacts_bucket = gcp.storage.Bucket(
        "artifacts-bucket",
        name=f"pytorch-ci-artifacts-{gcp_project}",
        location=gcp_region,
        storage_class="STANDARD",
        uniform_bucket_level_access=True,
        lifecycle_rules=[
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="Delete",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=30,
                ),
            ),
        ],
        labels={
            "environment": "shared",
            "purpose": "artifacts",
            "managed-by": "pulumi",
        },
        project=gcp_project,
    )

    # Create a Cloud Storage bucket for logs
    logs_bucket = gcp.storage.Bucket(
        "logs-bucket",
        name=f"pytorch-ci-logs-{gcp_project}",
        location=gcp_region,
        storage_class="STANDARD",
        uniform_bucket_level_access=True,
        lifecycle_rules=[
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="SetStorageClass",
                    storage_class="NEARLINE",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=7,
                ),
            ),
            gcp.storage.BucketLifecycleRuleArgs(
                action=gcp.storage.BucketLifecycleRuleActionArgs(
                    type="Delete",
                ),
                condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                    age=90,
                ),
            ),
        ],
        labels={
            "environment": "shared",
            "purpose": "logs",
            "managed-by": "pulumi",
        },
        project=gcp_project,
    )

    # Export outputs
    outputs = {
        "state_bucket_name": state_bucket.name,
        "state_bucket_url": state_bucket.url,
        "backup_bucket_name": backup_bucket.name,
        "backup_bucket_url": backup_bucket.url,
        "artifacts_bucket_name": artifacts_bucket.name,
        "artifacts_bucket_url": artifacts_bucket.url,
        "logs_bucket_name": logs_bucket.name,
        "logs_bucket_url": logs_bucket.url,
        "firestore_database_name": firestore_database.name,
        "state_management_sa_email": state_management_sa.email,
        "gcp_project": gcp_project,
        "gcp_region": gcp_region,
    }

    # Export to Pulumi stack outputs
    for key, value in outputs.items():
        pulumi.export(f"shared_gcp_{key}", value)

    return outputs
