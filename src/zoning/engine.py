"""
CityScope Zoning Engine
========================
Implements the two-pass architecture defined in ZONING-CODE.md:
  Pass 1 — Signal extraction (raw signals from IaC)
  Pass 2 — Rule evaluation (tier, domain, type, nature, entity boundaries)

Nature derivation (Entity Ontology §3) adds a semantic layer:
  NUCLEUS | CONDUIT | MEMBRANE | PROCESSOR (reactor/worker/sentinel) | SUBSTRATE

This module is platform-agnostic. It operates on the entity list and
dependency graph produced by the bootstrap pipeline. No service names,
product names, or repo paths appear in any rule.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re
from collections import Counter


# ---------------------------------------------------------------------------
# Signal model — raw measurable properties per entity
# ---------------------------------------------------------------------------

@dataclass
class EntitySignals:
    """Raw structural signals extracted from IaC and graph analysis."""
    entity_id: str

    # Graph signals (computed after all entities are collected)
    fan_in: int = 0
    critical_fan_in: int = 0
    fan_out: int = 0
    blast_radius: int = 0

    # IaC signals (extracted from source)
    exposed_ports: list[int] = field(default_factory=list)
    exposed_protocols: list[str] = field(default_factory=list)  # http, grpc, postgres, amqp...
    iac_resource_type: str = ""            # e.g. aws_docdb_cluster, aws_lb, aws_vpc
    service_type: str = ""                 # ClusterIP, NodePort, LoadBalancer
    node_port: Optional[int] = None        # if service_type=NodePort
    has_autoscaling: bool = False
    replica_count: int = 0
    has_init_containers: bool = False
    has_slo: bool = False

    # Ingress signals
    receives_external_traffic: bool = False  # ALB routes to it, or NodePort in app_list
    is_alb_target: bool = False              # explicitly in an ALB target group

    # Storage signals
    storage_targets: list[str] = field(default_factory=list)     # datastore entity IDs this depends on
    shared_storage_cohort_size: int = 0                          # how many entities share the same storage

    # Dependency detail
    sync_dependency_count: int = 0
    async_dependency_count: int = 0
    storage_dependency_count: int = 0
    infra_dependency_count: int = 0


# ---------------------------------------------------------------------------
# Pass 1: Signal Extraction — compute graph signals from entity list
# ---------------------------------------------------------------------------

def extract_signals(entities: dict, edges: list[dict]) -> dict[str, EntitySignals]:
    """
    Given a dict of entities {id: entity_dict} and a list of edge dicts,
    compute all structural signals for each entity.
    """
    signals: dict[str, EntitySignals] = {}

    # Initialize signals for every known entity
    for eid in entities:
        signals[eid] = EntitySignals(entity_id=eid)

    # Also create signals for implicit targets (dependency targets not in entities)
    for edge in edges:
        for target in [edge.get("source", ""), edge.get("target", "")]:
            if target and target not in signals:
                signals[target] = EntitySignals(entity_id=target)

    # --- Fan-in / fan-out ---
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        is_critical = edge.get("critical", False)
        dep_type = edge.get("type", "")

        if source in signals:
            signals[source].fan_out += 1
            if dep_type == "sync":
                signals[source].sync_dependency_count += 1
            elif dep_type == "async":
                signals[source].async_dependency_count += 1
            elif dep_type == "storage":
                signals[source].storage_dependency_count += 1
                signals[source].storage_targets.append(target)
            elif dep_type == "infra":
                signals[source].infra_dependency_count += 1

        if target in signals:
            signals[target].fan_in += 1
            if is_critical:
                signals[target].critical_fan_in += 1

    # --- Blast radius (transitive critical fan-in) ---
    # Build reverse critical graph
    critical_reverse: dict[str, list[str]] = {eid: [] for eid in signals}
    for edge in edges:
        if edge.get("critical"):
            target = edge.get("target", "")
            source = edge.get("source", "")
            if target in critical_reverse:
                critical_reverse[target].append(source)

    for eid in signals:
        visited = set()
        queue = [eid]
        while queue:
            node = queue.pop()
            for dependent in critical_reverse.get(node, []):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)
        signals[eid].blast_radius = len(visited)

    # --- Storage cohort size ---
    # Group entities by shared storage targets
    storage_to_users: dict[str, list[str]] = {}
    for eid, sig in signals.items():
        for st in sig.storage_targets:
            if st not in storage_to_users:
                storage_to_users[st] = []
            storage_to_users[st].append(eid)

    for eid, sig in signals.items():
        max_cohort = 0
        for st in sig.storage_targets:
            cohort_size = len(storage_to_users.get(st, []))
            if cohort_size > max_cohort:
                max_cohort = cohort_size
        sig.shared_storage_cohort_size = max_cohort

    # --- IaC signals (from entity dict) ---
    for eid, e in entities.items():
        sig = signals[eid]
        spec = e.get("spec", {})

        # Protocols/ports
        for proto in spec.get("protocols", []):
            port = proto.get("port")
            name = proto.get("name", "")
            if port:
                sig.exposed_ports.append(port)
            if name:
                sig.exposed_protocols.append(name)

        # Scaling
        scaling = spec.get("scaling", {})
        if scaling.get("strategy") == "hpa":
            sig.has_autoscaling = True
        sig.replica_count = scaling.get("current_replicas", 0)

        # SLO
        if spec.get("slo"):
            sig.has_slo = True

        # Labels for init containers detection
        labels = e.get("metadata", {}).get("labels", {})

        # External traffic signals (from enrichment or bootstrap labels)
        if labels.get("external_traffic") == "true":
            sig.receives_external_traffic = True
        if labels.get("service_type"):
            sig.service_type = labels["service_type"]
        if labels.get("nodePort"):
            try:
                sig.node_port = int(labels["nodePort"])
            except (ValueError, TypeError):
                pass

        # Enrichment signals (set by enrichment.py)
        esig = e.get("_enrichment_signals", {})
        if esig.get("receives_external_traffic"):
            sig.receives_external_traffic = True
        if esig.get("is_alb_target"):
            sig.is_alb_target = True

        # IaC resource type (set by terraform parser)
        if e.get("spec", {}).get("iac_resource_type"):
            sig.iac_resource_type = e["spec"]["iac_resource_type"]

        # Structural inference: gateway entities inherently receive external traffic
        # ALBs, NLBs, CDN edges are boundary interfaces by definition in IaC.
        # If enrichment didn't set the flag, infer from entity type + fan-out.
        current_type = spec.get("type", "")
        if current_type == "gateway" and not sig.receives_external_traffic:
            # Gateway with outbound edges (routes traffic) = external-facing
            # Gateway without edges might be a DNS record (handled by absorption)
            sig.receives_external_traffic = True

        # (init container presence is signaled by critical sync deps with "initContainer" description)
        for dep in spec.get("depends_on", []):
            desc = dep.get("description", "")
            if "initcontainer" in desc.lower() or "init container" in desc.lower():
                sig.has_init_containers = True
                break

    return signals


# ---------------------------------------------------------------------------
# Pass 2a: Entity Type Classification (Zoning Code §3)
# ---------------------------------------------------------------------------

# IaC resource type → entity type mapping (T-TYPE-02)
IAC_TYPE_MAP = {
    # Network
    "vpc": "network", "subnet": "network", "route_table": "network",
    "security_group": "network", "firewall": "network", "nacl": "network",
    # Datastore
    "db_instance": "datastore", "rds": "datastore", "docdb": "datastore",
    "dynamodb": "datastore", "sql": "datastore", "aurora": "datastore",
    # Cache
    "elasticache": "cache", "memorydb": "cache",
    # Message bus
    "msk": "messagebus", "mq": "messagebus", "sqs": "messagebus",
    "sns": "messagebus", "eventbridge": "messagebus",
    # Storage
    "s3_bucket": "storage", "storage_bucket": "storage", "blob": "storage",
    # Compute
    "eks": "compute", "ecs": "compute", "instance": "compute",
    "launch_template": "compute", "node_group": "compute",
    # Gateway
    "lb": "gateway", "alb": "gateway", "nlb": "gateway",
    "api_gateway": "gateway", "cloudfront": "gateway", "cdn": "gateway",
}

# Known database ports (T-TYPE-01)
DB_PORTS = {5432, 3306, 1433, 27017, 9042, 1521, 3050}
CACHE_PORTS = {6379, 11211}
BROKER_PORTS = {5672, 9092, 4222, 6650}


def classify_type(sig: EntitySignals, current_type: str) -> str:
    """
    Apply T-TYPE-01 and T-TYPE-02 rules.
    Returns the computed entity type.
    """
    # T-TYPE-02: IaC resource type wins if known
    if sig.iac_resource_type:
        for pattern, etype in IAC_TYPE_MAP.items():
            if pattern in sig.iac_resource_type.lower():
                return etype

    # T-TYPE-01: Protocol-based
    ports_set = set(sig.exposed_ports)
    proto_set = set(p.lower() for p in sig.exposed_protocols)

    # Datastore: exposes DB port AND no outbound service deps
    if ports_set & DB_PORTS and sig.sync_dependency_count == 0:
        return "datastore"

    # Cache: exposes cache port AND no outbound service deps
    if ports_set & CACHE_PORTS and sig.sync_dependency_count == 0:
        return "cache"

    # Messagebus: exposes broker port AND no outbound service deps
    if ports_set & BROKER_PORTS and sig.sync_dependency_count == 0:
        return "messagebus"

    # Gateway: receives external traffic AND has fan-out (routes to backends)
    # IMPORTANT: Only promote to gateway if the entity was ORIGINALLY bootstrapped
    # as a gateway (from IaC resource type). Services that receive traffic via ALB
    # are still services — they are ALB targets, not gateways themselves.
    # This rule only applies to entities whose current_type is already gateway.
    if current_type == "gateway" and sig.receives_external_traffic and sig.fan_out > 0:
        return "gateway"

    # Gateway: NodePort or LoadBalancer service type with fan-out
    # Same principle — only confirm gateway if already typed as such.
    if current_type == "gateway" and sig.service_type in ("NodePort", "LoadBalancer") and sig.fan_out > 0:
        return "gateway"

    # Default: keep existing if set, otherwise service
    return current_type if current_type else "service"


# ---------------------------------------------------------------------------
# Pass 2b: Tier Classification (Zoning Code §4)
# ---------------------------------------------------------------------------

def classify_tier(sig: EntitySignals, entity_type: str) -> tuple[int, str]:
    """
    Apply T-TIER-01 through T-TIER-04 rules.
    Returns (tier, rule_id).
    """
    fi = sig.fan_in
    cfi = sig.critical_fan_in
    ext = sig.receives_external_traffic or sig.is_alb_target

    # T-TIER-01: Tier 0 — Critical path
    if cfi >= 5:
        return 0, "T-TIER-01: critical_fan_in >= 5"
    if entity_type == "datastore" and cfi >= 3:
        return 0, "T-TIER-01: datastore with critical_fan_in >= 3"
    if entity_type == "gateway" and ext and fi >= 3:
        return 0, "T-TIER-01: external gateway with fan_in >= 3"

    # T-TIER-02: Tier 1 — Important
    if 1 <= cfi < 5:
        return 1, "T-TIER-02: critical_fan_in 1-4"
    if fi >= 5 and cfi == 0:
        return 1, "T-TIER-02: fan_in >= 5, non-critical"
    if entity_type == "messagebus" and fi >= 3:
        return 1, "T-TIER-02: messagebus with fan_in >= 3"
    if ext and fi >= 1:
        return 1, "T-TIER-02: external ingress with fan_in >= 1"
    if ext and fi == 0 and sig.fan_out > 0:
        # External-facing leaf service (receives traffic, calls backends)
        return 1, "T-TIER-02: external-facing service"

    # T-TIER-03: Tier 2 — Supporting
    if fi >= 1 and cfi == 0:
        return 2, "T-TIER-03: has dependents, none critical"
    if fi >= 1:
        return 2, "T-TIER-03: has dependents"

    # T-TIER-04: Tier 3 — Non-critical
    return 3, "T-TIER-04: no dependents, no external traffic"


def propagate_tiers(
    entities: dict,
    signals: dict[str, EntitySignals],
    edges: list[dict],
    tiers: dict[str, int],
) -> dict[str, int]:
    """
    Tier propagation pass (Zoning Code §4.3).
    If a Tier N entity critically depends on a Tier M entity where M > N+1,
    promote the dependency.
    """
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for edge in edges:
            if not edge.get("critical"):
                continue
            source = edge.get("source", "")
            target = edge.get("target", "")
            if source not in tiers or target not in tiers:
                continue

            source_tier = tiers[source]
            target_tier = tiers[target]

            # If source is more critical than target, promote target
            max_allowed = source_tier + 1
            if target_tier > max_allowed:
                tiers[target] = max_allowed
                changed = True

    return tiers


# ---------------------------------------------------------------------------
# Pass 2b.2: Nature Classification (Entity Ontology §3)
# ---------------------------------------------------------------------------

def classify_nature(sig: EntitySignals, entity_type: str) -> tuple[str, str, str]:
    """
    Derive the behavioral nature from structural signals.
    Implements ENTITY-ONTOLOGY.md §3 derivation rules.

    Returns (nature, sub_nature, rule_id).
    nature:     NUCLEUS | CONDUIT | MEMBRANE | PROCESSOR | SUBSTRATE
    sub_nature: (empty for non-processors) | REACTOR | WORKER | SENTINEL
    """
    fi = sig.fan_in
    cfi = sig.critical_fan_in
    fo = sig.fan_out
    ext = sig.receives_external_traffic

    # Rule N-01: Nucleus — gravity centers (datastores/caches with high CFI)
    if cfi >= 3 and entity_type in ("datastore", "cache"):
        return "NUCLEUS", "", "N-01: datastore/cache with critical_fan_in >= 3"

    # Rule N-02: Conduit — transmission pathways (message brokers)
    if entity_type == "messagebus" and fi >= 3:
        return "CONDUIT", "", "N-02: messagebus with fan_in >= 3"

    # Rule N-03: Membrane — boundary interfaces (external gateways)
    if ext and entity_type == "gateway":
        return "MEMBRANE", "", "N-03: external gateway"

    # Rule N-04: Substrate — infrastructure ground plane
    if entity_type in ("network", "compute", "storage"):
        return "SUBSTRATE", "", "N-04: infrastructure entity (network/compute/storage)"

    # Rule N-05: Processor sub-natures (services and remaining entities)

    # N-05c: Sentinel — critical auth gate, narrow function, many wait on it
    #   CFI >= 5 means many services critically depend (e.g. initContainer wait)
    #   Narrow protocol surface = few exposed protocol types
    if cfi >= 5 and len(set(sig.exposed_protocols)) <= 2:
        return "PROCESSOR", "SENTINEL", "N-05c: critical_fan_in >= 5, narrow protocol surface"

    # N-05a: Reactor — high throughput, many connections, transforms data
    #   Fan-in >= 1 (receives work) AND fan-out >= 3 (calls many deps)
    if fi >= 1 and fo >= 3:
        return "PROCESSOR", "REACTOR", "N-05a: fan_in >= 1 and fan_out >= 3"

    # N-05b: Worker — background processor, low visibility
    #   Everything else: low fan-in, moderate fan-out, no external exposure
    return "PROCESSOR", "WORKER", "N-05b: default processor (low fan-in or fan-out)"


# ---------------------------------------------------------------------------
# Pass 2c: Domain Classification (Zoning Code §5)
# ---------------------------------------------------------------------------

def classify_domains(
    entities: dict,
    signals: dict[str, EntitySignals],
    edges: list[dict],
) -> dict[str, str]:
    """
    Derive domain boundaries from storage cohorts and sync topology.
    Returns {entity_id: domain_id}.
    """
    # Phase 1: Storage cohort clustering
    storage_to_users: dict[str, set[str]] = {}
    for eid, sig in signals.items():
        for st in sig.storage_targets:
            if st not in storage_to_users:
                storage_to_users[st] = set()
            storage_to_users[st].add(eid)

    # Build entity → cohort mapping
    # An entity can be in multiple cohorts; we use union-find to merge
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Union entities sharing the same storage target
    for storage_target, users in storage_to_users.items():
        users_list = list(users)
        for i in range(1, len(users_list)):
            union(users_list[0], users_list[i])

    # Phase 2: Sync topology refinement
    # Union entities with sync dependencies
    for edge in edges:
        if edge.get("type") == "sync":
            source = edge.get("source", "")
            target = edge.get("target", "")
            if source and target:
                # Only union if they share at least one storage target
                # (data gravity wins — sync calls alone don't merge domains)
                source_storage = set(signals.get(source, EntitySignals(entity_id="")).storage_targets)
                target_storage = set(signals.get(target, EntitySignals(entity_id="")).storage_targets)
                if source_storage & target_storage:
                    union(source, target)

    # Collect domain groups
    domain_groups: dict[str, set[str]] = {}
    for eid in list(entities.keys()) + list(signals.keys()):
        root = find(eid)
        if root not in domain_groups:
            domain_groups[root] = set()
        domain_groups[root].add(eid)

    # Assign domain IDs
    # Sort groups by size (largest first) for stable numbering
    sorted_groups = sorted(domain_groups.values(), key=lambda g: -len(g))

    domain_assignments: dict[str, str] = {}
    domain_counter = 0
    for group in sorted_groups:
        if len(group) <= 1:
            # Singletons get infrastructure domain or standalone
            for eid in group:
                etype = entities.get(eid, {}).get("spec", {}).get("type", "")
                if etype in ("network", "compute", "storage", "gateway"):
                    domain_assignments[eid] = "infrastructure"
                else:
                    domain_assignments[eid] = "standalone"
            continue

        domain_counter += 1
        domain_id = f"domain-{domain_counter:03d}"
        for eid in group:
            domain_assignments[eid] = domain_id

    # ── Gravitational Pull ──────────────────────────────────────────
    # Datastores/caches/messagebus entities with no storage_targets of
    # their own end up as singletons (standalone). But if other entities
    # critically depend on them, the datastore should be pulled into the
    # domain of its heaviest dependent cohort. This makes NUCLEUS
    # entities the gravitational center of their domain.
    #
    # Rule: For each standalone datastore/cache/messagebus, count critical
    # dependents per domain. If one domain dominates, reassign the
    # datastore to that domain. If tied or spread evenly, keep standalone.
    # ────────────────────────────────────────────────────────────────
    # Build reverse critical dependency map: target → [source, ...]
    critical_dependents: dict[str, list[str]] = {eid: [] for eid in domain_assignments}
    for edge in edges:
        if edge.get("critical"):
            target = edge.get("target", "")
            source = edge.get("source", "")
            if target in critical_dependents:
                critical_dependents[target].append(source)

    # Also count non-critical fan-in for messagebus (async dependencies)
    all_dependents: dict[str, list[str]] = {eid: [] for eid in domain_assignments}
    for edge in edges:
        target = edge.get("target", "")
        source = edge.get("source", "")
        if target in all_dependents:
            all_dependents[target].append(source)

    # Build forward dependency map: source → [target domains]
    forward_deps: dict[str, list[str]] = {eid: [] for eid in domain_assignments}
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        if source in forward_deps and target in domain_assignments:
            forward_deps[source].append(target)

    # Iterative pull — run multiple passes because pulling one entity
    # may create enough mass to pull another (e.g., datastore pulled in
    # first pass, then orphan service pulled in second pass via its
    # dependency on that datastore's new domain).
    for _pass in range(3):
        changed = False
        for eid, dom in list(domain_assignments.items()):
            if dom != "standalone":
                continue
            if eid not in entities:
                continue

            etype = entities[eid].get("spec", {}).get("type", "")

            # --- Collect domain votes from both directions ---
            domain_votes: dict[str, int] = {}

            # Votes from dependents (who depends on me?)
            # For datastores/caches: use critical dependents (strong gravity)
            # For messagebus: use all dependents (async = weaker but still gravity)
            # For services: use all dependents
            if etype in ("datastore", "cache"):
                dep_list = critical_dependents.get(eid, [])
            elif etype == "messagebus":
                dep_list = all_dependents.get(eid, [])
            else:
                dep_list = all_dependents.get(eid, [])

            for dep_eid in dep_list:
                dep_dom = domain_assignments.get(dep_eid, "standalone")
                if dep_dom not in ("standalone", "infrastructure"):
                    # Weight: critical dependents count double
                    weight = 2 if dep_eid in (critical_dependents.get(eid, [])) else 1
                    domain_votes[dep_dom] = domain_votes.get(dep_dom, 0) + weight

            # Votes from my own dependencies (who do I depend on?)
            # If I depend on entities in a specific domain, that pulls me too.
            for target_eid in forward_deps.get(eid, []):
                target_dom = domain_assignments.get(target_eid, "standalone")
                if target_dom not in ("standalone", "infrastructure"):
                    # Forward deps count as 1 vote each
                    domain_votes[target_dom] = domain_votes.get(target_dom, 0) + 1

            if not domain_votes:
                continue

            # Find dominant domain
            sorted_doms = sorted(domain_votes.items(), key=lambda x: -x[1])
            dominant_dom, dominant_count = sorted_doms[0]
            total_votes = sum(domain_votes.values())

            # Pull if dominant domain has >50% of votes
            if dominant_count > total_votes * 0.5:
                domain_assignments[eid] = dominant_dom
                changed = True

        if not changed:
            break

    return domain_assignments


def name_domains(
    entities: dict,
    signals: dict[str, EntitySignals],
    domains: dict[str, str],
) -> dict[str, str]:
    """
    Replace generic domain-NNN IDs with semantically meaningful names.
    Strategy:
    1. Find the dominant storage target(s) in each domain
    2. Derive a name from the storage technology + protocol stack
    3. Infrastructure and standalone domains keep their names

    Returns updated {entity_id: domain_name} dict.
    """
    # Collect domain → member entities
    domain_members: dict[str, list[str]] = {}
    for eid, dom in domains.items():
        if dom not in domain_members:
            domain_members[dom] = []
        domain_members[dom].append(eid)

    # Build rename map
    rename: dict[str, str] = {}

    for dom_id, members in domain_members.items():
        # Skip special domains
        if dom_id in ("infrastructure", "standalone"):
            rename[dom_id] = dom_id
            continue

        # Collect storage targets and protocols used by this domain
        storage_targets: list[str] = []
        protocols: set[str] = set()
        for eid in members:
            sig = signals.get(eid)
            if sig:
                storage_targets.extend(sig.storage_targets)
                protocols.update(p.lower() for p in sig.exposed_protocols)

        # Find dominant storage entity name
        if storage_targets:
            # Count occurrences — most common storage = domain anchor
            storage_counts = Counter(storage_targets)
            dominant_storage = storage_counts.most_common(1)[0][0]

            # Derive technology from storage entity
            ds_lower = dominant_storage.lower()
            if "mssql" in ds_lower or "sql" in ds_lower:
                tech = "mssql"
            elif "postgres" in ds_lower or "pg" in ds_lower:
                tech = "postgres"
            elif "docdb" in ds_lower or "mongo" in ds_lower:
                tech = "docdb"
            elif "redis" in ds_lower:
                tech = "redis"
            elif "dynamo" in ds_lower:
                tech = "dynamodb"
            else:
                tech = dominant_storage.split("-")[0] if "-" in dominant_storage else dominant_storage

            # Derive platform hint from protocols
            if "orleans" in protocols or "mssql" in protocols:
                platform = "wincore"
            elif "grpc" in protocols and "http" in protocols and tech == "postgres":
                platform = "nexus"
            else:
                platform = "app"

            domain_name = f"{platform}-{tech}"
        else:
            # No storage — use protocol signature
            if protocols:
                domain_name = f"proto-{'-'.join(sorted(protocols)[:2])}"
            else:
                domain_name = dom_id  # keep generic

        # Ensure uniqueness
        base_name = domain_name
        counter = 1
        while domain_name in rename.values():
            counter += 1
            domain_name = f"{base_name}-{counter}"

        rename[dom_id] = domain_name

    # Apply rename
    return {eid: rename.get(dom, dom) for eid, dom in domains.items()}


# ---------------------------------------------------------------------------
# Pass 2d: Entity Boundary Rules (Zoning Code §6)
# ---------------------------------------------------------------------------

def apply_entity_boundaries(
    entities: dict,
    signals: dict[str, EntitySignals],
    edges: list[dict],
) -> tuple[dict, list[dict]]:
    """
    Apply absorption and collapse rules.
    Returns (filtered_entities, filtered_edges).
    """
    to_absorb: set[str] = set()
    collapse_groups: dict[str, list[str]] = {}  # parent -> [children]

    for eid, sig in signals.items():
        if eid not in entities:
            continue
        e = entities[eid]
        etype = e.get("spec", {}).get("type", "")

        # T-TYPE-03.1: DNS records → absorb into gateway target
        # A gateway entity with fan_in=0 and fan_out=0 that is not an ALB
        # (i.e., DNS records, Cloudflare records) should be absorbed into
        # the ALB/gateway it points to.
        if etype == "gateway" and sig.fan_in == 0 and sig.fan_out == 0:
            # Check if this is a DNS record (no protocols, no ports)
            if not sig.exposed_ports and not sig.exposed_protocols:
                to_absorb.add(eid)
                continue

        # T-TYPE-03.2: Security groups / firewall rules with single attachment
        # Only absorb LEAF network entities (security groups, NACLs, firewall rules).
        # Foundation network entities (VPC, subnets) are never absorbed — they are
        # SUBSTRATE and define the ground plane of the city.
        FOUNDATION_NETWORK_PATTERNS = ("vpc", "subnet", "vnet")
        is_foundation = any(p in eid.lower() for p in FOUNDATION_NETWORK_PATTERNS)
        if etype == "network" and not is_foundation and sig.fan_in <= 1 and sig.fan_out == 0:
            if not sig.exposed_ports:
                to_absorb.add(eid)
                continue

    # Filter
    filtered_entities = {eid: e for eid, e in entities.items() if eid not in to_absorb}
    filtered_edges = [
        edge for edge in edges
        if edge.get("source", "") not in to_absorb and edge.get("target", "") not in to_absorb
    ]

    return filtered_entities, filtered_edges


# ---------------------------------------------------------------------------
# Orchestrator: Run full zoning evaluation
# ---------------------------------------------------------------------------

def run_zoning(entities: dict, edges: list[dict]) -> dict:
    """
    Run the complete zoning pipeline:
    1. Extract signals
    2. Apply entity boundaries (filter noise)
    3. Classify types
    4. Classify tiers
    5. Propagate tiers
    6. Classify domains + semantic naming
    7. Classify natures (Entity Ontology)
    8. Attach _signals audit metadata

    Returns the updated entities dict.
    """
    # Step 1: Extract signals
    signals = extract_signals(entities, edges)

    # Step 2: Entity boundaries — filter noise
    entities, edges = apply_entity_boundaries(entities, signals, edges)

    # Re-extract signals after filtering
    signals = extract_signals(entities, edges)

    # Step 3: Classify types
    for eid, e in entities.items():
        sig = signals.get(eid, EntitySignals(entity_id=eid))
        current_type = e.get("spec", {}).get("type", "service")
        new_type = classify_type(sig, current_type)
        e["spec"]["type"] = new_type

    # Step 4: Classify tiers
    tiers = {}
    tier_rules = {}
    for eid, e in entities.items():
        sig = signals.get(eid, EntitySignals(entity_id=eid))
        etype = e["spec"]["type"]
        tier, rule = classify_tier(sig, etype)
        tiers[eid] = tier
        tier_rules[eid] = rule

    # Step 5: Propagate tiers
    tiers = propagate_tiers(entities, signals, edges, tiers)

    # Step 6: Classify domains
    domains = classify_domains(entities, signals, edges)

    # Step 6.5: Semantic domain naming
    domains = name_domains(entities, signals, domains)

    # Step 7: Classify natures (Entity Ontology §3)
    natures: dict[str, tuple[str, str, str]] = {}
    for eid, e in entities.items():
        sig = signals.get(eid, EntitySignals(entity_id=eid))
        etype = e["spec"]["type"]
        nature, sub_nature, nature_rule = classify_nature(sig, etype)
        natures[eid] = (nature, sub_nature, nature_rule)

    # Step 8: Apply results and attach audit signals
    for eid, e in entities.items():
        sig = signals.get(eid, EntitySignals(entity_id=eid))
        nature, sub_nature, nature_rule = natures.get(eid, ("PROCESSOR", "WORKER", "N-05b"))

        e["spec"]["tier"] = tiers.get(eid, 3)
        e["spec"]["nature"] = nature
        if sub_nature:
            e["spec"]["sub_nature"] = sub_nature
        elif "sub_nature" in e.get("spec", {}):
            del e["spec"]["sub_nature"]
        e["metadata"]["domain"] = domains.get(eid, "standalone")

        # Audit trail
        e["_signals"] = {
            "tier": {
                "computed": tiers.get(eid, 3),
                "rule": tier_rules.get(eid, "T-TIER-04"),
                "signals": {
                    "fan_in": sig.fan_in,
                    "critical_fan_in": sig.critical_fan_in,
                    "blast_radius": sig.blast_radius,
                    "external_ingress": sig.receives_external_traffic,
                    "has_autoscaling": sig.has_autoscaling,
                    "replica_count": sig.replica_count,
                },
            },
            "domain": {
                "computed": domains.get(eid, "standalone"),
                "storage_targets": sig.storage_targets,
                "shared_storage_cohort_size": sig.shared_storage_cohort_size,
            },
            "type": {
                "computed": e["spec"]["type"],
            },
            "nature": {
                "computed": nature,
                "sub_nature": sub_nature or None,
                "rule": nature_rule,
                "signals": {
                    "fan_in": sig.fan_in,
                    "fan_out": sig.fan_out,
                    "critical_fan_in": sig.critical_fan_in,
                    "receives_external_traffic": sig.receives_external_traffic,
                    "exposed_protocols": sig.exposed_protocols,
                    "entity_type": e["spec"]["type"],
                },
            },
        }

    return entities
