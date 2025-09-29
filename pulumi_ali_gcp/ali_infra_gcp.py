"""ALI Infrastructure for GCP - VPC, Cloud Functions autoscaler, and IAM policies"""


import pulumi
import pulumi_gcp as gcp
from pulumi import Config, Output


def deploy():
    """Deploy ALI infrastructure for GCP including VPCs, Cloud Functions autoscaler, and IAM policies"""

    # Configuration
    config = Config()
    gcp_config = Config("gcp")

    # Get GCP project and region
    gcp_project = gcp_config.require("project")
    gcp_region = gcp_config.get("region") or "us-central1"

    # Environment configuration
    ali_prod_environment = config.get("ali_prod_environment_gcp") or "ghci-lf-gcp"
    ali_canary_environment = config.get("ali_canary_environment_gcp") or "ghci-lf-c-gcp"

    # VPC configuration
    gcp_vpc_suffixes = config.get_object("gcp_vpc_suffixes") or ["I", "II"]
    gcp_canary_vpc_suffixes = config.get_object("gcp_canary_vpc_suffixes") or ["I"]

    # Create production VPCs
    prod_vpcs = {}
    prod_subnets = {}
    for idx, suffix in enumerate(gcp_vpc_suffixes):
        vpc = gcp.compute.Network(
            f"ali-runners-vpc-{suffix}",
            name=f"{ali_prod_environment}-{suffix}",
            auto_create_subnetworks=False,
            description=f"VPC network for {ali_prod_environment}-{suffix}",
            project=gcp_project,
        )
        prod_vpcs[suffix] = vpc

        # Create subnet for each VPC
        subnet = gcp.compute.Subnetwork(
            f"ali-runners-subnet-{suffix}",
            name=f"{ali_prod_environment}-{suffix}-subnet",
            network=vpc.id,
            ip_cidr_range=f"10.{idx}.0.0/16",
            region=gcp_region,
            private_ip_google_access=True,
            project=gcp_project,
        )
        prod_subnets[suffix] = subnet

        # Create Cloud Router for NAT
        router = gcp.compute.Router(
            f"ali-router-{suffix}",
            name=f"{ali_prod_environment}-{suffix}-router",
            network=vpc.id,
            region=gcp_region,
            project=gcp_project,
        )

        # Create Cloud NAT for outbound internet access
        gcp.compute.RouterNat(
            f"ali-nat-{suffix}",
            name=f"{ali_prod_environment}-{suffix}-nat",
            router=router.name,
            region=gcp_region,
            nat_ip_allocate_option="AUTO_ONLY",
            source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
            project=gcp_project,
        )

    # Create VPC peering connections between production VPCs
    if len(gcp_vpc_suffixes) > 1:
        gcp.compute.NetworkPeering(
            "ali-vpc-peering-1",
            name=f"{ali_prod_environment}-peering-1-to-2",
            network=prod_vpcs[gcp_vpc_suffixes[0]].self_link,
            peer_network=prod_vpcs[gcp_vpc_suffixes[1]].self_link,
            export_custom_routes=True,
            import_custom_routes=True,
        )

        gcp.compute.NetworkPeering(
            "ali-vpc-peering-2",
            name=f"{ali_prod_environment}-peering-2-to-1",
            network=prod_vpcs[gcp_vpc_suffixes[1]].self_link,
            peer_network=prod_vpcs[gcp_vpc_suffixes[0]].self_link,
            export_custom_routes=True,
            import_custom_routes=True,
        )

    # Create canary VPC
    canary_vpc = None
    canary_subnet = None
    if gcp_canary_vpc_suffixes:
        suffix = gcp_canary_vpc_suffixes[0]
        idx = gcp_vpc_suffixes.index(suffix) if suffix in gcp_vpc_suffixes else 0
        canary_vpc = gcp.compute.Network(
            f"ali-runners-canary-vpc-{suffix}",
            name=f"{ali_canary_environment}-{suffix}",
            auto_create_subnetworks=False,
            description=f"VPC network for {ali_canary_environment}-{suffix}",
            project=gcp_project,
        )

        canary_subnet = gcp.compute.Subnetwork(
            f"ali-runners-canary-subnet-{suffix}",
            name=f"{ali_canary_environment}-{suffix}-subnet",
            network=canary_vpc.id,
            ip_cidr_range=f"10.{idx}.0.0/16",
            region=gcp_region,
            private_ip_google_access=True,
            project=gcp_project,
        )

        # Create Cloud Router and NAT for canary
        canary_router = gcp.compute.Router(
            f"ali-canary-router-{suffix}",
            name=f"{ali_canary_environment}-{suffix}-router",
            network=canary_vpc.id,
            region=gcp_region,
            project=gcp_project,
        )

        gcp.compute.RouterNat(
            f"ali-canary-nat-{suffix}",
            name=f"{ali_canary_environment}-{suffix}-nat",
            router=canary_router.name,
            region=gcp_region,
            nat_ip_allocate_option="AUTO_ONLY",
            source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
            project=gcp_project,
        )

    # Create service account for GitHub Actions with Workload Identity Federation
    github_actions_sa = gcp.serviceaccount.Account(
        "ossci-gha-terraform",
        account_id="ossci-gha-terraform",
        display_name="GitHub Actions Terraform Service Account",
        description="Used by pytorch/ci-infra workflows to deploy infrastructure",
        project=gcp_project,
    )

    # Create Workload Identity Pool for GitHub Actions
    workload_identity_pool = gcp.iam.WorkloadIdentityPool(
        "github-actions-pool",
        workload_identity_pool_id="github-actions",
        display_name="GitHub Actions",
        description="Workload Identity Pool for GitHub Actions",
        project=gcp_project,
    )

    # Create Workload Identity Provider for GitHub
    workload_identity_provider = gcp.iam.WorkloadIdentityPoolProvider(
        "github-actions-provider",
        workload_identity_pool_id=workload_identity_pool.workload_identity_pool_id,
        workload_identity_pool_provider_id="github",
        display_name="GitHub",
        description="GitHub OIDC provider",
        attribute_mapping={
            "google.subject": "assertion.sub",
            "attribute.actor": "assertion.actor",
            "attribute.repository": "assertion.repository",
            "attribute.repository_owner": "assertion.repository_owner",
        },
        attribute_condition='assertion.repository_owner == "pytorch"',
        oidc=gcp.iam.WorkloadIdentityPoolProviderOidcArgs(
            issuer_uri="https://token.actions.githubusercontent.com",
        ),
        project=gcp_project,
    )

    # Grant the GitHub Actions service account necessary permissions
    github_sa_roles = [
        "roles/compute.admin",
        "roles/iam.serviceAccountUser",
        "roles/storage.admin",
        "roles/cloudfunctions.admin",
    ]

    for idx, role in enumerate(github_sa_roles):
        gcp.projects.IAMMember(
            f"github-actions-sa-{idx}",
            project=gcp_project,
            role=role,
            member=Output.concat("serviceAccount:", github_actions_sa.email),
        )

    # Allow GitHub Actions to impersonate the service account
    gcp.serviceaccount.IAMBinding(
        "github-actions-sa-binding",
        service_account_id=github_actions_sa.name,
        role="roles/iam.workloadIdentityUser",
        members=[
            Output.concat(
                "principalSet://iam.googleapis.com/",
                workload_identity_pool.name,
                "/attribute.repository/pytorch/ci-infra"
            ),
        ],
    )

    # Create service account for Cloud Functions autoscaler
    autoscaler_sa = gcp.serviceaccount.Account(
        "ali-autoscaler-sa",
        account_id=f"{ali_prod_environment}-autoscaler",
        display_name=f"Autoscaler service account for {ali_prod_environment}",
        project=gcp_project,
    )

    # Grant autoscaler permissions
    autoscaler_roles = [
        "roles/compute.instanceAdmin.v1",
        "roles/iam.serviceAccountUser",
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
    ]

    for idx, role in enumerate(autoscaler_roles):
        gcp.projects.IAMMember(
            f"autoscaler-sa-{idx}",
            project=gcp_project,
            role=role,
            member=Output.concat("serviceAccount:", autoscaler_sa.email),
        )

    # Create IAM policy for Artifact Registry access (equivalent to ECR)
    artifact_registry_sa = gcp.serviceaccount.Account(
        "artifact-registry-sa",
        account_id=f"{ali_prod_environment}-artifact-registry",
        display_name=f"Artifact Registry access for {ali_prod_environment}",
        project=gcp_project,
    )

    # Grant Artifact Registry permissions
    gcp.projects.IAMMember(
        "artifact-registry-reader",
        project=gcp_project,
        role="roles/artifactregistry.reader",
        member=Output.concat("serviceAccount:", artifact_registry_sa.email),
    )

    # Create IAM policy for Cloud Storage access (equivalent to S3 for sccache)
    storage_sa = gcp.serviceaccount.Account(
        "storage-sccache-sa",
        account_id=f"{ali_prod_environment}-storage-sccache",
        display_name=f"Cloud Storage access for sccache in {ali_prod_environment}",
        project=gcp_project,
    )

    # Create storage bucket for sccache
    sccache_bucket = gcp.storage.Bucket(
        "ossci-compiler-cache",
        name=f"ossci-compiler-cache-{gcp_project}",
        location=gcp_region,
        uniform_bucket_level_access=True,
        project=gcp_project,
    )

    # Grant storage permissions
    gcp.storage.BucketIAMMember(
        "sccache-bucket-iam",
        bucket=sccache_bucket.name,
        role="roles/storage.objectAdmin",
        member=Output.concat("serviceAccount:", storage_sa.email),
    )

    # Create IAM policy for Cloud Functions access (equivalent to Lambda)
    functions_sa = gcp.serviceaccount.Account(
        "cloud-functions-sa",
        account_id=f"{ali_prod_environment}-cloud-functions",
        display_name=f"Cloud Functions access for {ali_prod_environment}",
        project=gcp_project,
    )

    # Grant Cloud Functions permissions
    functions_roles = [
        "roles/cloudfunctions.invoker",
        "roles/cloudfunctions.viewer",
    ]

    for idx, role in enumerate(functions_roles):
        gcp.projects.IAMMember(
            f"functions-sa-{idx}",
            project=gcp_project,
            role=role,
            member=Output.concat("serviceAccount:", functions_sa.email),
        )

    # Note: The actual Cloud Functions autoscaler would be implemented here
    # For this migration, we're creating the structure but not implementing
    # the full autoscaler logic which would require additional code

    # Export outputs
    outputs = {
        "prod_vpcs": prod_vpcs,
        "prod_subnets": prod_subnets,
        "canary_vpc": canary_vpc,
        "canary_subnet": canary_subnet,
        "github_actions_sa_email": github_actions_sa.email,
        "workload_identity_pool": workload_identity_pool.name,
        "workload_identity_provider": workload_identity_provider.name,
        "autoscaler_sa_email": autoscaler_sa.email,
        "artifact_registry_sa_email": artifact_registry_sa.email,
        "storage_sa_email": storage_sa.email,
        "functions_sa_email": functions_sa.email,
        "sccache_bucket": sccache_bucket.name,
        "gcp_project": gcp_project,
        "gcp_region": gcp_region,
        "ali_prod_environment": ali_prod_environment,
        "ali_canary_environment": ali_canary_environment,
    }

    # Export to Pulumi stack outputs
    for key, value in outputs.items():
        if key in ["prod_vpcs", "prod_subnets"]:
            # Export dictionary items individually
            for suffix, resource in value.items():
                pulumi.export(f"ali_gcp_{key}_{suffix}", resource)
        else:
            pulumi.export(f"ali_gcp_{key}", value)

    return outputs
