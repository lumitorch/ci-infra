# PyTorch CI Infrastructure - Pulumi Migration

This directory contains the Pulumi Python migration of the PyTorch CI infrastructure, previously managed with Terraform.

## Overview

The infrastructure has been successfully migrated from Terraform HCL to Pulumi Python, maintaining the same architecture and functionality. The migration includes:

### Components Migrated

1. **ARC (Actions Runner Controller)**
   - VPC with public/private subnets and NAT gateways
   - EKS cluster (lf-arc-dev) with Kubernetes 1.33
   - IAM roles for cluster administration
   - NGINX Ingress Controller
   - Cert-Manager with Let's Encrypt integration
   - ArgoCD for GitOps deployments
   - GitHub Actions Runner Controller
   - Runner Scale Sets configuration

2. **ALI (Autoscaler Lambda Infrastructure)**
   - Multiple VPCs with peering connections
   - Lambda-based EC2 autoscaler for GitHub Actions
   - IAM policies for ECR, S3, and Lambda access
   - GitHub OIDC role for CI/CD workflows
   - Support for both production and canary environments

3. **Shared Infrastructure**
   - S3 buckets for state storage
   - DynamoDB tables for state locking
   - Backend state management utilities

## Project Structure

```
ci-infra/
├── __main__.py                 # Main Pulumi program entry point
├── Pulumi.yaml                 # Pulumi project configuration
├── Pulumi.dev.yaml            # Development stack configuration
├── requirements.txt           # Python dependencies
├── pulumi_arc/                # ARC infrastructure modules
│   ├── infra/                # Layer 1: VPC, EKS, IAM
│   ├── helm/                 # Layer 2: Kubernetes resources
│   └── argocd/               # Layer 3: Runner scale sets
├── pulumi_ali/                # ALI infrastructure modules
│   └── ali_infra.py          # VPCs, Lambda, IAM policies
└── pulumi_shared/             # Shared utilities
    └── backend_state.py       # State management resources
```

## Migration Benefits

1. **Type Safety**: Python's type system provides better IDE support and error detection
2. **Better Abstractions**: Pulumi's component resources allow for cleaner abstractions
3. **Native Loops and Conditionals**: No need for complex Terraform expressions
4. **Unified Programming Model**: Use Python for both infrastructure and application code
5. **Rich Ecosystem**: Access to Python's extensive library ecosystem

## Prerequisites

- Python 3.8 or later
- Pulumi CLI installed
- AWS credentials configured
- Access to the PyTorch AWS account (391835788720)

## Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Select the Pulumi stack:
   ```bash
   pulumi stack select dev
   ```

## Configuration

The infrastructure is configured through `Pulumi.dev.yaml`. Key configuration options:

- `deploy_arc`: Enable/disable ARC infrastructure deployment
- `deploy_ali`: Enable/disable ALI infrastructure deployment
- `deploy_argocd`: Enable/disable ArgoCD deployment
- `aws:region`: AWS region (default: us-east-1)

## Deployment

1. Preview changes:
   ```bash
   pulumi preview
   ```

2. Deploy infrastructure:
   ```bash
   pulumi up
   ```

3. To deploy specific components:
   ```bash
   # Deploy only ARC
   pulumi config set deploy_arc true
   pulumi config set deploy_ali false
   pulumi up
   
   # Deploy only ALI
   pulumi config set deploy_arc false
   pulumi config set deploy_ali true
   pulumi up
   ```

## State Management

Pulumi manages state through the Pulumi Service by default. The migrated infrastructure includes the same backend state resources (S3 buckets and DynamoDB tables) that were used with Terraform, allowing for a smooth transition.

## Layered Architecture

The migration maintains the same layered architecture as the original Terraform code:

1. **Infrastructure Layer**: VPCs, subnets, EKS cluster, IAM roles
2. **Platform Layer**: Kubernetes resources, ingress, cert-manager
3. **Application Layer**: ArgoCD, runner scale sets

Each layer depends on outputs from the previous layer, ensuring proper dependency management.

## Security Considerations

- All secrets are managed through AWS Secrets Manager
- IAM roles use least-privilege principles
- OIDC is used for GitHub Actions authentication
- Network isolation through VPC and security groups

## Differences from Terraform

While the functionality remains the same, there are some implementation differences:

1. **Resource Naming**: Pulumi auto-generates unique names by default
2. **State Management**: Uses Pulumi Service instead of S3 backend
3. **Module Structure**: Python packages instead of Terraform modules
4. **Provider Configuration**: Configured through Pulumi config instead of provider blocks

## Troubleshooting

1. **AWS Credentials**: Ensure AWS credentials are properly configured
2. **Python Dependencies**: Run `pip install -r requirements.txt` if imports fail
3. **Stack Selection**: Make sure the correct stack is selected with `pulumi stack select`
4. **Resource Conflicts**: If resources already exist, you may need to import them

## Next Steps

1. Test the deployment in a development environment
2. Import existing resources if doing an in-place migration
3. Update CI/CD pipelines to use Pulumi instead of Terraform
4. Train team on Pulumi concepts and Python infrastructure code

## Support

For questions or issues with the migration, please contact the PyTorch infrastructure team.

## License

This infrastructure code follows the same licensing as the PyTorch project.