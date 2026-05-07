---
title: "CityScope Zoning Code"
version: "0.1.0"
kind: ZoningCode
description: >
  Platform-agnostic rules for classifying, tiering, and grouping
  infrastructure entities. No rule in this document may reference
  a specific product name, repository path, or service identifier.
  All classification derives from measurable structural signals
  extracted from IaC sources and dependency graph analysis.
---

# CityScope Zoning Code

## 1. Purpose

This document is the single source of truth for how CityScope classifies
entities. It replaces all hardcoded heuristics (regex patterns, name matching)
with **structural signal rules** — platform-agnostic, measurable, and
machine-evaluable.

Every rule follows one principle: **an entity's identity is determined by
what it does and how it connects, never by what it is called.**

A real-world zoning code says "this parcel allows commercial use at FAR 2.5"
— not "this parcel is for Starbucks." CityScope's zoning code works the
same way.

---

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Entity** | Any discrete infrastructure component with an independent lifecycle: a running process, a data store, a network boundary, a message broker. |
| **Signal** | A measurable, extractable property of an entity. Signals come from IaC declarations (static) or runtime telemetry (dynamic). |
| **Fan-in** | Number of other entities that declare a dependency on this entity. |
| **Critical fan-in** | Subset of fan-in where the dependency is marked `critical: true`. |
| **Fan-out** | Number of dependencies this entity declares on others. |
| **Blast radius** | Transitive closure of critical fan-in — all entities that would be affected if this entity fails. |
| **Storage cohort** | Set of entities that share the same storage dependency target. |
| **Tier** | Criticality classification (0–3). Derived from structural signals, not names. |
| **Domain** | Bounded context grouping. Derived from connectivity topology, not naming conventions. |
| **Entity type** | Functional classification (service, datastore, gateway, etc.). Derived from protocols, ports, and resource characteristics. |

---

## 3. Entity type classification

Entity type is the most fundamental classification. It determines the
base visual representation in the city and constrains which other rules
apply.

### 3.1 Type signals

Type is determined by examining the following signals in priority order.
The **first matching rule** wins.

#### Rule T-TYPE-01: Protocol-based classification

| Observed signal | Assigned type |
|----------------|---------------|
| Exposes port matching known database protocols (5432, 3306, 1433, 27017, 9042) AND has no outbound service dependencies (fan-out to non-infra = 0) | `datastore` |
| Exposes port matching cache protocols (6379, 11211) AND has no outbound service dependencies | `cache` |
| Exposes port matching message broker protocols (5672, 9092, 4222) AND has no outbound service dependencies | `messagebus` |
| Source is an object storage resource (S3, GCS, Azure Blob) identified by IaC resource type | `storage` |
| Source is a network boundary resource (VPC, subnet, security group, firewall rule) identified by IaC resource type | `network` |
| Source is a compute resource (cluster, node group, VM, instance) identified by IaC resource type | `compute` |
| Receives external traffic (NodePort, LoadBalancer service type, or ingress resource) AND fan-out > 0 (routes to backends) | `gateway` |
| Default for any entity that exposes HTTP/gRPC/TCP ports and has outbound dependencies | `service` |

#### Rule T-TYPE-02: IaC resource type mapping

When an entity is extracted from IaC (Terraform, Pulumi, CloudFormation),
the resource type provides a definitive signal:

| IaC resource pattern | Assigned type |
|---------------------|---------------|
| `*_vpc`, `*_subnet`, `*_route_table`, `*_security_group`, `*_firewall*` | `network` |
| `*_db_instance`, `*_rds_*`, `*_docdb_*`, `*_dynamodb_*`, `*_sql_*` | `datastore` |
| `*_elasticache_*`, `*_memorydb_*` | `cache` |
| `*_msk_*`, `*_mq_*`, `*_sqs_*`, `*_sns_*`, `*_eventbridge_*` | `messagebus` |
| `*_s3_bucket*`, `*_storage_bucket*`, `*_blob_*` | `storage` |
| `*_eks_*`, `*_ecs_*`, `*_instance`, `*_launch_template*`, `*_node_group*` | `compute` |
| `*_lb`, `*_alb`, `*_nlb`, `*_api_gateway*`, `*_cloudfront*`, `*_cdn*` | `gateway` |
| `cloudflare_record`, `*_dns_record*` | See Rule T-TYPE-03 |

#### Rule T-TYPE-03: Entity boundary — when a resource is NOT a separate entity

Not every IaC resource becomes a CityScope entity. A resource is an
**attribute** of its parent entity (not a standalone entity) when:

1. **DNS records**: A DNS record pointing to a gateway (ALB, CDN) is an
   attribute of that gateway, not a separate entity. Multiple DNS records
   pointing to the same target are collapsed into the target entity's
   metadata.

2. **Security groups**: A security group attached to exactly one compute
   or service entity is an attribute of that entity. Only shared security
   groups (attached to multiple entities) become standalone network entities.

3. **IAM roles/policies**: Never standalone entities. They are attributes
   of the entity they serve (via IRSA, instance profile, etc.).

4. **Subnets**: Subnets within a VPC are attributes of the VPC entity
   unless they carry distinct workloads (e.g., a dedicated monitoring subnet
   with isolated traffic).

**Collapsing rule**: When multiple IaC resources map to the same logical
function (e.g., 10 Cloudflare DNS records all pointing to the same ALB),
they collapse into a single entity with a `count` metadata field.

---

## 4. Tier classification

Tier (0–3) measures **criticality** — the impact of this entity's failure
on the overall system. Tier is computed, not assigned by name.

### 4.1 Tier signals

The following signals are extracted from the dependency graph and IaC
configuration:

| Signal | Symbol | Source |
|--------|--------|--------|
| Fan-in count | `FI` | Dependency graph |
| Critical fan-in count | `CFI` | Dependency graph (critical=true edges) |
| Blast radius size | `BR` | Transitive closure of critical fan-in |
| Has external ingress | `EXT` | Service type=NodePort/LoadBalancer, or ingress resource, or gateway routes to it |
| Autoscaling enabled | `HPA` | IaC scaling configuration |
| Replica count | `RC` | IaC replica/desired count |
| Has SLO defined | `SLO` | IaC or annotation |
| Entity type | `TYPE` | From section 3 |

### 4.2 Tier rules

Tier is determined by evaluating rules top-down. **First match wins.**

#### Rule T-TIER-01: Tier 0 — Critical path

An entity is Tier 0 if **any** of the following conditions is true:

- `CFI >= 5` — Five or more entities critically depend on it. Its failure
  causes widespread cascade.
- `TYPE = datastore AND CFI >= 3` — A data store with three or more
  critical dependents is a single point of failure for a significant
  portion of the system.
- `TYPE = gateway AND EXT = true AND FI >= 3` — An external-facing
  gateway routing to three or more backends. Loss means total external
  outage for those services.

**Rationale**: Tier 0 means "if this entity fails, customers notice
immediately and broadly." The signals measure exactly that — cascade
breadth and external exposure.

#### Rule T-TIER-02: Tier 1 — Important

An entity is Tier 1 if **any** of the following is true:

- `CFI >= 1 AND CFI < 5` — At least one critical dependent, but
  limited blast radius.
- `FI >= 5 AND CFI = 0` — Many non-critical dependents. Failure
  degrades but doesn't break the system.
- `TYPE = messagebus AND FI >= 3` — A message broker with significant
  fan-in. Async failures are less immediate but still impactful.
- `TYPE = compute AND` hosts Tier 0 or Tier 1 workloads — A compute
  node that runs critical services inherits their criticality.
- `EXT = true AND FI >= 1` — Receives external traffic and routes
  to at least one backend.

#### Rule T-TIER-03: Tier 2 — Supporting

An entity is Tier 2 if **any** of the following is true:

- `FI >= 1 AND FI < 5 AND CFI = 0` — Has dependents but none are critical.
- `TYPE IN (storage, network) AND` attached to Tier 0/1 entities — Supporting
  infrastructure for important workloads.
- Default tier for any entity with `FI >= 1` that doesn't match Tier 0 or 1.

#### Rule T-TIER-04: Tier 3 — Non-critical

An entity is Tier 3 if:

- `FI = 0 AND EXT = false` — Nobody depends on it and it has no external
  exposure. Its failure affects nothing else.
- `TYPE IN (network, storage) AND` all attached entities are Tier 2+.

### 4.3 Tier propagation (second pass)

After initial tier assignment, a **propagation pass** adjusts tiers based
on dependency chains:

**Upward propagation**: If an entity at Tier N has a `critical: true`
dependency on an entity currently at Tier M where M > N, the dependency's
tier is promoted to min(N, M). In other words: if a Tier 0 entity critically
depends on a Tier 2 entity, that Tier 2 entity is promoted to at least
Tier 1.

**Downward constraint**: An entity's tier can never be *lower* (more
critical) than its most critical dependent's tier minus 1. A Tier 2 entity
that is critically depended upon by a Tier 0 entity must become at least
Tier 1.

The propagation pass runs iteratively until no more changes occur
(fixed-point convergence).

---

## 5. Domain classification

Domains are bounded contexts — groups of entities that change together
and share data coupling. Domain boundaries are derived from **connectivity
topology**, not naming conventions.

### 5.1 Domain signals

| Signal | Description |
|--------|------------|
| **Storage cohort** | Entities sharing the same storage dependency form a natural domain cluster. If entity A and entity B both depend on the same datastore, they are data-coupled. |
| **Sync call cluster** | Entities connected by synchronous (gRPC, HTTP) dependencies form call chains. Dense mutual connectivity suggests same domain. |
| **Gateway boundary** | A gateway entity and the services it routes to form a domain boundary — the gateway is the "edge" of that domain. |
| **Infrastructure boundary** | Entities in the same VPC/subnet/cluster share an infrastructure domain. |

### 5.2 Domain derivation algorithm

Domain assignment uses a two-phase approach:

#### Phase 1: Storage cohort clustering

1. For each storage entity (datastore, cache), collect all entities that
   depend on it. This forms a **storage cohort**.
2. If a storage cohort maps to a single logical database (same host,
   same port, but different database names within it), each distinct
   database name forms a **sub-cohort**.
3. Entities that share the same sub-cohort are placed in the same domain
   candidate group.

#### Phase 2: Sync topology refinement

1. Within each storage cohort, examine sync (gRPC/HTTP) call patterns.
2. If a subset of entities in the cohort has dense mutual sync calls
   (forms a clique or near-clique), they are a strong domain candidate.
3. Entities that bridge two storage cohorts (depend on storage in
   cohort A and have sync calls to entities in cohort B) are **boundary
   entities** — assigned to the cohort where they have storage dependency
   (data gravity wins).

#### Phase 3: Infrastructure entities

Infrastructure entities (network, compute, storage, gateway) are
assigned to a special `infrastructure` domain unless they are
exclusively used by a single application domain, in which case they
inherit that domain.

### 5.3 Domain naming

Domains are named automatically based on their dominant characteristics:

- The name is derived from the most common **database name pattern** in
  the storage cohort, or the most connected entity's functional role.
- Domain names are slugified identifiers (e.g., `domain-001`,
  `domain-002`) until a human operator assigns semantic names.
- The zoning code does not dictate domain names — it dictates domain
  **boundaries**.

---

## 6. Entity boundary rules

These rules determine what becomes a standalone entity vs. what gets
absorbed as metadata of a parent entity.

### 6.1 Standalone entity criteria

A resource becomes a standalone CityScope entity if it has **at least one**
of:

1. **Independent lifecycle**: It can be deployed, scaled, or destroyed
   independently of other entities (has its own deployment manifest,
   Terraform resource, or Helm release).
2. **Independent failure mode**: Its failure doesn't necessarily coincide
   with another entity's failure (separate process, separate host, or
   separate availability zone).
3. **Fan-in >= 1**: At least one other entity depends on it.

### 6.2 Absorption criteria

A resource is absorbed into its parent entity's metadata if **all** of:

1. Its lifecycle is fully coupled to the parent (created/destroyed together).
2. It has no independent fan-in (nothing depends on it that doesn't
   also depend on the parent).
3. It serves a single parent entity exclusively.

**Examples of absorption**:
- DNS records → absorbed into the gateway they point to.
- Security groups serving one entity → absorbed into that entity.
- IAM roles/policies → absorbed into the entity they serve.
- Sidecar containers → absorbed into the main service entity.

### 6.3 Collapse criteria

Multiple IaC resources that represent the **same logical function** are
collapsed into a single entity:

- Multiple DNS records pointing to the same target → single gateway entity
  with `aliases: [list]` metadata.
- Multiple read replicas of a database → single datastore entity with
  `replicas: N` in scaling metadata.
- Multiple AZs of the same subnet → single network entity with
  `availability_zones: [list]` metadata.

---

## 7. Dependency classification

Dependencies between entities are classified by type and criticality.

### 7.1 Dependency type rules

| Observed signal | Dependency type |
|----------------|----------------|
| Target entity type = `datastore` or `cache` | `storage` or `cache` |
| Target entity type = `messagebus` | `async` |
| Protocol is synchronous (HTTP, gRPC, TCP with request-response) | `sync` |
| Target entity type = `network`, `compute`, or `storage` (object) | `infra` |

### 7.2 Criticality rules

A dependency is `critical: true` when **any** of:

1. **Storage write path**: The source entity writes to the target
   datastore (connection string contains write credentials or the
   source is the only writer).
2. **Startup dependency**: The source declares an init-container or
   readiness probe that waits for the target.
3. **Sync call without fallback**: The source makes synchronous calls
   to the target and has no circuit breaker, retry-with-fallback, or
   graceful degradation configured.

A dependency is `critical: false` when:

1. **Async communication**: Messages go through a broker — the source
   can continue operating if the target is temporarily unavailable.
2. **Read replica**: The source reads from a replica; primary failure
   doesn't affect it directly.
3. **Observability dependency**: OTel collectors, log aggregators —
   failure means loss of telemetry, not loss of function.

---

## 8. Implementation contract

The bootstrap pipeline MUST implement these rules as follows:

### 8.1 Two-pass architecture

**Pass 1 — Signal extraction**: Parse IaC sources and extract raw
signals: ports, protocols, resource types, connection strings, environment
variables, scaling config. No classification happens in this pass —
only signal collection.

**Pass 2 — Rule evaluation**: Apply zoning rules from this document
to the extracted signals. Tier, domain, and type are all computed in
this pass using the rules above. No hardcoded names, regex patterns
matching product names, or platform-specific heuristics are permitted.

### 8.2 Override mechanism

Human operators can override any computed classification by adding
an `overrides` section to an entity's declaration file:

```yaml
overrides:
  tier: 0           # operator override, reason required
  domain: payments   # operator-assigned domain name
  reason: "Customer-facing payment gateway, business-critical"
```

Overrides always win over computed values. The bootstrap pipeline
preserves existing overrides when re-running.

### 8.3 Audit trail

Every computed classification must be accompanied by a `_signals`
metadata section showing which signals led to the decision:

```yaml
_signals:
  tier:
    computed: 1
    rule: T-TIER-02
    signals:
      fan_in: 8
      critical_fan_in: 2
      blast_radius: 12
      external_ingress: false
      has_hpa: true
  domain:
    computed: domain-003
    rule: storage-cohort
    signals:
      storage_targets: ["postgres-10.2.159.193"]
      cohort_size: 14
```

This enables operators to understand *why* a classification was made
and to provide informed overrides.

---

## 9. Versioning

This document is versioned. When rules change, the version number
increments and the bootstrap pipeline re-evaluates all entities
against the new rules. Previous classifications are preserved in
the audit trail for comparison.

| Version | Date | Change |
|---------|------|--------|
| 0.1.0 | 2025-05-07 | Initial draft — structural signal rules for tier, domain, type |
