# CityScope

> **Infrastructure Ontology Platform** — From Observation to Understanding

## Overview

CityScope is an infrastructure ontology platform that models your entire system as a formal knowledge graph. Instead of inferring what exists by scraping metrics and parsing configuration files, CityScope uses **entity declaration manifests** — each service, datastore, and network segment declares what it is, what it depends on, and what rules govern it.

The first implementation targets the **NEXUS** platform: a multi-tenant iGaming system with 45+ microservices, Orleans actors, multiple data stores, and a complete LGTM observability stack.

## Why Ontology, Not Collection

| Traditional Observability | CityScope Ontology |
|---------------------------|-------------------|
| Parses IaC, infers entities | Services self-declare via YAML manifests |
| Pattern-matches env vars for dependencies | Dependencies explicitly declared and validated |
| Criticality guessed from traffic | Tier assigned by architect, enforced by rules |
| No formal rules | R001–R010 constraint rules validated in CI |
| Approximate, drifts over time | Authoritative — ontology IS the truth |
| AI sees raw data, must infer | AI reads typed ontology — structured understanding |

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Tier 2: Application Layer           │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ AI       │ │ City     │ │ Timelapse /      │ │
│  │ Planner  │ │ Renderer │ │ Incident Narrator│ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│           Tier 1: Ontology Core (Phase 1)        │
│  ┌────────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Ontology   │ │ Registr. │ │ Knowledge     │  │
│  │ Schema     │ │ Pipeline │ │ Graph (Git+YAML)│ │
│  └────────────┘ └──────────┘ └───────────────┘  │
│  ┌────────────┐ ┌──────────┐                    │
│  │ Bootstrap  │ │ Rule     │                    │
│  │ Collector  │ │ Engine   │                    │
│  └────────────┘ └──────────┘                    │
├─────────────────────────────────────────────────┤
│              Tier 3: Event Layer                 │
│  ┌──────────────────────────────────────────┐   │
│  │  Event Bridge (Go) → WebSocket → Renderer│   │
│  │  Sources: OTel, Mimir, Loki, Tempo, K8s  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

Events reference ontology entities but **do not modify the ontology**. Structural changes require PR review.

## Roadmap

| Phase | Timeline | Focus |
|-------|----------|-------|
| **Phase 1** | Weeks 1–3 | Ontology Core: schema, bootstrap collector, registration pipeline |
| **Phase 2** | Weeks 3–5 | AI Planner + Static City: Claude Sonnet layout, Three.js renderer |
| **Phase 3** | Weeks 5–8 | Event Layer: Go event bridge, WebSocket push, visual signatures |
| **Phase 4** | Weeks 8–10 | Timelapse Recorder: .ctsc binary format, playback UI |
| **Phase 5** | Week 10+ | AI Integration: ontology export, incident narrator, query API |

## Quick Start

```bash
# Clone
git clone https://github.com/ervolkan/cityscope.git
cd cityscope

# Install dependencies
pip install -r requirements.txt

# Run bootstrap collector (once, for migration)
python -m src.bootstrap extract --source /path/to/iac --output declarations/

# Validate all declarations
python -m src.registration validate

# Generate consolidated ontology
python -m src.registration consolidate --output ontology.json
```

## Project Structure

```
cityscope/
├── src/
│   ├── ontology/        # JSON Schema, rules, domains, teams
│   ├── bootstrap/       # IaC parser → draft declaration manifests
│   └── registration/    # Validation pipeline → ontology.json
├── declarations/        # Entity YAML manifests (source of truth)
├── docs/                # Design docs, gap analysis, specifications
├── scripts/             # CI/CLI utilities
├── .ai/
│   └── roles/           # AI collaborator prompt files
└── .github/
    └── workflows/       # CI pipeline (validate on PR)
```

## Entity Types

| Type | Description | Example |
|-------|-------------|---------|
| `service` | Deployable unit processing nexus-wallet, nexus-payment |
| `gateway` | Entry point routing external traffic | ALB, Cloudflare proxy |
| `datastore` | Persistent storage | PostgreSQL, MSSQL, DocumentDB |
| `cache` | In-memory data store | Redis |
| `messagebus` | Async message broker | RabbitMQ |
| `storage` | Object/file storage | S3 buckets |
| `compute` | Compute resource group | EKS worker nodes |
| `network` | Network segments | VPC, subnets |

## License

Confidential — Internal Use Only
