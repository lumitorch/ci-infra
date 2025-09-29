"""ARC ArgoCD Layer - Runner Scale Sets configuration"""

import pulumi
from pulumi import Config, Output
import pulumi_aws as aws
import pulumi_kubernetes as k8s
import json
import os


def deploy(helm_outputs: dict):
    """
    Deploy ARC ArgoCD layer including runner scale sets.
    
    Args:
        helm_outputs: Outputs from the Helm layer
    """
    
    # Configuration
    config = Config()
    
    # ArgoCD configuration
    organization = config.get("organization") or "lf"
    cluster = config.get("cluster") or "in-cluster"
    provider_path = config.get("provider_path") or "argocd/aws/391835788720/us-east-1"
    git_revision = config.get("git_revision") or "main"
    
    # Get Kubernetes provider from Helm layer
    k8s_provider = helm_outputs["k8s_provider"]
    argocd_namespace = helm_outputs["argocd_namespace"]
    
    # Get ARC GitHub App credentials from AWS Secrets Manager
    arc_config_secret = aws.secretsmanager.get_secret_version(
        secret_id="pytorch-arc-github-app"
    )
    
    arc_private_key_secret = aws.secretsmanager.get_secret_version(
        secret_id="pytorch-arc-github-app-private-key"
    )
    
    arc_config = Output.from_input(arc_config_secret.secret_string).apply(
        lambda s: json.loads(s)
    )
    
    arc_app_id = arc_config.apply(lambda c: c["app-id"])
    arc_installation_id = arc_config.apply(lambda c: c["installation-id"])
    arc_private_key = arc_private_key_secret.secret_string
    
    # Create ClusterRole for secret reading
    secret_reader_role = k8s.rbac.v1.ClusterRole(
        "secret-reader",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="secret-reader",
        ),
        rules=[
            k8s.rbac.v1.PolicyRuleArgs(
                api_groups=[""],
                resources=["secrets"],
                verbs=["get", "list", "watch"],
            ),
        ],
        opts=pulumi.ResourceOptions(provider=k8s_provider)
    )
    
    # Define runner scale sets (in a real migration, this would be discovered from the filesystem)
    # For now, we'll define a sample set
    runner_scale_sets = {
        "aws": "aws",  # Example runner scale set
    }
    
    # Create resources for each runner scale set
    namespaces = {}
    github_secrets = {}
    role_bindings = {}
    
    for name, value in runner_scale_sets.items():
        namespace_name = f"{organization}-{value}"
        
        # Create namespace
        namespace = k8s.core.v1.Namespace(
            f"arc-runners-{name}",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=namespace_name,
            ),
            opts=pulumi.ResourceOptions(provider=k8s_provider)
        )
        namespaces[name] = namespace
        
        # Create GitHub App secret in the namespace
        github_secret = k8s.core.v1.Secret(
            f"github-app-{name}",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="github-config",
                namespace=namespace.metadata.name,
            ),
            string_data={
                "github_app_id": arc_app_id,
                "github_app_installation_id": arc_installation_id,
                "github_app_private_key": arc_private_key,
            },
            type="Opaque",
            opts=pulumi.ResourceOptions(
                provider=k8s_provider,
                depends_on=[namespace]
            )
        )
        github_secrets[name] = github_secret
        
        # Create RoleBinding for secret access
        role_binding = k8s.rbac.v1.RoleBinding(
            f"secret-access-{name}",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="secret-reader-binding",
                namespace=namespace.metadata.name,
            ),
            role_ref=k8s.rbac.v1.RoleRefArgs(
                api_group="rbac.authorization.k8s.io",
                kind="ClusterRole",
                name=secret_reader_role.metadata.name,
            ),
            subjects=[
                k8s.rbac.v1.SubjectArgs(
                    kind="ServiceAccount",
                    name="default",
                    namespace=namespace.metadata.name,
                ),
            ],
            opts=pulumi.ResourceOptions(
                provider=k8s_provider,
                depends_on=[namespace, secret_reader_role]
            )
        )
        role_bindings[name] = role_binding
    
    # Create ArgoCD ApplicationSet for runner scale sets
    # Note: This requires the ArgoCD CRDs to be installed, which happens in the Helm layer
    application_set = k8s.apiextensions.CustomResource(
        "arc-runner-scale-sets",
        api_version="argoproj.io/v1alpha1",
        kind="ApplicationSet",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=f"arc-runner-scale-sets-{organization}",
            namespace=argocd_namespace,
        ),
        spec={
            "generators": [{
                "git": {
                    "repoURL": "https://github.com/pytorch/ci-infra",
                    "revision": git_revision,
                    "directories": [{
                        "path": f"{provider_path}/{cluster}/*",
                    }],
                },
            }],
            "template": {
                "metadata": {
                    "name": "{{path.basename}}",
                },
                "spec": {
                    "project": "default",
                    "source": {
                        "repoURL": "oci://ghcr.io/actions/actions-runner-controller-charts",
                        "chart": "gha-runner-scale-set",
                        "targetRevision": "0.12.1",
                        "helm": {
                            "valueFiles": [
                                f"https://raw.githubusercontent.com/pytorch/ci-infra/{git_revision}/{provider_path}/{cluster}/{{{{path.basename}}}}/values.yaml",
                            ],
                        },
                    },
                    "destination": {
                        "server": "https://kubernetes.default.svc",
                        "namespace": f"{organization}-{{{{path.basename}}}}",
                    },
                    "syncPolicy": {
                        "automated": {
                            "prune": True,
                            "selfHeal": True,
                        },
                    },
                },
            },
        },
        opts=pulumi.ResourceOptions(
            provider=k8s_provider,
            depends_on=list(namespaces.values()) + list(github_secrets.values())
        )
    )
    
    # Export outputs
    outputs = {
        **helm_outputs,  # Pass through helm outputs
        "runner_namespaces": [ns.metadata.name for ns in namespaces.values()],
        "application_set_name": application_set.metadata.name,
    }
    
    # Export key values
    pulumi.export("arc_runner_namespaces", [ns.metadata.name for ns in namespaces.values()])
    pulumi.export("arc_application_set_created", True)
    
    return outputs