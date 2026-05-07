# CityScope Session Handoff — 2025-05-07 (Session 2)

## What we built this session

### 1. Nature Classification (`classify_nature()` in engine.py)
Implements ENTITY-ONTOLOGY.md §3 derivation rules in code:
- N-01: NUCLEUS — datastore/cache with critical_fan_in >= 3
- N-02: CONDUIT — messagebus with fan_in >= 3
- N-03: MEMBRANE — external gateway (receives_external_traffic + type=gateway)
- N-04: SUBSTRATE — network/compute/storage infrastructure
- N-05c: SENTINEL — service with CFI >= 5 + narrow protocol surface (≤ 2 protocols)
- N-05a: REACTOR — service with fan_in >= 1 AND fan_out >= 3
- N-05b: WORKER — everything else (default processor)

Each entity gets `spec.nature`, `spec.sub_nature` (for processors), and
`_signals.nature` audit trail with the rule that fired and input signals.

### 2. Domain Semantic Naming (`name_domains()` in engine.py)
Replaces generic `domain-001`, `domain-002` with meaningful names derived from:
- Dominant storage target technology (mssql, postgres, docdb, etc.)
- Protocol stack hints (orleans/mssql → wincore, grpc+http+postgres → nexus)
- Result: `wincore-mssql`, `app-postgres`, `infrastructure`, `standalone`

### 3. Signal Extraction Fixes (extract_signals)
- Added label-based signal reading (external_traffic, service_type, nodePort)
- Added `_enrichment_signals` propagation (receives_external_traffic, is_alb_target)
- Added `iac_resource_type` reading from spec
- Added structural inference: gateway entities inherently receive external traffic

### 4. Entity Boundary Fix
- VPC and other foundation network entities (vpc, subnet, vnet patterns) are
  now protected from absorption. Only leaf network entities (security groups,
  NACLs, firewall rules) get absorbed.

### 5. Type Classification Fix
- Gateway type promotion now only confirms entities already bootstrapped as
  gateway (from IaC resource type). Services receiving ALB traffic remain
  services — they are ALB targets, not gateways.

## Current state of the ontology

```
69 entities after zoning:
  Tier 0: 5   (MSSQL CFI=28, PostgreSQL CFI=14, DocumentDB CFI=8,
                identity-service CFI=13, prod-alb FI=9)
  Tier 1: 35  (external-facing services, Cloudflare entries, RabbitMQ, log-mgmt)
  Tier 2: 9   (internal services with some dependents)
  Tier 3: 20  (Nexus internal services, infra, standalone)

  Types:
    service: 46, gateway: 13, datastore: 5, storage: 2,
    compute: 1, messagebus: 1, network: 1

  Domains:
    wincore-mssql (29): WinCore stack — MSSQL-anchored Orleans/.NET services
    app-postgres (14):  Nexus stack — PostgreSQL-anchored gRPC/HTTP services
    infrastructure (17): VPC, EKS, ALBs, Cloudflare, S3
    standalone (9):      cross-domain datastores, orphan services

  Natures:
    NUCLEUS: 3          (MSSQL, PostgreSQL, DocumentDB)
    CONDUIT: 1          (RabbitMQ)
    MEMBRANE: 13        (ALBs + Cloudflare DNS entries)
    PROCESSOR/SENTINEL: 1 (identity-service)
    PROCESSOR/REACTOR: 21 (WinCore services with fan-in + fan-out >= 3)
    PROCESSOR/WORKER: 26  (Nexus internal + low-connectivity services)
    SUBSTRATE: 4         (VPC, EKS, S3 x2)
```

## Key discoveries this session

1. **Gateway vs service distinction is critical**: Services receiving ALB traffic
   are NOT gateways. Gateways are IaC-defined boundary infrastructure (ALB, CDN).
   Services behind them are "ALB targets" — still processors.

2. **Foundation network entities must be protected**: VPC was being absorbed by
   the same rule that removes orphan security groups. Foundation detection
   (pattern-based: vpc/subnet/vnet) prevents this.

3. **Nature derivation validates structural signals**: identity-service correctly
   classified as SENTINEL (CFI=13, 2 protocols) purely from graph topology.
   Nexus services correctly classified as WORKER (FI=0, internal). No name
   matching needed anywhere.

4. **mssql-10-2-133-4 (CFI=2) is NOT a nucleus**: The secondary MSSQL instance
   has low critical fan-in. The engine correctly keeps it below the NUCLEUS
   threshold (CFI >= 3). It will be PROCESSOR/WORKER until more services
   critically depend on it.

## What to do next session

### Priority 1: Renderer update with nature-based geometry
Update `renderer/index.html` to use nature-specific shapes:
- NUCLEUS = SphereGeometry, size ∝ CFI
- CONDUIT = TubeGeometry spanning connected clusters
- MEMBRANE = arc/dome at domain perimeter
- SENTINEL = tall narrow CylinderGeometry (spire)
- REACTOR = hexagonal prism, height = tier
- WORKER = small BoxGeometry
- SUBSTRATE = ground plane / platform

Layout rules:
- Nucleus at domain center
- Processors orbit their nucleus (distance ∝ 1/dependency_criticality)
- Membranes at outer ring
- Substrate as ground plane
- Tier as Y-axis elevation

### Priority 2: Infra chain completion
- EKS managed node group parsing (nested block regex)
- Service → node group edges
- Monitoring services → monitoring node group (taint matching)

### Priority 3: Runtime event layer scaffold
- Event type taxonomy YAML
- OTel/Prometheus signal mapping to visual properties
- WebSocket infrastructure for live updates

## File locations

```
P:\Work\CityScope\cityscope-repo\
  bootstrap_real.py              — Bootstrap pipeline (Pass 1)
  run_pipeline.py                — Full pipeline orchestrator
  src/zoning/
    __init__.py
    engine.py                    — Zoning engine + nature classification
    enrichment.py                — Graph enrichment (edge discovery)
  docs/
    ZONING-CODE.md               — Platform-agnostic classification rules
    ENTITY-ONTOLOGY.md           — Five natures, forms, spatial layout
  ontology.json                  — Current real ontology (69 entities)
  declarations_zoned/            — Individual YAML per entity (post-zoning)
  renderer/index.html            — Three.js renderer (still uses old BoxGeometry)

P:\Work\CityScope\infra\          — Cloned BetCoreWin/infra repo
P:\Work\CityScope\betcorewin-cd\  — Cloned BetCoreWin/betcorewin-cd repo
```

## Commits
- `fcd2ea3` — feat: real bootstrap pipeline + zoning engine + graph enrichment
- `9971b48` — docs: entity ontology - five natures, forms, and spatial layout principles
- (pending) — feat: nature classification + domain semantic naming + signal extraction fixes
