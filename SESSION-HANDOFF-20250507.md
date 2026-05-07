# CityScope Session Handoff — 2025-05-07 (Session 3)

## What we built this session

### 1. Nature-Based Renderer (renderer/index.html — full rewrite)
Replaced flat grid BoxGeometry layout with nature-aware 3D city:

**Geometry per nature:**
- NUCLEUS → SphereGeometry, radius ∝ log₂(CFI) — MSSQL (CFI=28) is the biggest sphere
- CONDUIT → OctahedronGeometry, radius ∝ log₂(FI) — RabbitMQ diamond
- MEMBRANE → CylinderGeometry(1.8, 2.0, 0.8, 16) — thin disc for ALB/Cloudflare
- SUBSTRATE → BoxGeometry(4, 0.6, 4) — flat platform for VPC/EKS/S3
- SENTINEL → CylinderGeometry(0.5, 0.7, h, 8) — tall narrow spire, h ∝ log₂(CFI)
- REACTOR → CylinderGeometry(1.1, 1.1, h, 6) — hexagonal prism, height by tier
- WORKER → BoxGeometry(1.4, h, 1.4) — small box, height by tier

**Domain cluster layout:**
- 4 domains = 4 neighborhoods (circular ground plates with border rings)
- standalone (cx:0, cz:0), wincore-mssql (cx:-38, cz:20), app-postgres (cx:38, cz:20), infrastructure (cx:0, cz:-35)
- Concentric orbital placement within each domain:
  - Nucleus → center
  - Conduit/Sentinel → near center (r=5-6)
  - Reactor → inner orbit (radius × 0.45)
  - Worker → outer orbit (radius × 0.7)
  - Membrane → perimeter (radius × 0.92)
  - Substrate → ground level

**Visual enhancements:**
- NUCLEUS: animated glow ring (TorusGeometry, pulsing opacity + rotation)
- SENTINEL: beacon sphere on top (pulsing emissive)
- Wireframe overlay on all entities
- Nature-colored labels per entity
- Tooltip shows nature badge, FI/CFI/Blast radius, dependency list with ⚡/→ markers
- Legend: nature shapes + domain ground colors
- Stats panel: by nature + by domain breakdown

**Preserved from v1:** Event bridge WebSocket, alert overlays, TAXONOMY, live event feed

### 2. Gravitational Pull — Domain Assignment Fix (engine.py)
Added a gravitational pull phase to `classify_domains()` that pulls standalone
entities into their natural domain based on dependency topology:

**Problem:** Datastores (MSSQL, PostgreSQL, DocumentDB) and orphan services
(srv-cashout-grpc, srv-cashout-provider-service) ended up in `standalone`
because they have no `storage_targets` of their own, so union-find couldn't
cluster them with their dependents.

**Solution:** After initial domain assignment, iterate over standalone entities
and collect "domain votes" from two directions:
- **Reverse:** who depends on me? (critical deps = 2 votes, normal = 1 vote)
- **Forward:** who do I depend on? (1 vote per target)
If one domain has >50% of votes, pull the entity there.

**Key design decisions:**
- Datastore/cache: only count critical dependents (strong gravity — data is critical)
- Messagebus: count all dependents (async = weaker but still gravity)
- Services: count all dependents + forward deps
- Iterative (3 passes): first pass pulls datastores, second pass pulls orphan services
  that now have forward deps into the newly-pulled datastore's domain (domino effect)

**Result:**
- mssql-10-2-152-240 (CFI=28) → wincore-mssql (was standalone)
- postgres-10-2-159-193 (CFI=14) → app-postgres (was standalone)
- prod-docdb (CFI=8) → wincore-mssql (was standalone)
- mssql-10-2-133-4 (CFI=2) → wincore-mssql (was standalone)
- srv-cashout-grpc → wincore-mssql (was standalone, 1 dependent in wincore)
- srv-cashout-provider-service → wincore-mssql (was standalone, 3 dependents in wincore)
- rabbitmq, stage, srv-betdatasource-grpc → remain standalone (no dominant pull)

## Current state of the ontology

```
69 entities after zoning:

  Domains (post-gravitational-pull):
    wincore-mssql: ~34  (was 29 — gained MSSQL, DocDB, secondary MSSQL, 2 cashout services)
    infrastructure: 17  (unchanged)
    app-postgres:  ~15  (was 14 — gained PostgreSQL)
    standalone:    ~3   (rabbitmq, stage, betdatasource-grpc)

  Natures:
    NUCLEUS: 3          (MSSQL, PostgreSQL, DocumentDB — now inside their domains)
    CONDUIT: 1          (RabbitMQ)
    MEMBRANE: 13        (ALBs + Cloudflare DNS entries)
    PROCESSOR/SENTINEL: 1 (identity-service)
    PROCESSOR/REACTOR: 21
    PROCESSOR/WORKER: ~26
    SUBSTRATE: 4         (VPC, EKS, S3 x2)
```

## Key discoveries this session

1. **Datastores must be inside their dependent domain, not standalone**: The
   "city metaphor" breaks when the database sits outside the neighborhood it
   serves. Gravitational pull fixes this by using dependency topology as mass.

2. **Iterative pull enables cascading**: Pulling MSSQL into wincore-mssql in
   pass 1 creates forward-dep votes for srv-cashout-grpc in pass 2. Without
   iteration, orphan services with only forward deps stay stranded.

3. **Nature-based geometry makes city instantly readable**: You can see at a
   glance which entities are critical (big red spheres), which are boundary
   (green discs at perimeter), which are workhorses (purple hexagons in orbit).
   The old BoxGeometry grid conveyed none of this.

4. **Domain plates create spatial memory**: The circular ground plates establish
   neighborhoods. Once you know "wincore is southwest, nexus is east", you
   develop spatial intuition — same as navigating a real city.

## What to do next session

### Priority 1: Namespace extraction (separate PR)
- Parse ArgoCD/Flux Application manifests for `spec.destination.namespace`
- Or heuristic: nexus-* → nexus ns, bo-*/srv-*/identity-* → wincore ns
- Add `metadata.namespace` to entity declarations
- Use as validation signal for domain assignment

### Priority 2: Infra chain completion
- EKS managed node group parsing (nested block regex)
- Service → node group edges
- Monitoring services → monitoring node group (taint matching)

### Priority 3: Runtime event layer scaffold
- Event type taxonomy YAML
- OTel/Prometheus signal mapping to visual properties
- WebSocket infrastructure for live updates

### Priority 4: Renderer refinements
- Domain plate overlap fix (adjust DOMAIN_CONFIG coordinates based on entity count)
- Dependency line filtering (show/hide by type, critical-only toggle)
- Camera presets (fly to domain, fly to entity)
- Click-to-select with dependency highlighting

## File changes this session

```
Modified:
  src/zoning/engine.py           — Gravitational pull in classify_domains()
  renderer/index.html            — Full rewrite: nature geometry + domain layout

Unchanged:
  bootstrap_real.py
  run_pipeline.py
  src/zoning/enrichment.py
  docs/ZONING-CODE.md
  docs/ENTITY-ONTOLOGY.md
```

## Commits
- `fcd2ea3` — feat: real bootstrap pipeline + zoning engine + graph enrichment
- `9971b48` — docs: entity ontology - five natures, forms, and spatial layout principles
- (PR #10) — feat: nature classification + domain semantic naming + signal extraction fixes
- (this session) — feat: nature-based renderer + gravitational pull domain assignment
