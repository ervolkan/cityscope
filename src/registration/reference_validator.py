"""Reference validator — validates cross-entity references in declarations."""

from pathlib import Path
from typing import Any

import yaml


def load_all_declarations(declarations_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load all declaration manifests into a lookup dict by entity ID."""
    declarations_dir = Path(declarations_dir)
    entities: dict[str, dict[str, Any]] = {}
    
    for yaml_file in declarations_dir.glob("*.yaml"):
        if yaml_file.name.startswith("."):
            continue
        with open(yaml_file, "r") as f:
            declaration = yaml.safe_load(f)
        entity_id = declaration.get("metadata", {}).get("id")
        if entity_id:
            entities[entity_id] = declaration
    
    for yaml_file in declarations_dir.glob("*.yml"):
        if yaml_file.name.startswith("."):
            continue
        with open(yaml_file, "r") as f:
            declaration = yaml.safe_load(f)
        entity_id = declaration.get("metadata", {}).get("id")
        if entity_id:
            entities[entity_id] = declaration
    
    return entities


def load_registry(registry_path: str | Path) -> set[str]:
    """Load a YAML registry file (domains.yaml or teams.yaml) and return valid IDs."""
    with open(registry_path, "r") as f:
        entries = yaml.safe_load(f)
    return {entry["id"] for entry in entries}


def validate_references(declarations_dir: str | Path) -> list[str]:
    """Validate all cross-entity references in declarations.
    
    Checks:
    - All depends_on targets exist in the ontology
    - All metadata.domain values reference valid domains
    - All metadata.team values reference valid teams
    
    Returns a list of validation errors.
    """
    entities = load_all_declarations(declarations_dir)
    errors: list[str] = []
    
    # Find domains and teams registries
    ontology_dir = Path(declarations_dir).parent.parent / "src" / "ontology"
    valid_domains = load_registry(ontology_dir / "domains.yaml")
    valid_teams = load_registry(ontology_dir / "teams.yaml")
    
    for entity_id, declaration in entities.items():
        # Check domain reference
        domain = declaration.get("metadata", {}).get("domain")
        if domain and domain not in valid_domains:
            errors.append(
                f"{entity_id}: domain '{domain}' not found in domains.yaml"
            )
        
        # Check team reference
        team = declaration.get("metadata", {}).get("team")
        if team and team not in valid_teams:
            errors.append(
                f"{entity_id}: team '{team}' not found in teams.yaml"
            )
        
        # Check depends_on references
        for dep in declaration.get("spec", {}).get("depends_on", []):
            target = dep.get("target")
            if target and target not in entities:
                errors.append(
                    f"{entity_id}: depends_on target '{target}' not found in declarations"
                )
    
    return errors
