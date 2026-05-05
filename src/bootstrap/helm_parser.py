"""Helm Values Parser — extracts entity declarations from Helm chart values files."""

import re
from pathlib import Path
from typing import Any

import yaml


class HelmValuesParser:
    """Parses Helm values files from betcorewin-cd style repositories."""

    def __init__(self, root_path: str | Path):
        self.root_path = Path(root_path)
        self.entities: list[dict[str, Any]] = []

    def parse(self) -> list[dict[str, Any]]:
        """Parse all Helm values files and return entity declarations."""
        self._find_and_parse_values_files()
        return self.entities

    def _find_and_parse_values_files(self):
        """Find and parse all values*.yaml files in the repository."""
        for values_file in self.root_path.rglob("values*.yaml"):
            if self._is_skippable(values_file):
                continue
            try:
                with open(values_file, "r") as f:
                    values = yaml.safe_load(f)
                if values:
                    self._extract_entities(values, str(values_file))
            except yaml.YAMLError:
                continue

    def _is_skippable(self, file_path: Path) -> bool:
        """Skip common non-service values files."""
        skip_patterns = [
            "global",
            "common",
            "defaults",
            "template",
            "example",
            "sample",
            "test",
            "fixture",
        ]
        name_lower = file_path.stem.lower()
        return any(pattern in name_lower for pattern in skip_patterns)

    def _extract_entities(self, values: dict, source_file: str):
        """Extract entities from a parsed values dictionary."""
        # Look for service definitions
        service_name = self._extract_service_name(values, source_file)
        if not service_name:
            return

        entity: dict[str, Any] = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": self._to_entity_id(service_name),
                "name": service_name,
                "domain": "",  # TODO
                "team": "",  # TODO
                "description": "",  # TODO
            },
            "spec": {
                "type": "service",
                "tier": 0,  # TODO
                "lifecycle": "active",
                "protocols": [],
                "depends_on": [],
                "image": self._extract_image(values),
            },
        }

        # Extract protocols from ports
        protocols = self._extract_protocols(values)
        if protocols:
            entity["spec"]["protocols"] = protocols

        # Extract dependencies
        dependencies = self._extract_dependencies(values, source_file)
        if dependencies:
            entity["spec"]["depends_on"] = dependencies

        # Extract scaling
        scaling = self._extract_scaling(values)
        if scaling:
            entity["spec"]["scaling"] = scaling

        # Determine if this is a gateway entity
        if self._is_gateway(values, service_name):
            entity["spec"]["type"] = "gateway"

        self.entities.append(entity)

    def _extract_service_name(self, values: dict, source_file: str) -> str | None:
        """Extract service name from nameOverride or values file path."""
        # Try nameOverride first
        name_override = values.get("nameOverride") or values.get("name_override")
        if name_override:
            return str(name_override)
        
        # Fall back to file name pattern: values-servicename.yaml
        file_stem = Path(source_file).stem
        match = re.match(r"values[-_]([a-z0-9-]+)", file_stem.lower())
        if match:
            return match.group(1)
        
        return None

    def _to_entity_id(self, service_name: str) -> str:
        """Convert service name to entity ID format."""
        return re.sub(r"[^a-z0-9-]", "-", service_name.lower()).strip("-")

    def _extract_image(self, values: dict) -> str | None:
        """Extract container image reference."""
        # Common patterns
        image = values.get("image", {})
        if isinstance(image, str):
            return image
        if isinstance(image, dict):
            repository = image.get("repository", "")
            tag = image.get("tag", "latest")
            if repository:
                return f"{repository}:{tag}"
        # Check nested patterns
        for key in ["deployment", "container"]:
            nested = values.get(key, {})
            if isinstance(nested, dict):
                img = nested.get("image")
                if isinstance(img, str):
                    return img
                if isinstance(img, dict):
                    repo = img.get("repository", "")
                    tag = img.get("tag", "latest")
                    if repo:
                        return f"{repo}:{tag}"
        return None

    def _extract_protocols(self, values: dict) -> list[dict[str, Any]]:
        """Extract protocol endpoints from port definitions."""
        protocols = []
        ports = self._find_ports(values)
        
        for port_info in ports:
            port = port_info.get("port")
            target_port = port_info.get("targetPort") or port
            name = port_info.get("name", "")
            protocol = port_info.get("protocol", "TCP").lower()
            
            if not port:
                continue

            # Determine protocol type from port/name
            if 8080 <= port <= 8090 or "grpc" in name.lower():
                proto_name = "grpc"
            elif port == 80 or port == 8080 or "http" in name.lower():
                proto_name = "http"
            elif port == 443 or "https" in name.lower():
                proto_name = "https"
            elif port in (11111, 30000):
                proto_name = "orleans"
            elif port == 5672 or "amqp" in name.lower():
                proto_name = "amqp"
            elif port == 6379 or "redis" in name.lower():
                proto_name = "redis"
            elif port == 5432 or "postgres" in name.lower():
                proto_name = "postgres"
            elif port in (1433, 1434) or "mssql" in name.lower():
                proto_name = "mssql"
            else:
                proto_name = "tcp"

            protocols.append({
                "name": proto_name,
                "port": port,
                "description": f"{proto_name.upper()} port {port}",
            })
        
        return protocols

    def _find_ports(self, values: dict, depth: int = 0) -> list[dict[str, Any]]:
        """Recursively find all port definitions in values."""
        ports = []
        if depth > 10:
            return ports
        
        # Direct service.ports
        service = values.get("service", {})
        if isinstance(service, dict):
            ports_list = service.get("ports", [])
            if isinstance(ports_list, list):
                for p in ports_list:
                    if isinstance(p, dict) and "port" in p:
                        ports.append(p)
        
        # Container ports
        container = values.get("container", {})
        if isinstance(container, dict):
            ports_list = container.get("ports", [])
            if isinstance(ports_list, list):
                for p in ports_list:
                    if isinstance(p, dict) and "containerPort" in p:
                        ports.append({"port": p["containerPort"], "name": p.get("name", "")})
        
        # Deployment ports
        deployment = values.get("deployment", {})
        if isinstance(deployment, dict):
            ports_list = deployment.get("ports", [])
            if isinstance(ports_list, list):
                for p in ports_list:
                    if isinstance(p, dict) and "port" in p:
                        ports.append(p)
        
        # Recurse into nested dicts
        for key, val in values.items():
            if isinstance(val, dict) and key not in ("service", "container", "deployment", "ports"):
                ports.extend(self._find_ports(val, depth + 1))
        
        return ports

    def _extract_dependencies(self, values: dict, source_file: str) -> list[dict[str, Any]]:
        """Extract dependencies from environment variables and connection strings."""
        deps = []
        env_vars = self._find_env_vars(values)
        
        for env in env_vars:
            var_name = env.get("name", "")
            var_value = env.get("value", "")
            
            if not var_name or not var_value:
                continue

            # gRPC service hosts (case-insensitive match)
            var_upper = var_name.upper()
            if ("GRPCHOST" in var_upper or "GRPC_HOST" in var_upper or 
                "SERVICEHOST" in var_upper or "SERVICE_HOST" in var_upper):
                target = self._to_entity_id(var_value.split(":")[0])
                deps.append({
                    "target": target,
                    "type": "sync",
                    "protocol": "grpc",
                    # TODO: timeout_ms
                    "description": f"Auto-detected from {var_name}",
                })
            
            # Database connection strings
            elif any(keyword in var_value.lower() for keyword in [
                "postgres", "postgresql", "mysql", "mssql", "sqlserver",
                "mongodb", "documentdb", "redis"
            ]):
                dep_type = "cache" if "redis" in var_value.lower() else "storage"
                protocol = self._detect_storage_protocol(var_value)
                target = self._extract_hostname_from_connection_string(var_value)
                if target:
                    deps.append({
                        "target": target,
                        "type": dep_type,
                        "protocol": protocol,
                        "critical": True,
                        "description": f"Auto-detected from {var_name}",
                    })
            
            # RabbitMQ / AMQP
            elif any(keyword in var_name.lower() for keyword in ["rabbit", "amqp", "mq"]) or \
                 any(keyword in var_value.lower() for keyword in ["rabbit", "amqp"]):
                target = self._extract_hostname_from_connection_string(var_value)
                if not target:
                    target = "rabbitmq"
                deps.append({
                    "target": target,
                    "type": "async",
                    "protocol": "amqp",
                    "description": f"Auto-detected from {var_name}",
                })
        
        # initContainers → critical dependencies
        init_containers = values.get("initContainers", [])
        if isinstance(init_containers, list):
            for container in init_containers:
                if isinstance(container, dict) and container.get("name"):
                    deps.append({
                        "target": self._to_entity_id(container["name"]),
                        "type": "infra",
                        "critical": True,
                        "description": f"Init container: {container['name']}",
                    })
        
        return deps

    def _find_env_vars(self, values: dict, depth: int = 0) -> list[dict[str, str]]:
        """Recursively find environment variable definitions."""
        env_vars = []
        if depth > 10:
            return env_vars
        
        # Direct env key
        env = values.get("env", {})
        if isinstance(env, list):
            for e in env:
                if isinstance(e, dict) and "name" in e:
                    env_vars.append(e)
        elif isinstance(env, dict):
            for name, value in env.items():
                env_vars.append({"name": name, "value": str(value)})
        
        # Recurse
        for key, val in values.items():
            if isinstance(val, dict) and key != "env":
                env_vars.extend(self._find_env_vars(val, depth + 1))
        
        return env_vars

    def _detect_storage_protocol(self, connection_string: str) -> str:
        """Detect storage protocol from connection string."""
        cs_lower = connection_string.lower()
        if cs_lower.startswith(("postgres://", "postgresql://")):
            return "postgres"
        if cs_lower.startswith(("mssql://", "sqlserver://")):
            return "mssql"
        if cs_lower.startswith(("mongodb://", "documentdb://")):
            return "mssql"  # DocumentDB uses MongoDB wire protocol
        if cs_lower.startswith("redis://"):
            return "redis"
        if cs_lower.startswith("amqp://"):
            return "amqp"
        return "tcp"

    def _extract_hostname_from_connection_string(self, connection_string: str) -> str | None:
        """Extract hostname from a connection string."""
        # Pattern: protocol://user:pass@host:port/db
        match = re.search(r"://(?:[^@]+@)?([^:/?]+)", connection_string)
        if match:
            return match.group(1)
        return None

    def _extract_scaling(self, values: dict) -> dict[str, Any] | None:
        """Extract scaling configuration."""
        scaling = {}
        
        # HPA / autoscaling
        autoscaling = values.get("autoscaling", {})
        if isinstance(autoscaling, dict):
            if "minReplicas" in autoscaling:
                scaling["min_replicas"] = int(autoscaling["minReplicas"])
            if "maxReplicas" in autoscaling:
                scaling["max_replicas"] = int(autoscaling["maxReplicas"])
            if autoscaling.get("enabled"):
                scaling["strategy"] = "hpa"
        
        # Replica count
        replicas = values.get("replicaCount") or values.get("replicas")
        if replicas is not None:
            scaling["current_replicas"] = int(replicas)
        
        return scaling if scaling else None

    def _is_gateway(self, values: dict, service_name: str) -> bool:
        """Determine if a service is a gateway based on configuration."""
        name_lower = service_name.lower()
        if any(keyword in name_lower for keyword in [
            "gateway", "proxy", "ingress", "alb", "nginx", "haproxy", "cloudflare"
        ]):
            return True
        
        # Check if it has routing config
        if any(key in values for key in ["routing", "ingress", "gateway"]):
            return True
        
        return False
