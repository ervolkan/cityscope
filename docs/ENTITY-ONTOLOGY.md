---
title: "CityScope Entity Ontology — Forms & Natures"
version: "0.1.0"
kind: SemanticOntology
description: >
  Defines the fundamental natures of infrastructure entities and their
  visual forms. Each entity's nature is determined by its structural
  signals — what it does, not what it is called.
  
  Metaphor: This is not a human city. This is an autonomous station
  on an uninhabited world. Nothing here exists for human comfort —
  everything exists to process, store, transmit, or protect. Forms
  follow function at a molecular level, like elements in a periodic
  table.
---

# CityScope Entity Ontology — Forms & Natures

## 1. Philosophy

Every entity in the CityScope universe has a **nature** — a fundamental
behavioral identity determined by what it does, how it connects, and
what flows through it. Nature is not assigned by name. Nature emerges
from structure.

Like chemical elements, an entity's nature determines its form. Carbon
is carbon because of its atomic number, not its label. A datastore is
a datastore because it holds state and has high inbound write gravity,
not because someone named it "database."

The visual representation is a direct expression of nature. There is
no decorative layer — form IS function.


## 2. The Five Natures

Every infrastructure entity belongs to one of five fundamental natures.
These are not the entity types from the zoning code (service, datastore,
gateway, etc.) — those are structural classifications. Natures are
**behavioral essences** that determine visual form.

### 2.1 Signals that determine nature

Nature is derived from a combination of zoning signals:

| Signal | What it reveals |
|--------|----------------|
| Fan-in / Fan-out ratio | Is this entity a source, sink, or transformer? |
| Critical fan-in | Does failure cascade? Is this a gravity center? |
| External traffic | Does it interface with the outside? |
| Storage dependency count | Does it hold state or process state? |
| Protocol types | What kind of energy flows through it? |
| Async vs sync ratio | Does it work in real-time or deferred? |


### 2.2 Nature: Nucleus

**What it is**: A gravity center. Entities cluster around it. It holds
state that others depend on. Without it, entire sections of the system
collapse.

**Structural signature**:
- Critical fan-in >= 3
- Entity type: datastore, cache
- Storage targets: IS the storage target (others point TO it)
- Fan-out: near zero (it doesn't call others — others call it)

**Examples from real signals**: MSSQL instance (CFI=28), PostgreSQL
instance (CFI=14), DocumentDB cluster (CFI=8)

**Visual essence**: Dense, heavy, gravitational. A reactor core or
a dense mineral deposit. It does not move — everything orbits around
it. Its mass (visual size) is proportional to critical fan-in.
Pulsing glow indicates activity level. The heavier the nucleus, the
larger the gravitational field visualized around it.

**Form properties**:
- Shape: Sphere or truncated octahedron (dense packing)
- Size: Proportional to critical_fan_in (blast radius)
- Surface: Metallic, reflective — indicates stored energy
- Animation: Slow, deep pulse — breathing rhythm proportional to
  write throughput
- Field: Visible gravitational field lines to dependents, thicker
  lines = critical dependencies


### 2.3 Nature: Conduit

**What it is**: A transmission pathway. It does not create or store —
it moves things between other entities. Message brokers, event buses,
service meshes.

**Structural signature**:
- Entity type: messagebus
- Fan-in >= 3 with async dependency type
- Fan-out: zero or very low (it doesn't initiate — it relays)
- No storage dependencies of its own

**Examples from real signals**: RabbitMQ (FI=22, all async)

**Visual essence**: An energy conduit or pipeline network. Long,
horizontal, connecting — not a building but a **channel**. It is
the infrastructure between buildings, not a building itself. Visible
flow particles moving through it show message throughput.

**Form properties**:
- Shape: Horizontal tube/pipeline or elevated rail — spans between
  the entities it connects
- Size: Cross-section proportional to fan-in (throughput capacity)
- Surface: Translucent, with visible interior flow
- Animation: Particles flowing through the conduit, speed indicates
  message rate, color indicates queue depth (cool=healthy,
  warm=backing up)
- Position: Does not occupy a "plot" — it exists BETWEEN plots,
  as connective tissue


### 2.4 Nature: Membrane

**What it is**: A boundary interface. It separates inside from outside,
translates between protocols, filters and routes. Gateways, load
balancers, CDN edges.

**Structural signature**:
- Entity type: gateway
- Receives external traffic = true
- Fan-out > 0 (routes to backends)
- Fan-in from external sources (Cloudflare, DNS)

**Examples from real signals**: prod-alb (FI=9, routes to 20 services),
Cloudflare DNS entries

**Visual essence**: A protective shell or atmospheric boundary. Not a
wall but a **translucent dome** or energy shield at the perimeter of
the station. Traffic visibly passes through it, getting filtered and
routed. It is always at the edge — the outermost ring of the layout.

**Form properties**:
- Shape: Arc, dome section, or ring segment — not a box
- Size: Arc length proportional to the number of backends it routes to
- Surface: Semi-transparent with visible traffic passing through
- Animation: Incoming request particles hit the membrane and refract
  to their target services inside. Blocked requests scatter off.
- Position: Always on the perimeter of the domain it protects. If
  multiple membranes exist, they form concentric or adjacent arcs.


### 2.5 Nature: Processor

**What it is**: A worker. It takes input, transforms it, produces
output. The majority of services are processors — they receive
requests, do computation, call other services, write to storage,
return responses.

**Structural signature**:
- Entity type: service
- Fan-out > 0 (calls other services or writes to storage)
- Storage dependency count > 0 (reads/writes state)
- Has both inbound and outbound connections

**Sub-natures** (determined by signal ratios):

#### 2.5.1 Processor — Reactor

High throughput, many connections, transforms data actively.
- Fan-in >= 1 AND Fan-out >= 3
- Has autoscaling (dynamic capacity)
- Multiple protocol types (serves HTTP, gRPC, Orleans, etc.)

**Examples**: srv-betticket-service (FI=2, FO=11, 5 protocols, Orleans)

**Form**: Tall hexagonal prism with visible activity indicators.
Multiple antenna-like connection points on top. Internal energy
core visible through translucent panels. Height = tier importance,
width = connection count.

#### 2.5.2 Processor — Worker

Background processor, batch jobs, data pipeline steps. Low fan-in,
moderate fan-out, often no external exposure.
- Fan-in = 0 (no one calls it directly)
- Fan-out > 0 (it calls out to dependencies)
- No external traffic

**Examples**: Nexus services (nexus-customer, nexus-payment — currently
internal, no fan-in, write to PostgreSQL)

**Form**: Compact cubic unit with a single status indicator.
Functional, minimal. Like a processing module in a station —
does its job quietly. Smaller footprint than reactors.
Dim when idle, brightens when active.

#### 2.5.3 Processor — Sentinel

Auth, compliance, fraud detection, validation. Critical path
but narrow function. High critical fan-in because many services
MUST pass through it.
- Critical fan-in >= 5 (services wait for it in initContainers)
- Narrow protocol surface (usually just one: gRPC or HTTP)
- Functions as a gate — binary pass/fail

**Examples**: identity-service (CFI=13, all services wait for it)

**Form**: Tall, narrow spire or obelisk. A watchtower. Distinctive
silhouette — instantly recognizable from any angle. Beacon light
at top indicates operational status. Taller than most processors
but narrower footprint. The visual emphasis is on HEIGHT (authority)
not WIDTH (capacity).


### 2.6 Nature: Substrate

**What it is**: The ground itself. Networks, compute platforms,
storage volumes. Other entities exist ON it or WITHIN it, not
beside it.

**Structural signature**:
- Entity type: network, compute, storage
- Fan-in is mostly infra-type dependencies
- Serves as the platform for other natures

**Examples from real signals**: VPC (everything runs inside it),
EKS cluster (all services run on it), S3 buckets (static storage)

**Visual essence**: Not a building at all — the **terrain** itself.
VPC is the ground plane, subnets are zones within it, compute
nodes are platforms that buildings stand on. Storage volumes are
underground deposits — visible only as markers or hatched ground
areas.

**Form properties**:
- VPC/Network: The ground plane itself, with borders showing
  network boundaries. Different subnets = different ground textures
  or elevation levels.
- Compute: Raised platform or mesa — services physically sit on it.
  Node group size determines platform area.
- Object Storage: Subterranean — a hatch or marker on the ground
  indicating stored resources below. Not a building.
- Position: Always UNDER or AROUND other entities, never beside them
  as peers.


## 3. Nature Derivation Rules

Nature is computed from zoning signals, NOT from entity type alone.

```
IF critical_fan_in >= 3 AND entity_type IN (datastore, cache):
    nature = NUCLEUS

ELIF entity_type = messagebus AND fan_in >= 3:
    nature = CONDUIT

ELIF receives_external_traffic AND entity_type = gateway:
    nature = MEMBRANE

ELIF entity_type IN (network, compute, storage):
    nature = SUBSTRATE

ELIF entity_type = service:
    IF critical_fan_in >= 5:
        nature = SENTINEL
    ELIF fan_in >= 1 AND fan_out >= 3:
        nature = REACTOR
    ELSE:
        nature = WORKER
```


## 4. Spatial Layout Principles

These natures dictate where entities are placed relative to each other.

### 4.1 Gravity model

The layout uses a gravity metaphor:

- **Nuclei** are placed first. They are the anchors. Their position
  is fixed and central to the entities that depend on them.
- **Processors** orbit their nucleus — the storage they depend on
  determines their neighborhood. Distance from nucleus is inversely
  proportional to dependency criticality.
- **Conduits** are drawn as connections between neighborhoods, not
  as standalone objects. They run between the clusters they serve.
- **Membranes** form the outer boundary. They sit at the perimeter,
  facing outward.
- **Substrate** is the ground plane. It doesn't compete for space —
  everything sits on it.

### 4.2 Domain as neighborhood

The zoning code's domain-001, domain-002 become visible neighborhoods:

- Each domain's nucleus anchors its center.
- Processors in that domain cluster around their nucleus.
- The domain boundary is implicit — it's where the cluster density
  drops off.
- Conduits between domains create visible "roads" or "bridges."

### 4.3 Tier as elevation

Tier 0 entities are elevated — on higher ground or on raised platforms.
Tier 3 entities are at ground level or partially submerged. This gives
an immediate visual signal: look up = critical, look down = supporting.


## 5. Visual Signal Encoding

Beyond form and position, each entity carries real-time signal encodings:

| Visual property | What it encodes | Source |
|----------------|----------------|--------|
| Size (volume) | Blast radius / importance | critical_fan_in + fan_in |
| Height | Tier (criticality) | Zoning tier |
| Shape | Nature (behavioral role) | Nature derivation |
| Surface material | Entity type | Zoning type |
| Glow intensity | Current activity level | Runtime telemetry |
| Glow color | Health state | Runtime events |
| Connection lines | Dependencies | Dependency graph |
| Line thickness | Dependency criticality | critical flag |
| Line animation | Traffic flow | Runtime throughput |
| Ground texture | Network/subnet | Infrastructure topology |
| Elevation | Tier level | Zoning tier |
| Particle effects | Error rate / latency | Runtime SLO breach |


## 6. Versioning

| Version | Date | Change |
|---------|------|--------|
| 0.1.0 | 2025-05-07 | Initial draft — five natures, form definitions, layout principles |
