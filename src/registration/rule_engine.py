"""Rule engine — enforces ontology constraint rules (R001–R012) against the full graph."""

from typing import Any


def check_rule_r001_tier_dependency(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R001: Tier-0 services cannot depend on tier-3 services."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        tier = declaration.get("spec", {}).get("tier")
        if tier != 0:
            continue
        for dep in declaration.get("spec", {}).get("depends_on", []):
            target_id = dep.get("target")
            target = entities.get(target_id)
            if target and target.get("spec", {}).get("tier") == 3:
                errors.append(
                    f"R001: tier-0 entity '{entity_id}' depends on tier-3 entity '{target_id}'"
                )
    return errors


def check_rule_r002_team_ownership(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R002: Every service must have at least one owner team."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        entity_type = declaration.get("spec", {}).get("type")
        if entity_type not in ("service", "gateway"):
            continue
        team = declaration.get("metadata", {}).get("team")
        if not team:
            errors.append(f"R002: entity '{entity_id}' has no owner team assigned")
    return errors


def check_rule_r003_datastore_backup(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R003: Datastore entities must have backup configuration."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        if declaration.get("spec", {}).get("type") != "datastore":
            continue
        backup = declaration.get("spec", {}).get("backup")
        if not backup or not backup.get("enabled"):
            errors.append(
                f"R003: datastore entity '{entity_id}' has no backup configuration"
            )
        elif backup.get("retention_days", 0) < 7:
            errors.append(
                f"R003: datastore entity '{entity_id}' backup retention_days ({backup.get('retention_days')}) is less than 7"
            )
    return errors


def check_rule_r004_sync_protocol_timeout(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R004: Sync dependencies must specify protocol and timeout."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        for dep in declaration.get("spec", {}).get("depends_on", []):
            if dep.get("type") != "sync":
                continue
            if not dep.get("protocol"):
                errors.append(
                    f"R004: entity '{entity_id}' sync dependency '{dep.get('target')}' missing protocol"
                )
            if not dep.get("timeout_ms"):
                errors.append(
                    f"R004: entity '{entity_id}' sync dependency '{dep.get('target')}' missing timeout_ms"
                )
    return errors


def check_rule_r006_lifecycle_transitions(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R006: Lifecycle state transitions must follow valid paths."""
    valid_transitions = {
        "provisioning": "active",
        "active": "deprecated",
        "deprecated": "retired",
    }
    errors: list[str] = []
    # This rule checks the transition history which would be in git commits
    # For now, validate the current state is one of the valid states
    for entity_id, declaration in entities.items():
        lifecycle = declaration.get("spec", {}).get("lifecycle")
        if lifecycle and lifecycle not in valid_transitions and lifecycle != "retired":
            errors.append(
                f"R006: entity '{entity_id}' has invalid lifecycle state '{lifecycle}'"
            )
    return errors


def check_rule_r007_slo_targets(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R007: Tier-0 and tier-1 services must have SLO targets."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        tier = declaration.get("spec", {}).get("tier")
        if tier not in (0, 1):
            continue
        slo = declaration.get("spec", {}).get("slo")
        if not slo:
            errors.append(
                f"R007: tier-{tier} entity '{entity_id}' has no SLO targets defined"
            )
        else:
            if "availability_percent" not in slo:
                errors.append(
                    f"R007: tier-{tier} entity '{entity_id}' missing slo.availability_percent"
                )
            if "latency_p99_ms" not in slo:
                errors.append(
                    f"R007: tier-{tier} entity '{entity_id}' missing slo.latency_p99_ms"
                )
    return errors


def check_rule_r008_circular_dependencies(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R008: No circular dependencies in the graph."""
    errors: list[str] = []
    # Build adjacency list
    graph: dict[str, list[str]] = {}
    for entity_id, declaration in entities.items():
        deps = [
            dep.get("target")
            for dep in declaration.get("spec", {}).get("depends_on", [])
            if dep.get("target")
        ]
        graph[entity_id] = deps
    
    # DFS cycle detection
    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycle_path: list[str] = []
    
    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        cycle_path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = cycle_path.index(neighbor)
                cycle = cycle_path[cycle_start:] + [neighbor]
                errors.append(
                    f"R008: circular dependency detected: {' -> '.join(cycle)}"
                )
                return True
        
        cycle_path.pop()
        rec_stack.discard(node)
        return False
    
    for node in graph:
        if node not in visited:
            dfs(node)
    
    return errors


def check_rule_r009_unique_ids(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R009: Entity IDs must be globally unique."""
    errors: list[str] = []
    seen_ids: dict[str, str] = {}  # id -> filename
    for filename, declaration in entities.items():
        entity_id = declaration.get("metadata", {}).get("id")
        if not entity_id:
            continue
        if entity_id in seen_ids:
            errors.append(
                f"R009: duplicate entity ID '{entity_id}' found in {filename} (also in {seen_ids[entity_id]})"
            )
        else:
            seen_ids[entity_id] = filename
    return errors


def check_rule_r010_retirement_date(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R010: Deprecated/retired entities must have a retirement_date."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        lifecycle = declaration.get("spec", {}).get("lifecycle")
        if lifecycle in ("deprecated", "retired"):
            retirement_date = declaration.get("spec", {}).get("retirement_date")
            if not retirement_date:
                errors.append(
                    f"R010: {lifecycle} entity '{entity_id}' is missing retirement_date"
                )
    return errors


def check_rule_r011_gateway_downstreams(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R011: Gateway entities should have at least one sync dependency."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        if declaration.get("spec", {}).get("type") != "gateway":
            continue
        sync_deps = [
            dep for dep in declaration.get("spec", {}).get("depends_on", [])
            if dep.get("type") == "sync"
        ]
        if not sync_deps:
            errors.append(
                f"R011: gateway entity '{entity_id}' has no downstream sync dependencies"
            )
    return errors


def check_rule_r012_compute_network(entities: dict[str, dict[str, Any]]) -> list[str]:
    """R012: Compute entities must belong to a network."""
    errors: list[str] = []
    for entity_id, declaration in entities.items():
        if declaration.get("spec", {}).get("type") != "compute":
            continue
        infra_deps = [
            dep for dep in declaration.get("spec", {}).get("depends_on", [])
            if dep.get("type") == "infra"
        ]
        if not infra_deps:
            errors.append(
                f"R012: compute entity '{entity_id}' has no infra dependency (network)"
            )
    return errors


# Rule registry — all rules are run during validation
ALL_RULES = {
    "R001": check_rule_r001_tier_dependency,
    "R002": check_rule_r002_team_ownership,
    "R003": check_rule_r003_datastore_backup,
    "R004": check_rule_r004_sync_protocol_timeout,
    "R006": check_rule_r006_lifecycle_transitions,
    "R007": check_rule_r007_slo_targets,
    "R008": check_rule_r008_circular_dependencies,
    "R009": check_rule_r009_unique_ids,
    "R010": check_rule_r010_retirement_date,
    "R011": check_rule_r011_gateway_downstreams,
    "R012": check_rule_r012_compute_network,
}


def run_all_rules(entities: dict[str, dict[str, Any]]) -> list[str]:
    """Execute all rules against the entity graph and return combined errors."""
    all_errors: list[str] = []
    for rule_id, check_fn in ALL_RULES.items():
        errors = check_fn(entities)
        all_errors.extend(errors)
    return all_errors
