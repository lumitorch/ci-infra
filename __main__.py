"""PyTorch CI Infrastructure - Pulumi Python Migration"""

import pulumi
from pulumi import Config

# Import infrastructure components
from pulumi_arc.infra import arc_infra
from pulumi_arc.helm import arc_helm
from pulumi_arc.argocd import arc_argocd
from pulumi_ali import ali_infra

# Get configuration
config = Config()
deploy_arc = config.get_bool("deploy_arc") or True
deploy_ali = config.get_bool("deploy_ali") or True
deploy_argocd = config.get_bool("deploy_argocd") or True

# Deploy ARC infrastructure if enabled
if deploy_arc:
    # Layer 1: Base infrastructure (VPC, EKS, IAM)
    arc_infra_outputs = arc_infra.deploy()
    
    # Layer 2: Helm deployments (K8s resources, ArgoCD, ARC)
    arc_helm_outputs = arc_helm.deploy(arc_infra_outputs)
    
    # Layer 3: ArgoCD runner scale sets
    if deploy_argocd:
        arc_argocd_outputs = arc_argocd.deploy(arc_helm_outputs)

# Deploy ALI infrastructure if enabled
if deploy_ali:
    ali_outputs = ali_infra.deploy()

# Export key outputs
pulumi.export("message", "PyTorch CI Infrastructure deployed successfully")