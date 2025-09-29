"""ARC Helm Layer for GCP - Kubernetes resources, ArgoCD, and ARC controller setup"""


import pulumi
import pulumi_kubernetes as k8s
from pulumi import Config


def deploy(infra_outputs: dict):
    """
    Deploy ARC Helm layer for GCP including Kubernetes resources, ArgoCD, and ARC controller.

    Args:
        infra_outputs: Outputs from the GCP infrastructure layer
    """

    # Configuration
    config = Config()

    # ArgoCD configuration
    argocd_namespace = config.get("argocd_namespace") or "argocd"
    argocd_version = config.get("argocd_version") or "7.7.15"
    argocd_ingress_host = config.get("argocd_ingress_host_gcp") or "argocd-gcp.pytorch.org"
    letsencrypt_issuer = config.get("letsencrypt_issuer") or "letsencrypt-prod"
    argocd_dex_github_org = config.get("argocd_dex_github_org") or "pytorch"
    argocd_dex_github_team = config.get("argocd_dex_github_team") or "pytorch-dev-infra"

    # Get cluster information from infra layer
    infra_outputs["gke_cluster"]
    infra_outputs["gke_cluster_name"]
    infra_outputs["gke_cluster_endpoint"]
    infra_outputs["gke_cluster_ca_certificate"]
    kubeconfig = infra_outputs["kubeconfig"]
    gcp_project = infra_outputs["gcp_project"]

    # Create Kubernetes provider using the GKE cluster
    k8s_provider = k8s.Provider(
        "arc-gcp-k8s-provider",
        kubeconfig=kubeconfig,
    )

    # Create namespace for cert-manager
    cert_manager_namespace = k8s.core.v1.Namespace(
        "cert-manager-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="cert-manager",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Install cert-manager using Helm
    cert_manager = k8s.helm.v3.Release(
        "cert-manager-gcp",
        name="cert-manager",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://charts.jetstack.io",
        ),
        chart="cert-manager",
        version="v1.16.2",
        namespace=cert_manager_namespace.metadata.name,
        values={
            "crds": {
                "enabled": True,
            },
            "prometheus": {
                "enabled": False,
            },
        },
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Create ClusterIssuer for Let's Encrypt
    letsencrypt_issuer_resource = k8s.apiextensions.CustomResource(
        "letsencrypt-prod-gcp",
        api_version="cert-manager.io/v1",
        kind="ClusterIssuer",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=letsencrypt_issuer,
        ),
        spec={
            "acme": {
                "server": "https://acme-v02.api.letsencrypt.org/directory",
                "email": "pytorch-dev-infra@pytorch.org",
                "privateKeySecretRef": {
                    "name": f"{letsencrypt_issuer}-key",
                },
                "solvers": [{
                    "http01": {
                        "ingress": {
                            "class": "nginx",
                        },
                    },
                }],
            },
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=[cert_manager]
        )
    )

    # Install NGINX Ingress Controller
    nginx_namespace = k8s.core.v1.Namespace(
        "ingress-nginx-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="ingress-nginx",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    nginx_ingress = k8s.helm.v3.Release(
        "nginx-ingress-gcp",
        name="ingress-nginx",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://kubernetes.github.io/ingress-nginx",
        ),
        chart="ingress-nginx",
        version="4.11.3",
        namespace=nginx_namespace.metadata.name,
        values={
            "controller": {
                "service": {
                    "type": "LoadBalancer",
                    "annotations": {
                        "cloud.google.com/load-balancer-type": "External",
                    },
                },
                "metrics": {
                    "enabled": True,
                },
                "podAnnotations": {
                    "prometheus.io/scrape": "true",
                    "prometheus.io/port": "10254",
                },
            },
        },
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Create namespace for ArgoCD
    argocd_namespace_resource = k8s.core.v1.Namespace(
        "argocd-namespace-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=argocd_namespace,
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Install ArgoCD using Helm
    k8s.helm.v3.Release(
        "argocd-gcp",
        name="argocd",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://argoproj.github.io/argo-helm",
        ),
        chart="argo-cd",
        version=argocd_version,
        namespace=argocd_namespace_resource.metadata.name,
        values={
            "global": {
                "domain": argocd_ingress_host,
            },
            "server": {
                "ingress": {
                    "enabled": True,
                    "ingressClassName": "nginx",
                    "annotations": {
                        "cert-manager.io/cluster-issuer": letsencrypt_issuer,
                        "nginx.ingress.kubernetes.io/ssl-redirect": "true",
                        "nginx.ingress.kubernetes.io/backend-protocol": "HTTPS",
                    },
                    "hosts": [argocd_ingress_host],
                    "tls": [{
                        "secretName": "argocd-server-tls",
                        "hosts": [argocd_ingress_host],
                    }],
                },
                "config": {
                    "url": f"https://{argocd_ingress_host}",
                    "dex.config": f"""
connectors:
  - type: github
    id: github
    name: GitHub
    config:
      clientID: $dex.github.clientID
      clientSecret: $dex.github.clientSecret
      orgs:
      - name: {argocd_dex_github_org}
        teams:
        - {argocd_dex_github_team}
""",
                },
                "rbacConfig": {
                    "policy.default": "role:readonly",
                    "policy.csv": f"""
p, role:admin, applications, *, */*, allow
p, role:admin, clusters, *, *, allow
p, role:admin, repositories, *, *, allow
g, {argocd_dex_github_org}:{argocd_dex_github_team}, role:admin
""",
                },
            },
            "configs": {
                "params": {
                    "server.insecure": "false",
                },
            },
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=[nginx_ingress, letsencrypt_issuer_resource]
        )
    )

    # Create namespace for GitHub Actions Runner Controller
    arc_namespace = k8s.core.v1.Namespace(
        "arc-namespace-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="arc-system",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Install Actions Runner Controller
    k8s.helm.v3.Release(
        "arc-controller-gcp",
        name="actions-runner-controller",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://actions-runner-controller.github.io/actions-runner-controller",
        ),
        chart="actions-runner-controller",
        version="0.23.7",
        namespace=arc_namespace.metadata.name,
        values={
            "authSecret": {
                "create": False,
                "name": "controller-manager",
            },
            "serviceAccount": {
                "annotations": {
                    "iam.gke.io/gcp-service-account": f"arc-controller@{gcp_project}.iam.gserviceaccount.com",
                },
            },
            "metrics": {
                "serviceMonitor": {
                    "enabled": False,
                },
            },
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=[arc_namespace]
        )
    )

    # Export outputs
    outputs = {
        "cert_manager_namespace": cert_manager_namespace.metadata.name,
        "nginx_namespace": nginx_namespace.metadata.name,
        "argocd_namespace": argocd_namespace,
        "arc_namespace": arc_namespace.metadata.name,
        "argocd_url": f"https://{argocd_ingress_host}",
        "k8s_provider": k8s_provider,
    }

    # Export to Pulumi stack outputs
    for key, value in outputs.items():
        if key != "k8s_provider":  # Don't export the provider object
            pulumi.export(f"arc_gcp_helm_{key}", value)

    return outputs
