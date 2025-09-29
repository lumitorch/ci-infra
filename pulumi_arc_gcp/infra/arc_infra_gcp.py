"""ARC Infrastructure Layer for GCP - VPC, GKE Cluster, and IAM Roles"""

import json

import pulumi
import pulumi_gcp as gcp
from pulumi import Config, Output


def deploy():
    """Deploy ARC infrastructure layer for GCP"""

    # Configuration
    config = Config()
    gcp_config = Config("gcp")

    # Get GCP project and region
    gcp_project = gcp_config.require("project")
    gcp_region = gcp_config.get("region") or "us-central1"

    # Environment configuration
    arc_prod_environment = config.get("arc_prod_environment_gcp") or "lf-arc-prod-gcp"

    # Availability zones (GCP uses zones like us-central1-a, us-central1-b, us-central1-c)
    [f"{gcp_region}-{loc}" for loc in ["a", "b", "c"]]

    # Create VPC network for ARC runners
    vpc_network = gcp.compute.Network(
        "arc-runners-vpc",
        name=arc_prod_environment,
        auto_create_subnetworks=False,
        description=f"VPC network for {arc_prod_environment}",
        project=gcp_project,
    )

    # Create subnetwork with secondary ranges for GKE
    subnetwork = gcp.compute.Subnetwork(
        "arc-runners-subnet",
        name=f"{arc_prod_environment}-subnet",
        network=vpc_network.id,
        ip_cidr_range="10.0.0.0/20",
        region=gcp_region,
        private_ip_google_access=True,
        secondary_ip_ranges=[
            gcp.compute.SubnetworkSecondaryIpRangeArgs(
                range_name="pods",
                ip_cidr_range="10.4.0.0/14",
            ),
            gcp.compute.SubnetworkSecondaryIpRangeArgs(
                range_name="services",
                ip_cidr_range="10.8.0.0/20",
            ),
        ],
        project=gcp_project,
    )

    # Create Cloud Router for NAT
    router = gcp.compute.Router(
        "arc-cloud-router",
        name=f"{arc_prod_environment}-router",
        network=vpc_network.id,
        region=gcp_region,
        project=gcp_project,
    )

    # Create Cloud NAT for outbound internet access
    gcp.compute.RouterNat(
        "arc-cloud-nat",
        name=f"{arc_prod_environment}-nat",
        router=router.name,
        region=gcp_region,
        nat_ip_allocate_option="AUTO_ONLY",
        source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
        project=gcp_project,
    )

    # Create service account for GKE nodes
    gke_node_sa = gcp.serviceaccount.Account(
        "gke-node-sa",
        account_id=f"{arc_prod_environment}-gke-node",
        display_name=f"GKE node service account for {arc_prod_environment}",
        project=gcp_project,
    )

    # Grant necessary permissions to GKE node service account
    node_sa_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/monitoring.viewer",
        "roles/artifactregistry.reader",
    ]

    for idx, role in enumerate(node_sa_roles):
        gcp.projects.IAMMember(
            f"gke-node-sa-{idx}",
            project=gcp_project,
            role=role,
            member=Output.concat("serviceAccount:", gke_node_sa.email),
        )

    # Create service account for PyTorch CI admins
    pytorch_ci_admins_sa = gcp.serviceaccount.Account(
        "pytorch-ci-admins",
        account_id="pytorch-ci-admins",
        display_name="PyTorch CI Admins Service Account",
        project=gcp_project,
    )

    # Grant GKE admin permissions to PyTorch CI admins
    admin_roles = [
        "roles/container.admin",
        "roles/compute.admin",
        "roles/iam.serviceAccountUser",
    ]

    for idx, role in enumerate(admin_roles):
        gcp.projects.IAMMember(
            f"pytorch-ci-admins-{idx}",
            project=gcp_project,
            role=role,
            member=Output.concat("serviceAccount:", pytorch_ci_admins_sa.email),
        )

    # Create GKE cluster for ARC development
    gke_cluster = gcp.container.Cluster(
        "lf-arc-dev-gke",
        name="lf-arc-dev",
        location=gcp_region,
        initial_node_count=1,
        remove_default_node_pool=True,
        network=vpc_network.name,
        subnetwork=subnetwork.name,
        networking_mode="VPC_NATIVE",
        ip_allocation_policy=gcp.container.ClusterIpAllocationPolicyArgs(
            cluster_secondary_range_name="pods",
            services_secondary_range_name="services",
        ),
        master_auth=gcp.container.ClusterMasterAuthArgs(
            client_certificate_config=gcp.container.ClusterMasterAuthClientCertificateConfigArgs(
                issue_client_certificate=False,
            ),
        ),
        master_authorized_networks_config=gcp.container.ClusterMasterAuthorizedNetworksConfigArgs(
            cidr_blocks=[
                gcp.container.ClusterMasterAuthorizedNetworksConfigCidrBlockArgs(
                    cidr_block="0.0.0.0/0",
                    display_name="All networks",
                ),
            ],
        ),
        private_cluster_config=gcp.container.ClusterPrivateClusterConfigArgs(
            enable_private_nodes=True,
            enable_private_endpoint=False,
            master_ipv4_cidr_block="172.16.0.0/28",
        ),
        workload_identity_config=gcp.container.ClusterWorkloadIdentityConfigArgs(
            workload_pool=f"{gcp_project}.svc.id.goog",
        ),
        addons_config=gcp.container.ClusterAddonsConfigArgs(
            http_load_balancing=gcp.container.ClusterAddonsConfigHttpLoadBalancingArgs(
                disabled=False,
            ),
            horizontal_pod_autoscaling=gcp.container.ClusterAddonsConfigHorizontalPodAutoscalingArgs(
                disabled=False,
            ),
        ),
        cluster_autoscaling=gcp.container.ClusterClusterAutoscalingArgs(
            enabled=True,
            resource_limits=[
                gcp.container.ClusterClusterAutoscalingResourceLimitArgs(
                    resource_type="cpu",
                    minimum=1,
                    maximum=100,
                ),
                gcp.container.ClusterClusterAutoscalingResourceLimitArgs(
                    resource_type="memory",
                    minimum=1,
                    maximum=256,
                ),
            ],
        ),
        logging_config=gcp.container.ClusterLoggingConfigArgs(
            enable_components=[
                "SYSTEM_COMPONENTS",
                "WORKLOADS",
                "APISERVER",
                "CONTROLLER_MANAGER",
                "SCHEDULER",
            ],
        ),
        monitoring_config=gcp.container.ClusterMonitoringConfigArgs(
            enable_components=[
                "SYSTEM_COMPONENTS",
                "WORKLOADS",
                "APISERVER",
                "CONTROLLER_MANAGER",
                "SCHEDULER",
            ],
            managed_prometheus=gcp.container.ClusterMonitoringConfigManagedPrometheusArgs(
                enabled=True,
            ),
        ),
        project=gcp_project,
    )

    # Create node pool for the GKE cluster
    gcp.container.NodePool(
        "arc-node-pool",
        name="arc-node-pool",
        cluster=gke_cluster.name,
        location=gcp_region,
        initial_node_count=1,
        autoscaling=gcp.container.NodePoolAutoscalingArgs(
            min_node_count=1,
            max_node_count=10,
        ),
        management=gcp.container.NodePoolManagementArgs(
            auto_repair=True,
            auto_upgrade=True,
        ),
        node_config=gcp.container.NodePoolNodeConfigArgs(
            preemptible=False,
            machine_type="n2-standard-4",
            service_account=gke_node_sa.email,
            oauth_scopes=[
                "https://www.googleapis.com/auth/cloud-platform",
            ],
            metadata={
                "disable-legacy-endpoints": "true",
            },
            workload_metadata_config=gcp.container.NodePoolNodeConfigWorkloadMetadataConfigArgs(
                mode="GKE_METADATA",
            ),
            shielded_instance_config=gcp.container.NodePoolNodeConfigShieldedInstanceConfigArgs(
                enable_secure_boot=True,
                enable_integrity_monitoring=True,
            ),
        ),
        project=gcp_project,
    )

    # Get cluster credentials for kubectl
    kubeconfig = Output.all(gke_cluster.name, gke_cluster.endpoint, gke_cluster.master_auth).apply(
        lambda args: json.dumps({
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{
                "name": args[0],
                "cluster": {
                    "server": f"https://{args[1]}",
                    "certificate-authority-data": args[2].cluster_ca_certificate,
                },
            }],
            "contexts": [{
                "name": args[0],
                "context": {
                    "cluster": args[0],
                    "user": args[0],
                },
            }],
            "current-context": args[0],
            "users": [{
                "name": args[0],
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "gke-gcloud-auth-plugin",
                        "installHint": "Install gke-gcloud-auth-plugin for kubectl authentication",
                    },
                },
            }],
        })
    )

    # Export outputs
    outputs = {
        "gke_cluster": gke_cluster,
        "gke_cluster_name": gke_cluster.name,
        "gke_cluster_endpoint": gke_cluster.endpoint,
        "gke_cluster_ca_certificate": gke_cluster.master_auth.cluster_ca_certificate,
        "vpc_network_id": vpc_network.id,
        "vpc_network_name": vpc_network.name,
        "subnetwork_id": subnetwork.id,
        "subnetwork_name": subnetwork.name,
        "gke_node_sa_email": gke_node_sa.email,
        "pytorch_ci_admins_sa_email": pytorch_ci_admins_sa.email,
        "workload_identity_pool": f"{gcp_project}.svc.id.goog",
        "kubeconfig": kubeconfig,
        "gcp_project": gcp_project,
        "gcp_region": gcp_region,
        "arc_environment": arc_prod_environment,
    }

    # Export to Pulumi stack outputs
    for key, value in outputs.items():
        pulumi.export(f"arc_gcp_{key}", value)

    return outputs
