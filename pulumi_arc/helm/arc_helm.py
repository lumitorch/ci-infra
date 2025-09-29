"""ARC Helm Layer - Kubernetes resources, ArgoCD, and ARC controller setup"""

import pulumi
from pulumi import Config, Output
import pulumi_aws as aws
import pulumi_kubernetes as k8s
import pulumi_random as random
import json


def deploy(infra_outputs: dict):
    """
    Deploy ARC Helm layer including Kubernetes resources, ArgoCD, and ARC controller.
    
    Args:
        infra_outputs: Outputs from the infrastructure layer
    """
    
    # Configuration
    config = Config()
    
    # ArgoCD configuration
    argocd_namespace = config.get("argocd_namespace") or "argocd"
    argocd_version = config.get("argocd_version") or "7.7.15"
    argocd_ingress_host = config.get("argocd_ingress_host") or "argocd.pytorch.org"
    letsencrypt_issuer = config.get("letsencrypt_issuer") or "letsencrypt-prod"
    argocd_dex_github_org = config.get("argocd_dex_github_org") or "pytorch"
    argocd_dex_github_team = config.get("argocd_dex_github_team") or "pytorch-dev-infra"
    argocd_sa_terraform = config.get("argocd_sa_terraform") or "terraform"
    
    # Get cluster information from infra layer
    eks_cluster = infra_outputs["eks_cluster"]
    cluster_name = infra_outputs["eks_cluster_name"]
    cluster_endpoint = infra_outputs["eks_cluster_endpoint"]
    cluster_ca = infra_outputs["eks_cluster_certificate_authority"]
    oidc_provider = infra_outputs["eks_oidc_provider"]
    vpc_id = infra_outputs["vpc_id"]
    
    # Create Kubernetes provider using the EKS cluster
    k8s_provider = k8s.Provider(
        "arc-k8s-provider",
        kubeconfig=eks_cluster.kubeconfig_json,
    )
    
    # Create namespace for cert-manager
    cert_manager_namespace = k8s.core.v1.Namespace(
        "cert-manager",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="cert-manager",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )
    
    # Install cert-manager using Helm
    cert_manager = k8s.helm.v3.Release(
        "cert-manager",
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
    
    # Create ClusterIssuer for Let\'s Encrypt
    letsencrypt_issuer_resource = k8s.apiextensions.CustomResource(
        "letsencrypt-prod",
        api_version="cert-manager.io/v1",
        kind="ClusterIssuer",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="letsencrypt-prod",
        ),
        spec={
            "acme": {
                "server": "https://acme-v02.api.letsencrypt.org/directory",
                "email": "pytorch-dev-infra@meta.com",
                "privateKeySecretRef": {
                    "name": "letsencrypt-prod",
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
    nginx_ingress = k8s.helm.v3.Release(
        "ingress-nginx",
        name="ingress-nginx",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://kubernetes.github.io/ingress-nginx",
        ),
        chart="ingress-nginx",
        version="4.11.3",
        namespace="ingress-nginx",
        create_namespace=True,
        values={
            "controller": {
                "service": {
                    "type": "LoadBalancer",
                    "annotations": {
                        "service.beta.kubernetes.io/aws-load-balancer-type": "nlb",
                        "service.beta.kubernetes.io/aws-load-balancer-scheme": "internet-facing",
                    },
                },
            },
        },
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )
    
    # Get ArgoCD GitHub OAuth credentials from AWS Secrets Manager
    argocd_oauth_secret = aws.secretsmanager.get_secret_version(
        secret_id="pytorch-argocd-dex-github-oauth-app"
    )
    
    argocd_oauth_data = Output.from_input(argocd_oauth_secret.secret_string).apply(
        lambda s: json.loads(s)
    )
    
    # Create Kubernetes secret for ArgoCD GitHub OAuth
    argocd_github_oauth_secret = k8s.core.v1.Secret(
        "argocd-github-oauth",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="argocd-github-oauth",
            namespace=argocd_namespace,
            labels={
                "app.kubernetes.io/name": "argocd-github-oauth",
                "app.kubernetes.io/part-of": "argocd",
            },
        ),
        string_data={
            "dex.github.clientSecret": argocd_oauth_data.apply(lambda d: d["client_secret"]),
        },
        type="Opaque",
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )
    
    # Install ArgoCD using Helm
    argocd = k8s.helm.v3.Release(
        "argocd",
        name="argocd",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://argoproj.github.io/argo-helm",
        ),
        chart="argo-cd",
        version=argocd_version,
        namespace=argocd_namespace,
        create_namespace=True,
        values={
            "server": {
                "ingress": {
                    "enabled": True,
                    "ingressClassName": "nginx",
                    "annotations": {
                        "cert-manager.io/cluster-issuer": letsencrypt_issuer,
                        "nginx.ingress.kubernetes.io/backend-protocol": "HTTPS",
                    },
                    "hosts": [argocd_ingress_host],
                    "tls": [{
                        "secretName": "argocd-server-tls",
                        "hosts": [argocd_ingress_host],
                    }],
                },
                "extraArgs": [
                    "--insecure",
                ],
            },
            "configs": {
                "cm": {
                    "url": f"https://{argocd_ingress_host}",
                    "dex.config": Output.all(
                        argocd_oauth_data,
                        argocd_github_oauth_secret.metadata.name
                    ).apply(lambda args: f"""
connectors:
- type: github
  id: github
  name: GitHub
  config:
    clientID: {args[0]["client_id"]}
    clientSecret: ${args[1]}:dex.github.clientSecret
    orgs:
    - name: {argocd_dex_github_org}
      teams:
      - {argocd_dex_github_team}
"""),
                },
                "rbac": {
                    "policy.csv": f"""
g, {argocd_dex_github_org}:{argocd_dex_github_team}, role:admin
g, {argocd_sa_terraform}, role:admin
""",
                },
            },
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=[argocd_github_oauth_secret, nginx_ingress]
        )
    )
    
    # Install ARC (Actions Runner Controller)
    arc = k8s.helm.v3.Release(
        "arc",
        name="arc",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="oci://ghcr.io/actions/actions-runner-controller-charts",
        ),
        chart="gha-runner-scale-set-controller",
        version="0.12.1",
        namespace="arc-system",
        create_namespace=True,
        values={
            "metrics": {
                "controllerManagerAddr": ":8080",
                "listenerAddr": ":8080",
                "listenerEndpoint": "/metrics",
            },
            "logLevel": "info",
            "logFormat": "json",
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=[nginx_ingress]
        )
    )
    
    # Export outputs for use by other layers
    outputs = {
        **infra_outputs,  # Pass through infra outputs
        "k8s_provider": k8s_provider,
        "argocd_namespace": argocd_namespace,
        "arc_namespace": "arc-system",
        "nginx_ingress_namespace": "ingress-nginx",
        "cert_manager_namespace": cert_manager_namespace.metadata.name,
    }
    
    # Export key values
    pulumi.export("arc_argocd_namespace", argocd_namespace)
    pulumi.export("arc_arc_namespace", "arc-system")
    pulumi.export("arc_nginx_ingress_installed", True)
    pulumi.export("arc_argocd_installed", True)
    pulumi.export("arc_controller_installed", True)
    
    return outputs