"""Tests for the Bootstrap Collector Helm parser."""

import pytest
import yaml

from src.bootstrap.helm_parser import HelmValuesParser


class TestHelmValuesParser:
    """Tests for Helm values file parsing."""

    def test_extract_service_name_from_nameoverride(self):
        """Service name should be extracted from nameOverride."""
        values = {"nameOverride": "nexus-wallet"}
        parser = HelmValuesParser.__new__(HelmValuesParser)
        name = parser._extract_service_name(values, "values-test.yaml")
        assert name == "nexus-wallet"

    def test_extract_service_name_from_name_override(self):
        """Service name should be extracted from name_override (snake_case)."""
        values = {"name_override": "nexus-payment"}
        parser = HelmValuesParser.__new__(HelmValuesParser)
        name = parser._extract_service_name(values, "values-test.yaml")
        assert name == "nexus-payment"

    def test_to_entity_id_converts_to_lowercase_hyphen(self):
        """Entity ID should be lowercase with hyphens."""
        parser = HelmValuesParser.__new__(HelmValuesParser)
        assert parser._to_entity_id("NexusWallet") == "nexuswallet"
        assert parser._to_entity_id("nexus-wallet") == "nexus-wallet"
        assert parser._to_entity_id("nexus_wallet") == "nexus-wallet"

    def test_detect_grpc_port(self):
        """Port 8080 should be detected as gRPC."""
        values = {"service": {"ports": [{"port": 8080, "name": "grpc"}]}}
        parser = HelmValuesParser.__new__(HelmValuesParser)
        protocols = parser._extract_protocols(values)
        assert len(protocols) == 1
        assert protocols[0]["name"] == "grpc"

    def test_detect_http_port(self):
        """Port 80 should be detected as HTTP."""
        values = {"service": {"ports": [{"port": 80, "name": "http"}]}}
        parser = HelmValuesParser.__new__(HelmValuesParser)
        protocols = parser._extract_protocols(values)
        assert len(protocols) == 1
        assert protocols[0]["name"] == "http"

    def test_detect_orleans_port(self):
        """Port 11111 should be detected as Orleans."""
        values = {"service": {"ports": [{"port": 11111, "name": "orleans"}]}}
        parser = HelmValuesParser.__new__(HelmValuesParser)
        protocols = parser._extract_protocols(values)
        assert len(protocols) == 1
        assert protocols[0]["name"] == "orleans"

    def test_extract_sync_dependencies_from_env_vars(self):
        """Environment variables with GrpcHost should create sync dependencies."""
        values = {
            "nameOverride": "nexus-wallet",
            "env": [
                {"name": "IDENTITY_SERVICE_HOST", "value": "nexus-identity:8080"},
                {"name": "PAYMENT_GRPC_HOST", "value": "nexus-payment:5000"},
            ],
        }
        parser = HelmValuesParser.__new__(HelmValuesParser)
        deps = parser._extract_dependencies(values, "values-test.yaml")
        
        sync_deps = [d for d in deps if d["type"] == "sync"]
        assert len(sync_deps) == 2
        assert any(d["target"] == "nexus-identity" for d in deps)
        assert any(d["target"] == "nexus-payment" for d in deps)

    def test_extract_storage_dependencies_from_connection_strings(self):
        """Connection strings should create storage dependencies."""
        values = {
            "nameOverride": "nexus-wallet",
            "env": [
                {
                    "name": "DB_CONNECTION_STRING",
                    "value": "postgres://user:pass@nexus-db-wallet:5432/wallet",
                }
            ],
        }
        parser = HelmValuesParser.__new__(HelmValuesParser)
        deps = parser._extract_dependencies(values, "values-test.yaml")
        
        storage_deps = [d for d in deps if d["type"] == "storage"]
        assert len(storage_deps) == 1
        assert storage_deps[0]["target"] == "nexus-db-wallet"
        assert storage_deps[0]["protocol"] == "postgres"
        assert storage_deps[0]["critical"] is True

    def test_extract_rabbitmq_dependencies(self):
        """RabbitMQ env vars should create async dependencies."""
        values = {
            "nameOverride": "nexus-wallet",
            "env": [
                {"name": "RABBITMQ_HOST", "value": "amqp://rabbitmq:5672"},
            ],
        }
        parser = HelmValuesParser.__new__(HelmValuesParser)
        deps = parser._extract_dependencies(values, "values-test.yaml")
        
        async_deps = [d for d in deps if d["type"] == "async"]
        assert len(async_deps) == 1
        assert async_deps[0]["protocol"] == "amqp"

    def test_extract_scaling_config(self):
        """HPA config should be extracted correctly."""
        values = {
            "autoscaling": {
                "enabled": True,
                "minReplicas": 2,
                "maxReplicas": 10,
            },
            "replicaCount": 3,
        }
        parser = HelmValuesParser.__new__(HelmValuesParser)
        scaling = parser._extract_scaling(values)
        assert scaling is not None
        assert scaling["min_replicas"] == 2
        assert scaling["max_replicas"] == 10
        assert scaling["current_replicas"] == 3
        assert scaling["strategy"] == "hpa"

    def test_is_gateway_detection(self):
        """Gateway services should be detected by name and config."""
        parser = HelmValuesParser.__new__(HelmValuesParser)
        
        # Name-based detection
        assert parser._is_gateway({}, "nexus-gateway") is True
        assert parser._is_gateway({}, "api-gateway") is True
        assert parser._is_gateway({}, "alb-ingress") is True
        assert parser._is_gateway({}, "cloudflare-proxy") is True
        
        # Config-based detection
        assert parser._is_gateway({"ingress": {}}, "some-service") is True
        assert parser._is_gateway({"gateway": {}}, "some-service") is True
        
        # Regular services
        assert parser._is_gateway({}, "nexus-wallet") is False

    def test_image_extraction_patterns(self):
        """Image should be extracted from various patterns."""
        parser = HelmValuesParser.__new__(HelmValuesParser)
        
        # Direct string
        assert parser._extract_image({"image": "ghcr.io/betcorewin/nexus-wallet:latest"}) == \
            "ghcr.io/betcorewin/nexus-wallet:latest"
        
        # Dict format
        assert parser._extract_image({"image": {"repository": "ghcr.io/betcorewin/nexus-wallet", "tag": "v1.2.3"}}) == \
            "ghcr.io/betcorewin/nexus-wallet:v1.2.3"
        
        # Nested in deployment
        assert parser._extract_image({"deployment": {"image": "my-image:latest"}}) == \
            "my-image:latest"
        
        # No image
        assert parser._extract_image({}) is None
