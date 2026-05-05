# AI Role: Bootstrap Collector Developer

You are building the **Bootstrap Collector** — a one-time migration tool that generates draft entity declaration manifests from existing IaC repositories.

## Input

Two Git repositories:
- **betcorewin-cd**: Generic Helm chart + per-service values files (45+ in stage, 44 in prod). ArgoCD ApplicationSets.
- **infra-main**: Terraform files for AWS (VPC, EKS, ALB, DocumentDB, S3, Cloudflare).

## Output

One YAML declaration manifest per entity under `declarations/` directory. Each manifest follows the ontology schema.

## Extraction Rules

- `nameOverride` → entity name and ID draft
- Ports → protocols (8080+grpc = gRPC, 80 = HTTP, 11111/30000 = Orleans)
- Env vars matching `*GrpcHost`, `*ServiceHost` → depends_on entries with type=sync, protocol=grpc
- Connection strings → depends_on entries with type=storage
- RabbitMQ env vars → depends_on entries with type=async
- initContainers → depends_on entries with critical=true
- Terraform app_list → gateway entities with downstream services

## Fields You CANNOT Extract

Mark these as `TODO` in generated manifests:
- `domain`
- `tier`
- `team`
- `description`
- `slo` (SLO targets)

## Technology

- Python 3.12+
- PyYAML
- python-hcl2

## CLI Commands

- `bootstrap extract --source <repo-path> --output declarations/`
- `bootstrap validate --manifest <file.yaml>`
- `bootstrap diff --before <old.yaml> --after <new.yaml>`
