"""ARC ArgoCD Layer for GCP - Runner Scale Sets configuration"""

import pulumi
import pulumi_kubernetes as k8s
import yaml
from pulumi import Config


def deploy(helm_outputs: dict):
    """
    Deploy ARC ArgoCD layer for GCP including runner scale sets.

    Args:
        helm_outputs: Outputs from the GCP Helm layer
    """

    # Configuration
    config = Config()

    # ArgoCD configuration
    organization = config.get("organization") or "lf"
    cluster = config.get("cluster") or "in-cluster"
    provider_path = config.get("provider_path_gcp") or "argocd/gcp/pytorch-ci/us-central1"
    git_revision = config.get("git_revision") or "main"

    # Get Kubernetes provider from helm layer
    k8s_provider = helm_outputs["k8s_provider"]
    argocd_namespace = helm_outputs["argocd_namespace"]

    # Runner configurations
    runner_configs = [
        {
            "name": "linux-amd64-cpu",
            "runner_group": "Default",
            "labels": ["linux", "x64", "cpu"],
            "max_runners": 10,
            "min_runners": 0,
        },
        {
            "name": "linux-amd64-gpu",
            "runner_group": "Default",
            "labels": ["linux", "x64", "gpu"],
            "max_runners": 5,
            "min_runners": 0,
        },
        {
            "name": "linux-arm64-cpu",
            "runner_group": "Default",
            "labels": ["linux", "arm64", "cpu"],
            "max_runners": 5,
            "min_runners": 0,
        },
        {
            "name": "windows-amd64",
            "runner_group": "Default",
            "labels": ["windows", "x64"],
            "max_runners": 5,
            "min_runners": 0,
        },
    ]

    # Create ArgoCD Application for each runner scale set
    argocd_apps = []
    for runner_config in runner_configs:
        app_name = f"arc-runner-{runner_config['name']}"

        # Create ArgoCD Application manifest
        app_manifest = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Application",
            "metadata": {
                "name": app_name,
                "namespace": argocd_namespace,
                "finalizers": ["resources-finalizer.argocd.argoproj.io"],
            },
            "spec": {
                "project": "default",
                "source": {
                    "repoURL": "https://github.com/pytorch/ci-infra",
                    "targetRevision": git_revision,
                    "path": f"{provider_path}/runner-scale-sets/{runner_config['name']}",
                },
                "destination": {
                    "server": "https://kubernetes.default.svc",
                    "namespace": "arc-runners",
                },
                "syncPolicy": {
                    "automated": {
                        "prune": True,
                        "selfHeal": True,
                        "allowEmpty": False,
                    },
                    "syncOptions": [
                        "CreateNamespace=true",
                        "PrunePropagationPolicy=foreground",
                    ],
                    "retry": {
                        "limit": 5,
                        "backoff": {
                            "duration": "5s",
                            "factor": 2,
                            "maxDuration": "3m",
                        },
                    },
                },
                "revisionHistoryLimit": 10,
            },
        }

        # Create the ArgoCD Application
        app = k8s.apiextensions.CustomResource(
            f"argocd-app-{app_name}-gcp",
            api_version="argoproj.io/v1alpha1",
            kind="Application",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=app_name,
                namespace=argocd_namespace,
            ),
            spec=app_manifest["spec"],
            opts=pulumi.ResourceOptions(provider=k8s_provider)
        )
        argocd_apps.append(app)

    # Create ArgoCD AppProject for runner scale sets
    k8s.apiextensions.CustomResource(
        "arc-runners-project-gcp",
        api_version="argoproj.io/v1alpha1",
        kind="AppProject",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="arc-runners",
            namespace=argocd_namespace,
        ),
        spec={
            "description": "GitHub Actions Runner Controller Scale Sets",
            "sourceRepos": ["https://github.com/pytorch/ci-infra"],
            "destinations": [{
                "namespace": "arc-runners",
                "server": "https://kubernetes.default.svc",
            }],
            "clusterResourceWhitelist": [{
                "group": "*",
                "kind": "*",
            }],
            "namespaceResourceWhitelist": [{
                "group": "*",
                "kind": "*",
            }],
            "roles": [{
                "name": "admin",
                "policies": [
                    "p, proj:arc-runners:admin, applications, *, arc-runners/*, allow",
                ],
                "groups": [
                    f"{config.get('argocd_dex_github_org') or 'pytorch'}:{config.get('argocd_dex_github_team') or 'pytorch-dev-infra'}",
                ],
            }],
        },
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Create namespace for runners
    runners_namespace = k8s.core.v1.Namespace(
        "arc-runners-namespace-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="arc-runners",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Create ConfigMap for runner scale set configurations
    k8s.core.v1.ConfigMap(
        "arc-runner-configs-gcp",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="runner-configs",
            namespace=runners_namespace.metadata.name,
        ),
        data={
            "runners.yaml": yaml.dump({
                "runners": runner_configs,
                "organization": organization,
                "cluster": cluster,
            }),
        },
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )

    # Export outputs
    outputs = {
        "argocd_apps": [f"arc-runner-{config['name']}" for config in runner_configs],
        "app_project": "arc-runners",
        "runners_namespace": "arc-runners",
        "runner_config_map": "runner-configs",
        "runner_configs": runner_configs,
    }

    # Export to Pulumi stack outputs
    for key, value in outputs.items():
        pulumi.export(f"arc_gcp_argocd_{key}", value)

    return outputs
