"""
CityScope Graph Enrichment
============================
Extracts implicit edges that aren't visible in env vars / connection strings:

1. ALB → Service edges (from Terraform app_list + NodePort matching)
2. Cloudflare → ALB edges (from Terraform cloudflare modules)
3. Infra chain edges (all K8s services → compute node group → EKS → VPC)
4. Entity boundary signals (NodePort = external ingress, service type)

This module is structurally-driven — it uses port matching, resource type
patterns, and IaC reference chains. No service names are hardcoded.
"""

from __future__ import annotations
import re
from typing import Any


# ---------------------------------------------------------------------------
# 1. ALB → Service: app_list + NodePort matching
# ---------------------------------------------------------------------------

def extract_alb_edges(
    terraform_content: str,
    entities: dict[str, dict],
) -> list[dict]:
    """
    Parse Terraform for app_list variables (any variable whose type is
    list(object({name, port, ...}))). Each item creates an ALB → service edge.

    The service is identified by matching the NodePort from app_list against
    the NodePort declared in Helm values.
    """
    edges = []
    nodeport_to_entity = _build_nodeport_index(entities)

    # Find all ALB module declarations and their app_list variable references
    alb_modules = _find_alb_modules(terraform_content)

    # Find all app_list-style variables: list of {name, port} objects
    app_lists = _extract_app_lists(terraform_content)

    for alb_id, alb_info in alb_modules.items():
        app_list_ref = alb_info.get("app_list_ref", "")
        app_list_items = app_lists.get(app_list_ref, [])

        for item in app_list_items:
            port = item.get("port")
            app_name = item.get("name", "")
            is_public = item.get("type", "public") == "public"

            if not port:
                continue

            # Match by NodePort
            target_entity = nodeport_to_entity.get(int(port))

            if target_entity:
                edges.append({
                    "source": alb_id,
                    "target": target_entity,
                    "type": "sync",
                    "protocol": "http",
                    "critical": False,
                    "description": f"ALB routes to service via NodePort {port}",
                    "_enrichment": "alb_app_list",
                })

                # Mark entity as receiving external traffic
                if target_entity in entities:
                    _set_signal(entities[target_entity], "receives_external_traffic", True)
                    _set_signal(entities[target_entity], "is_alb_target", True)

    return edges


def _build_nodeport_index(entities: dict) -> dict[int, str]:
    """Build a mapping of NodePort number → entity ID from Helm values."""
    index = {}
    for eid, e in entities.items():
        spec = e.get("spec", {})

        # Check service ports for nodePort
        # We stored the original values data in various fields
        # Look for protocols with port numbers in NodePort range (30000-32767)
        for proto in spec.get("protocols", []):
            port = proto.get("port", 0)
            desc = proto.get("description", "")
            # NodePort services expose port in 30000-32767 range
            # But the app_list uses the NodePort value directly

        # The nodePort info may be in labels or source metadata
        labels = e.get("metadata", {}).get("labels", {})
        if "nodePort" in labels:
            try:
                index[int(labels["nodePort"])] = eid
            except (ValueError, TypeError):
                pass

    return index


def _find_alb_modules(content: str) -> dict[str, dict]:
    """Find all module declarations that use alb_microservice source."""
    alb_modules = {}
    for m in re.finditer(r'module\s+"([^"]+)"\s*\{', content):
        module_name = m.group(1)
        brace_start = content.rfind('{', m.start(), m.end() + 5)
        if brace_start == -1:
            continue
        depth, i = 1, brace_start + 1
        while i < len(content) and depth > 0:
            if content[i] == '{': depth += 1
            elif content[i] == '}': depth -= 1
            i += 1
        block = content[brace_start:i]

        source_match = re.search(r'source\s*=\s*"([^"]+)"', block)
        if not source_match or "alb" not in source_match.group(1).lower():
            continue

        app_list_match = re.search(r'app_list\s*=\s*(\S+)', block)
        app_list_ref = ""
        if app_list_match:
            ref = app_list_match.group(1).strip()
            ref = ref.replace("local.", "").replace("var.", "")
            app_list_ref = ref

        eid = _normalize_id(module_name)
        alb_modules[eid] = {
            "module_name": module_name,
            "source": source_match.group(1),
            "app_list_ref": app_list_ref,
        }

    return alb_modules

def _extract_app_lists(content: str) -> dict[str, list[dict]]:
    """Extract variable definitions containing lists of {name, port} objects."""
    app_lists = {}

    for m in re.finditer(r'variable\s+"([^"]+)"\s*\{', content):
        var_name = m.group(1)
        brace_start = content.rfind('{', m.start(), m.end() + 5)
        if brace_start == -1:
            continue
        depth, i = 1, brace_start + 1
        while i < len(content) and depth > 0:
            if content[i] == '{': depth += 1
            elif content[i] == '}': depth -= 1
            i += 1
        block = content[brace_start:i]

        default_match = re.search(r'default\s*=\s*\[', block)
        if not default_match:
            continue

        list_start = block.index('[', default_match.start())
        d2, j = 1, list_start + 1
        while j < len(block) and d2 > 0:
            if block[j] == '[': d2 += 1
            elif block[j] == ']': d2 -= 1
            j += 1
        list_content = block[list_start:j]

        items = _parse_object_list(list_content)
        if items:
            app_lists[var_name] = items

    # Resolve locals aliases
    for m in re.finditer(r'locals\s*\{', content):
        brace_start = content.find('{', m.start())
        depth, i = 1, brace_start + 1
        while i < len(content) and depth > 0:
            if content[i] == '{': depth += 1
            elif content[i] == '}': depth -= 1
            i += 1
        block = content[brace_start:i]
        for lm in re.finditer(r'(\w+)\s*=\s*var\.(\w+)', block):
            if lm.group(2) in app_lists:
                app_lists[lm.group(1)] = app_lists[lm.group(2)]

    return app_lists

def _parse_object_list(list_content: str) -> list[dict]:
    """Parse a HCL list of objects: [ { name = "x", port = "y" }, ... ]"""
    items = []
    # Find each { ... } block
    for m in re.finditer(r'\{([^}]+)\}', list_content):
        obj_str = m.group(1)
        item = {}
        for kv in re.finditer(r'(\w+)\s*=\s*"?([^",}\s]+)"?', obj_str):
            key = kv.group(1)
            val = kv.group(2).strip('"')
            item[key] = val
        if "name" in item and "port" in item:
            try:
                item["port"] = int(item["port"])
            except ValueError:
                pass
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# 2. Cloudflare → ALB edges
# ---------------------------------------------------------------------------

def extract_cloudflare_edges(
    terraform_content: str,
    entities: dict[str, dict],
) -> list[dict]:
    """
    Find cloudflare modules/resources that CNAME to an ALB,
    and create Cloudflare → ALB edges.
    """
    edges = []

    # Find cloudflare modules referencing ALB
    for m in re.finditer(r'module\s+"([^"]+)"\s*\{', terraform_content):
        module_name = m.group(1)
        block = _extract_block(terraform_content, m.end())

        source_match = re.search(r'source\s*=\s*"([^"]+)"', block)
        if not source_match or "cloudflare" not in source_match.group(1).lower():
            continue

        # Find ALB reference
        alb_match = re.search(r'alb_fqdn\s*=\s*(\S+)', block)
        if not alb_match:
            continue

        alb_ref = alb_match.group(1).strip()
        # Resolve: module.prod_alb.lb_dns_name → prod_alb
        alb_entity = _resolve_module_ref(alb_ref)

        if alb_entity:
            cf_entity = _normalize_id(module_name)
            edges.append({
                "source": cf_entity,
                "target": alb_entity,
                "type": "infra",
                "protocol": "dns",
                "critical": False,
                "description": f"DNS CNAME to ALB",
                "_enrichment": "cloudflare_to_alb",
            })

    # Standalone cloudflare_record resources
    for m in re.finditer(r'resource\s+"cloudflare_record"\s+"([^"]+)"', terraform_content):
        res_name = m.group(1)
        block = _extract_block(terraform_content, m.end())

        content_match = re.search(r'content\s*=\s*(\S+)', block)
        if not content_match:
            continue

        target_ref = content_match.group(1).strip()
        target_entity = _resolve_module_ref(target_ref)

        if target_entity:
            cf_entity = f"cf-{_normalize_id(res_name)}"
            edges.append({
                "source": cf_entity,
                "target": target_entity,
                "type": "infra",
                "protocol": "dns",
                "critical": False,
                "description": f"DNS record to ALB/service",
                "_enrichment": "cloudflare_record_to_target",
            })

    return edges


def _resolve_module_ref(ref: str) -> str | None:
    """Resolve a module.xxx.yyy reference to an entity ID."""
    # module.prod_alb.lb_dns_name_microservice → prod-alb
    m = re.match(r'module\.(\w+)', ref)
    if m:
        return _normalize_id(m.group(1))
    return None


# ---------------------------------------------------------------------------
# 3. Infra chain edges (services → compute → VPC)
# ---------------------------------------------------------------------------

def extract_infra_chain_edges(
    entities: dict[str, dict],
) -> list[dict]:
    """
    All service/gateway entities running on K8s implicitly depend on
    the compute (node group / cluster) and network (VPC) infrastructure.

    Rules:
    - Every service/gateway entity → depends on compute entities (infra edge)
    - Every compute entity → depends on network entities (infra edge)
    """
    edges = []

    # Find compute and network entities
    compute_entities = [eid for eid, e in entities.items() if e.get("spec", {}).get("type") == "compute"]
    network_entities = [eid for eid, e in entities.items() if e.get("spec", {}).get("type") == "network"]

    # Find the "main" compute entity (largest blast radius or most labels)
    # Heuristic: compute entity with "worker" in labels or name
    worker_compute = None
    cluster_compute = None
    for eid in compute_entities:
        e = entities[eid]
        labels = e.get("metadata", {}).get("labels", {})
        name = e.get("metadata", {}).get("name", "").lower()
        if labels.get("role") == "worker":
            worker_compute = eid
        if "cluster" in name and "node" not in name.lower():
            cluster_compute = eid

    # All services → worker compute (if found)
    if worker_compute:
        for eid, e in entities.items():
            etype = e.get("spec", {}).get("type", "")
            if etype in ("service", "gateway") and eid != worker_compute:
                edges.append({
                    "source": eid,
                    "target": worker_compute,
                    "type": "infra",
                    "protocol": "k8s",
                    "critical": False,
                    "description": "Runs on compute node group",
                    "_enrichment": "infra_chain_service_to_compute",
                })

    # Worker compute → cluster compute
    if worker_compute and cluster_compute and worker_compute != cluster_compute:
        edges.append({
            "source": worker_compute,
            "target": cluster_compute,
            "type": "infra",
            "protocol": "k8s",
            "critical": True,
            "description": "Node group belongs to cluster",
            "_enrichment": "infra_chain_nodegroup_to_cluster",
        })

    # Cluster compute → main VPC
    # Heuristic: the VPC entity with the most connections or the one
    # referenced in the EKS module
    if cluster_compute and network_entities:
        # Pick first VPC-like network entity
        main_vpc = network_entities[0]
        for nid in network_entities:
            if "vpc" in nid.lower():
                main_vpc = nid
                break
        edges.append({
            "source": cluster_compute,
            "target": main_vpc,
            "type": "infra",
            "protocol": "vpc",
            "critical": True,
            "description": "Cluster runs in VPC",
            "_enrichment": "infra_chain_cluster_to_vpc",
        })

    return edges


# ---------------------------------------------------------------------------
# 4. NodePort signal enrichment
# ---------------------------------------------------------------------------

def enrich_external_traffic_signals(
    terraform_content: str,
    entities: dict[str, dict],
) -> dict[str, dict]:
    """
    Mark entities as receiving external traffic based on:
    - NodePort service type in Helm values
    - Presence in ALB app_list (matched by port)
    """
    app_lists = _extract_app_lists(terraform_content)
    all_app_ports = set()
    for items in app_lists.values():
        for item in items:
            port = item.get("port")
            if isinstance(port, int):
                all_app_ports.add(port)

    for eid, e in entities.items():
        spec = e.get("spec", {})

        # Check for NodePort in protocols
        for proto in spec.get("protocols", []):
            port = proto.get("port", 0)
            if port in all_app_ports:
                _set_signal(e, "receives_external_traffic", True)
                _set_signal(e, "is_alb_target", True)
                _set_signal(e, "node_port", port)

    return entities


# ---------------------------------------------------------------------------
# Orchestrator: run all enrichment steps
# ---------------------------------------------------------------------------

def enrich_graph(
    terraform_contents: list[str],
    entities: dict[str, dict],
    existing_edges: list[dict],
) -> tuple[dict, list[dict]]:
    """
    Run all graph enrichment steps.

    Args:
        terraform_contents: list of raw .tf file contents
        entities: current entity dict {id: entity}
        existing_edges: current edge list from bootstrap Pass 1

    Returns:
        (enriched_entities, all_edges)
    """
    all_tf = "\n\n".join(terraform_contents)
    new_edges = list(existing_edges)

    # 1. ALB → Service edges
    alb_edges = extract_alb_edges(all_tf, entities)
    new_edges.extend(alb_edges)

    # 2. Cloudflare → ALB edges
    cf_edges = extract_cloudflare_edges(all_tf, entities)
    new_edges.extend(cf_edges)

    # 3. Infra chain edges
    infra_edges = extract_infra_chain_edges(entities)
    new_edges.extend(infra_edges)

    # 4. External traffic signal enrichment
    entities = enrich_external_traffic_signals(all_tf, entities)

    return entities, new_edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_block(content: str, start: int) -> str:
    idx = content.find("{", start)
    if idx == -1:
        return ""
    depth, i = 1, idx + 1
    while i < len(content) and depth > 0:
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
        i += 1
    return content[idx:i]


def _extract_list(content: str, start: int) -> str:
    idx = content.find("[", start)
    if idx == -1:
        return ""
    depth, i = 1, idx + 1
    while i < len(content) and depth > 0:
        if content[i] == "[":
            depth += 1
        elif content[i] == "]":
            depth -= 1
        i += 1
    return content[idx:i]


def _normalize_id(name: str) -> str:
    name = re.sub(r"^prod-", "", name)
    name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", name)


def _set_signal(entity: dict, key: str, value: Any):
    """Set a signal on an entity's metadata for later use by zoning engine."""
    if "_enrichment_signals" not in entity:
        entity["_enrichment_signals"] = {}
    entity["_enrichment_signals"][key] = value
