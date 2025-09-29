# Google Cloud Platform Infrastructure for PyTorch CI

This document describes the Google Cloud Platform (GCP) infrastructure components that have been added as equivalents to the existing AWS infrastructure.

## Overview

The GCP infrastructure provides the same capabilities as the AWS infrastructure but uses Google Cloud services:

| AWS Service | GCP Equivalent | Purpose |
|------------|----------------|---------|
| VPC | VPC Network | Network isolation |
| Subnets | Subnetworks | Network segmentation |
| NAT Gateway | Cloud NAT | Outbound internet access |
| EKS | GKE | Kubernetes cluster |
| Lambda | Cloud Functions | Serverless compute |
| EC2 | Compute Engine | Virtual machines |
| IAM Roles | Service Accounts & IAM | Access control |
| S3 | Cloud Storage | Object storage |
| DynamoDB | Firestore | NoSQL database |
| ECR | Artifact Registry | Container registry |
| Secrets Manager | Secret Manager | Secrets management |
| OIDC Provider | Workload Identity Federation | GitHub Actions authentication |

## Components

### 1. ARC Infrastructure (GKE)

Located in `pulumi_arc_gcp/`:

- **VPC Network**: Isolated network for GKE cluster
- **GKE Cluster**: Managed Kubernetes cluster with:
  - Workload Identity enabled
  - Private nodes with Cloud NAT
  - Auto-scaling node pools
  - Integrated monitoring and logging
- **Service Accounts**: For GKE nodes and admin access
- **Helm Deployments**: NGINX Ingress, Cert-Manager, ArgoCD
- **Runner Scale Sets**: GitHub Actions runners on GKE

### 2. ALI Infrastructure (Cloud Functions)

Located in `pulumi_ali_gcp/`:

- **Multiple VPC Networks**: With peering for production and canary
- **Cloud NAT**: For outbound internet access
- **Workload Identity Federation**: GitHub Actions authentication
- **Service Accounts**: For various GCP services
- **Cloud Storage**: For build cache (sccache equivalent)
- **Cloud Functions**: Autoscaler implementation (Lambda equivalent)

### 3. Shared Infrastructure

Located in `pulumi_shared_gcp/`:

- **Cloud Storage Buckets**: 
  - State storage bucket with versioning
  - Backup bucket with lifecycle policies
  - Artifacts bucket
  - Logs bucket
- **Firestore Database**: For state locking (DynamoDB equivalent)
- **Service Account**: For state management

## Configuration

### Prerequisites

1. **GCP Project**: Create a GCP project for the infrastructure
2. **Enable APIs**: The following APIs need to be enabled:
   - Compute Engine API
   - Kubernetes Engine API
   - Cloud Storage API
   - Firestore API
   - IAM API
   - Cloud Functions API
   - Artifact Registry API

3. **Authentication**: Configure GCP credentials:
   ```bash
   gcloud auth application-default login
   gcloud config set project YOUR_PROJECT_ID
   ```

### Stack Configuration

1. **Create a GCP stack**:
   ```bash
   pulumi stack init gcp
   ```

2. **Use the GCP configuration**:
   ```bash
   pulumi stack select gcp
   cp Pulumi.gcp.yaml Pulumi.gcp.yaml.example
   # Edit Pulumi.gcp.yaml with your project settings
   ```

3. **Set your GCP project ID**:
   ```bash
   pulumi config set gcp:project YOUR_PROJECT_ID
   ```

### Deployment

1. **Deploy shared infrastructure first**:
   ```bash
   pulumi config set deploy_arc_gcp false
   pulumi config set deploy_ali_gcp false
   pulumi up
   ```

2. **Deploy ARC (GKE) infrastructure**:
   ```bash
   pulumi config set deploy_arc_gcp true
   pulumi config set deploy_argocd_gcp true
   pulumi up
   ```

3. **Deploy ALI (Cloud Functions) infrastructure**:
   ```bash
   pulumi config set deploy_ali_gcp true
   pulumi up
   ```

## Key Differences from AWS

### Networking
- GCP uses VPC Networks instead of VPCs
- Subnets are regional, not zonal
- Cloud NAT is configured per region, not per availability zone
- VPC peering is bidirectional by default

### Kubernetes
- GKE includes many features by default (monitoring, logging, autoscaling)
- Workload Identity replaces IRSA for pod-level permissions
- GKE Autopilot is available for serverless Kubernetes

### IAM
- Service Accounts are the primary identity mechanism
- Workload Identity Federation replaces OIDC providers
- IAM bindings are at the project/resource level

### Storage
- Cloud Storage has built-in lifecycle management
- Firestore provides automatic scaling and replication
- No separate service for secrets (integrated with Secret Manager)

## Cost Optimization

1. **Use Preemptible VMs**: For non-critical workloads
2. **Enable GKE Autopilot**: For automatic resource optimization
3. **Set lifecycle policies**: On Cloud Storage buckets
4. **Use Cloud NAT**: Only where needed
5. **Regional resources**: Use single region where possible

## Monitoring and Logging

GCP provides integrated monitoring through:
- Cloud Monitoring (Stackdriver)
- Cloud Logging
- Cloud Trace
- Cloud Profiler

All are automatically integrated with GKE and other services.

## Security Best Practices

1. **Enable Workload Identity**: For GKE workloads
2. **Use Private GKE clusters**: With authorized networks
3. **Enable Binary Authorization**: For container security
4. **Use VPC Service Controls**: For API security
5. **Enable Cloud Armor**: For DDoS protection
6. **Implement least privilege**: With fine-grained IAM

## Troubleshooting

### Common Issues

1. **API not enabled**: Enable required APIs in the GCP Console
2. **Insufficient permissions**: Check IAM roles for your user/service account
3. **Quota exceeded**: Request quota increases in the GCP Console
4. **Network connectivity**: Verify firewall rules and Cloud NAT configuration

### Useful Commands

```bash
# Check GKE cluster status
gcloud container clusters list

# Get GKE credentials
gcloud container clusters get-credentials lf-arc-dev --region us-central1

# List service accounts
gcloud iam service-accounts list

# Check Cloud Storage buckets
gsutil ls

# View Firestore databases
gcloud firestore databases list
```

## Migration from AWS

To migrate from AWS to GCP:

1. **Export data**: From S3 to Cloud Storage, DynamoDB to Firestore
2. **Update DNS**: Point to new GCP load balancers
3. **Migrate secrets**: From Secrets Manager to Secret Manager
4. **Update CI/CD**: Configure Workload Identity Federation
5. **Test thoroughly**: In staging before production

## Support

For issues or questions:
1. Check the [GCP documentation](https://cloud.google.com/docs)
2. Review [Pulumi GCP provider docs](https://www.pulumi.com/registry/packages/gcp/)
3. Contact the PyTorch infrastructure team