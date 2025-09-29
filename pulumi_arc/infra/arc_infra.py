"""ARC Infrastructure Layer - VPC, EKS Cluster, and IAM Roles"""

import pulumi
from pulumi import Config, Output
import pulumi_aws as aws
import pulumi_awsx as awsx
import pulumi_eks as eks
import json


def deploy():
    """Deploy ARC infrastructure layer"""
    
    # Configuration
    config = Config()
    aws_config = Config("aws")
    
    # Get AWS region and account ID
    aws_region = aws_config.require("region")
    current_identity = aws.get_caller_identity()
    aws_account_id = current_identity.account_id
    
    # Environment configuration
    arc_prod_environment = config.get("arc_prod_environment") or "lf-arc-prod"
    
    # Availability zones
    availability_zones = [f"{aws_region}{loc}" for loc in ["a", "b", "c"]]
    
    # Create VPC for ARC runners
    vpc = awsx.ec2.Vpc(
        "arc-runners-vpc",
        vpc_name=arc_prod_environment,
        cidr_block="10.0.0.0/16",
        number_of_availability_zones=3,
        subnet_specs=[
            awsx.ec2.SubnetSpec(
                type=awsx.ec2.SubnetType.PRIVATE,
                cidr_mask=20,
            ),
            awsx.ec2.SubnetSpec(
                type=awsx.ec2.SubnetType.PUBLIC,
                cidr_mask=20,
            ),
        ],
        nat_gateways={
            "strategy": awsx.ec2.NatGatewayStrategy.ONE_PER_AZ,
        },
        tags={
            "Name": arc_prod_environment,
            "Environment": arc_prod_environment,
            "Project": arc_prod_environment,
        }
    )
    
    # Create IAM role for PyTorch CI admins
    pytorch_ci_admins_role = aws.iam.Role(
        "pytorch-ci-admins",
        name="pytorch-ci-admins",
        assume_role_policy=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{aws_account_id}:root"
                },
                "Action": "sts:AssumeRole"
            }]
        }),
        tags={
            "Environment": arc_prod_environment
        }
    )
    
    # Attach EKS policies to the admin role
    eks_cluster_policy_attachment = aws.iam.RolePolicyAttachment(
        "pytorch-ci-admins-eks-cluster",
        role=pytorch_ci_admins_role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
    )
    
    eks_service_policy_attachment = aws.iam.RolePolicyAttachment(
        "pytorch-arc-admins-eks-service",
        role=pytorch_ci_admins_role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonEKSServicePolicy"
    )
    
    # Create EKS cluster for ARC development
    eks_cluster = eks.Cluster(
        "lf-arc-dev-eks",
        name="lf-arc-dev",
        version="1.33",
        vpc_id=vpc.vpc_id,
        subnet_ids=vpc.private_subnet_ids,
        endpoint_private_access=False,
        endpoint_public_access=True,
        public_access_cidrs=["0.0.0.0/0"],
        create_oidc_provider=True,
        skip_default_node_group=True,
        enabled_cluster_log_types=[
            "api",
            "audit",
            "authenticator",
            "controllerManager",
            "scheduler",
        ],
        tags={
            "Environment": arc_prod_environment,
            "Name": "lf-arc-dev",
        },
        # Configure access entries for admin roles
        access_entries={
            "ossci_gha_terraform": eks.AccessEntryArgs(
                principal_arn=f"arn:aws:iam::{aws_account_id}:role/ossci_gha_terraform",
                type="STANDARD",
                access_policies={
                    "cluster_admin": eks.AccessPolicyAssociationArgs(
                        policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
                        access_scope=eks.AccessScopeArgs(
                            type="cluster",
                            namespaces=[]
                        )
                    )
                }
            ),
            "pytorch_ci_admins": eks.AccessEntryArgs(
                principal_arn=pytorch_ci_admins_role.arn,
                type="STANDARD",
                access_policies={
                    "cluster_admin": eks.AccessPolicyAssociationArgs(
                        policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
                        access_scope=eks.AccessScopeArgs(
                            type="cluster",
                            namespaces=[]
                        )
                    )
                }
            )
        }
    )
    
    # Export outputs for use by other layers
    outputs = {
        "vpc_id": vpc.vpc_id,
        "vpc_cidr": vpc.vpc.cidr_block,
        "private_subnet_ids": vpc.private_subnet_ids,
        "public_subnet_ids": vpc.public_subnet_ids,
        "eks_cluster": eks_cluster,
        "eks_cluster_name": eks_cluster.name,
        "eks_cluster_endpoint": eks_cluster.endpoint,
        "eks_cluster_certificate_authority": eks_cluster.certificate_authority,
        "eks_oidc_provider": eks_cluster.oidc_provider,
        "pytorch_ci_admins_role_arn": pytorch_ci_admins_role.arn,
        "aws_account_id": aws_account_id,
        "aws_region": aws_region,
        "arc_prod_environment": arc_prod_environment,
    }
    
    # Export key values
    pulumi.export("arc_vpc_id", vpc.vpc_id)
    pulumi.export("arc_eks_cluster_name", eks_cluster.name)
    pulumi.export("arc_eks_cluster_endpoint", eks_cluster.endpoint)
    pulumi.export("arc_pytorch_ci_admins_role_arn", pytorch_ci_admins_role.arn)
    
    return outputs