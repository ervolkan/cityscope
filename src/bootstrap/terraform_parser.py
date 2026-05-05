"""Terraform Parser — extracts infrastructure entities from Terraform files."""

import re
from pathlib import Path
from typing import Any

import yaml

try:
    import hcl2
    HAS_HCL2 = True
except ImportError:
    HAS_HCL2 = False


class TerraformParser:
    """Parses Terraform files from infra-main style repositories."""

    def __init__(self, root_path: str | Path):
        self.root_path = Path(root_path)
        self.entities: list[dict[str, Any]] = []

    def parse(self) -> list[dict[str, Any]]:
        """Parse all Terraform files and return entity declarations."""
        self._find_and_parse_tf_files()
        return self.entities

    def _find_and_parse_tf_files(self):
        """Find and parse all .tf and .tf.json files."""
        for tf_file in self.root_path.rglob("*.tf"):
            if self._is_skippable(tf_file):
                continue
            try:
                self._parse_terraform_file(tf_file)
            except Exception:
                continue

        for tf_json_file in self.root_path.rglob("*.tf.json"):
            if self._is_skippable(tf_json_file):
                continue
            try:
                self._parse_terraform_json_file(tf_json_file)
            except Exception:
                continue

    def _is_skippable(self, file_path: Path) -> bool:
        """Skip common non-infrastructure values files."""
        skip_patterns = [
            "test",
            "example",
            "sample",
            "fixture",
            "module",
        ]
        name_lower = file_path.stem.lower()
        return any(pattern in name_lower for pattern in skip_patterns)

    def _parse_terraform_file(self, file_path: Path):
        """Parse a HCL2 Terraform file."""
        if not HAS_HCL2:
            # Fallback: basic regex parsing
            self._regex_parse_tf_file(file_path)
            return

        with open(file_path, "r") as f:
            content = f.read()
        
        try:
            tf_config = hcl2.loads(content)
        except Exception:
            self._regex_parse_tf_file(file_path)
            return

        self._extract_entities_from_hcl(tf_config, str(file_path))

    def _regex_parse_tf_file(self, file_path: Path):
        """Fallback regex-based parsing when hcl2 is not available."""
        with open(file_path, "r") as f:
            content = f.read()

        # Extract resource blocks
        resource_pattern = r'resource\s+"(\w+)"\s+"(\w+)"\s*\{([^}]+)\}'
        for match in re.finditer(resource_pattern, content, re.DOTALL):
            resource_type = match.group(1)
            resource_name = match.group(2)
            body = match.group(3)
            self._extract_entity_from_resource_block(resource_type, resource_name, body, str(file_path))

        # Extract module blocks
        module_pattern = r'module\s+"(\w+)"\s*\{([^}]+)\}'
        for match in re.finditer(module_pattern, content, re.DOTALL):
            module_name = match.group(1)
            body = match.group(2)
            self._extract_entity_from_module_block(module_name, body, str(file_path))

    def _parse_terraform_json_file(self, file_path: Path):
        """Parse a JSON-encoded Terraform file."""
        import json
        with open(file_path, "r") as f:
            tf_json = json.load(f)
        
        self._extract_entities_from_hcl(tf_json, str(file_path))

    def _extract_entities_from_hcl(self, config: dict, source_file: str):
        """Extract entities from parsed HCL configuration."""
        # Look for resource blocks
        resources = config.get("resource", [])
        if not isinstance(resources, list):
            resources = [resources]
        
        for resource_block in resources:
            if not isinstance(resource_block, dict):
                continue
            for resource_type, resource_defs in resource_block.items():
                if not isinstance(resource_defs, dict):
                    continue
                for resource_name, resource_config in resource_defs.items():
                    self._extract_entity_from_resource_config(
                        resource_type, resource_name, resource_config, source_file
                    )

    def _extract_entity_from_resource_block(
        self, resource_type: str, resource_name: str, body: str, source_file: str
    ):
        """Extract entity from a regex-parsed resource block."""
        entity_type = self._map_tf_resource_type(resource_type)
        if not entity_type:
            return

        entity = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": self._to_entity_id(resource_name),
                "name": resource_name,
                "domain": "",  # TODO
                "team": "",  # TODO
                "description": f"Auto-extracted from Terraform: {resource_type} '{resource_name}'",
            },
            "spec": {
                "type": entity_type,
                "tier": 0,  # TODO
                "lifecycle": "active",
                "protocols": [],
                "depends_on": [],
            },
        }

        # Extract network info from body
        vpc_match = re.search(r'vpc_id\s*=\s*"([^"]+)"', body)
        if vpc_match:
            entity["spec"]["depends_on"].append({
                "target": self._to_entity_id(vpc_match.group(1)),
                "type": "infra",
                "description": f"VPC dependency: {vpc_match.group(1)}",
            })
        
        subnet_match = re.search(r'subnet_ids\s*=\s*\[([^\]]+)\]', body)
        if subnet_match:
            subnets = [s.strip().strip('"') for s in subnet_match.group(1).split(",")]
            for subnet in subnets:
                if subnet:
                    entity["spec"]["depends_on"].append({
                        "target": self._to_entity_id(subnet),
                        "type": "infra",
                        "description": f"Subnet dependency: {subnet}",
                    })

        self.entities.append(entity)

    def _extract_entity_from_module_block(
        self, module_name: str, body: str, source_file: str
    ):
        """Extract entity from a regex-parsed module block."""
        entity = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": self._to_entity_id(module_name),
                "name": module_name,
                "domain": "",  # TODO
                "team": "",  # TODO
                "description": f"Auto-extracted from Terraform module: {module_name}",
            },
            "spec": {
                "type": "compute",
                "tier": 0,  # TODO
                "lifecycle": "active",
                "protocols": [],
                "depends_on": [],
            },
        }

        source_match = re.search(r'source\s*=\s*"([^"]+)"', body)
        if source_match:
            entity["spec"]["depends_on"].append({
                "target": self._to_entity_id(source_match.group(1)),
                "type": "infra",
                "description": f"Module source: {source_match.group(1)}",
            })

        self.entities.append(entity)

    def _extract_entity_from_resource_config(
        self, resource_type: str, resource_name: str, config: dict, source_file: str
    ):
        """Extract entity from parsed HCL resource config."""
        entity_type = self._map_tf_resource_type(resource_type)
        if not entity_type:
            return

        entity = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": self._to_entity_id(resource_name),
                "name": resource_name,
                "domain": "",  # TODO
                "team": "",  # TODO
                "description": f"Auto-extracted from Terraform: {resource_type} '{resource_name}'",
            },
            "spec": {
                "type": entity_type,
                "tier": 0,  # TODO
                "lifecycle": "active",
                "protocols": [],
                "depends_on": [],
            },
        }

        # Extract network dependencies
        if isinstance(config, dict):
            vpc_id = config.get("vpc_id")
            if vpc_id:
                entity["spec"]["depends_on"].append({
                    "target": self._to_entity_id(vpc_id),
                    "type": "infra",
                    "description": f"VPC: {vpc_id}",
                })
            
            subnet_ids = config.get("subnet_ids", [])
            if isinstance(subnet_ids, list):
                for subnet in subnet_ids:
                    entity["spec"]["depends_on"].append({
                        "target": self._to_entity_id(str(subnet)),
                        "type": "infra",
                        "description": f"Subnet: {subnet}",
                    })
            
            # Extract security groups
            security_groups = config.get("vpc_security_group_ids", [])
            if isinstance(security_groups, list):
                for sg in security_groups:
                    entity["spec"]["depends_on"].append({
                        "target": self._to_entity_id(str(sg)),
                        "type": "infra",
                        "description": f"Security Group: {sg}",
                    })

        self.entities.append(entity)

    def _map_tf_resource_type(self, tf_resource_type: str) -> str | None:
        """Map Terraform resource type to CityScope entity type."""
        type_mapping = {
            "aws_vpc": "network",
            "aws_subnet": "network",
            "aws_route_table": "network",
            "aws_security_group": "network",
            "aws_network_acl": "network",
            "aws_db_instance": "datastore",
            "aws_rds_cluster": "datastore",
            "aws_docdb_cluster": "datastore",
            "aws_docdb_cluster_instance": "datastore",
            "aws_elasticache_cluster": "cache",
            "aws_elasticache_replication_group": "cache",
            "aws_msk_cluster": "messagebus",
            "aws_msk_serverless_cluster": "messagebus",
            "aws_mq_broker": "messagebus",
            "aws_s3_bucket": "storage",
            "aws_s3_bucket_versioning": "storage",
            "aws_eks_cluster": "compute",
            "aws_eks_node_group": "compute",
            "aws_launch_template": "compute",
            "aws_launch_configuration": "compute",
            "aws_instance": "compute",
            "aws_lb": "gateway",
            "aws_alb": "gateway",
            "aws_api_gateway_rest_api": "gateway",
            "aws_cloudfront_distribution": "gateway",
            "cloudflare_record": "gateway",
            "cloudflare_zone": "gateway",
        }
        
        return type_mapping.get(tf_resource_type.lower())

    def _to_entity_id(self, name: str) -> str:
        """Convert resource name to entity ID format."""
        return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
