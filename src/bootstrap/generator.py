"""Declaration Generator — creates draft YAML manifests with TODO markers."""

from typing import Any


class DeclarationGenerator:
    """Generates draft entity declaration manifests from parsed IaC data."""

    def generate_declarations(self, entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Generate declaration manifests from parsed entities.
        
        Returns a dict mapping filenames to manifest content.
        """
        declarations: dict[str, dict[str, Any]] = {}
        
        for entity in entities:
            entity_id = entity.get("metadata", {}).get("id")
            if not entity_id:
                continue
            
            # Clean up internal tracking fields
            if "_todos" in entity:
                del entity["_todos"]
            if "_source_file" in entity:
                del entity["_source_file"]
            
            filename = f"{entity_id}.yaml"
            declarations[filename] = entity
        
        return declarations

    def mark_todos(self, entity: dict[str, Any]) -> None:
        """Mark unextractable fields as TODO in the entity.
        
        These fields cannot be auto-extracted from IaC and require manual authoring:
        - domain
        - team
        - description
        - tier
        - SLO targets
        """
        entity["_todos"] = {}
        
        # Metadata TODOs
        metadata = entity.get("metadata", {})
        if not metadata.get("domain"):
            metadata["domain"] = ""  # TODO: assign domain from domains.yaml
            entity["_todos"]["domain"] = True
        if not metadata.get("team"):
            metadata["team"] = ""  # TODO: assign team from teams.yaml
            entity["_todos"]["team"] = True
        if not metadata.get("description") or metadata["description"].startswith("Auto-extracted"):
            metadata["description"] = metadata.get("description", "") + " [TODO: write description]"
            entity["_todos"]["description"] = True
        
        # Spec TODOs
        spec = entity.get("spec", {})
        if spec.get("tier", 0) == 0:
            # Tier 0 is the default placeholder
            entity["_todos"]["tier"] = True
        
        # SLO TODO (for tier-0 and tier-1, required by R007)
        # The bootstrap collector cannot know the real SLO targets
        # Mark as placeholder
        entity["_todos"]["slo"] = True
        
        # Sync dependency TODOs (timeout_ms required by R004)
        for dep in spec.get("depends_on", []):
            if dep.get("type") == "sync" and not dep.get("timeout_ms"):
                dep["timeout_ms"] = 0  # TODO: set actual timeout
                entity["_todos"][f"sync_timeout_{dep.get('target', 'unknown')}"] = True
        
        # Datastore backup TODO (required by R003)
        if spec.get("type") == "datastore":
            entity["_todos"]["backup"] = True
