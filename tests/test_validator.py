"""Tests for the ontology schema validator."""

import json
from pathlib import Path

import pytest
import yaml

from src.registration.validator import (
    load_schema,
    load_declaration,
    validate_declaration,
    validate_schema_integrity,
)


# Fixtures
@pytest.fixture
def schema_path() -> Path:
    return Path(__file__).parent.parent / "src" / "ontology" / "ontology-schema.json"


@pytest.fixture
def schema(schema_path: Path) -> dict:
    return load_schema(schema_path)


# Valid declaration samples
VALID_SERVICE = {
    "apiVersion": "cityscope.dev/v1",
    "kind": "Entity",
    "metadata": {
        "id": "nexus-wallet",
        "name": "Nexus Wallet Service",
        "domain": "nexus-core",
        "team": "nexus-backend",
        "description": "Handles customer wallet operations, deposits, and withdrawals",
    },
    "spec": {
        "type": "service",
        "tier": 0,
        "lifecycle": "active",
        "protocols": [{"name": "grpc", "port": 8080}],
        "depends_on": [
            {
                "target": "nexus-db-wallet",
                "type": "storage",
                "protocol": "postgres",
            }
        ],
        "scaling": {
            "min_replicas": 2,
            "max_replicas": 10,
            "strategy": "hpa",
        },
        "slo": {
            "availability_percent": 99.99,
            "latency_p99_ms": 200,
        },
        "image": "ghcr.io/betcorewin/nexus-wallet:latest",
    },
}


class TestSchemaIntegrity:
    """Tests for the ontology JSON Schema itself."""

    def test_schema_loads(self, schema_path: Path):
        """Schema file should be loadable as valid JSON."""
        schema = load_schema(schema_path)
        assert "properties" in schema
        assert "metadata" in schema["properties"]
        assert "spec" in schema["properties"]

    def test_schema_validates_against_metaschema(self, schema_path: Path):
        """Schema should be valid JSON Schema draft 2020-12."""
        errors = validate_schema_integrity(schema_path)
        assert not errors, f"Schema has errors: {errors}"

    def test_schema_requires_api_version(self, schema):
        """apiVersion must be 'cityscope.dev/v1'."""
        declaration = {**VALID_SERVICE, "apiVersion": "wrong/version"}
        errors = validate_declaration(schema, declaration)
        assert any("apiVersion" in e for e in errors)

    def test_schema_requires_kind_entity(self, schema):
        """kind must be 'Entity'."""
        declaration = {**VALID_SERVICE, "kind": "WrongKind"}
        errors = validate_declaration(schema, declaration)
        assert any("kind" in e for e in errors)


class TestMetadataValidation:
    """Tests for metadata field validation."""

    def test_valid_service_passes(self, schema):
        """A well-formed service declaration should validate."""
        errors = validate_declaration(schema, VALID_SERVICE)
        assert not errors, f"Expected no errors, got: {errors}"

    def test_missing_id_fails(self, schema):
        """metadata.id is required."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"].pop("id")
        errors = validate_declaration(schema, declaration)
        assert any("id" in e.lower() for e in errors)

    def test_invalid_id_format_fails(self, schema):
        """metadata.id must match pattern."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"]["id"] = "INVALID ID WITH SPACES"
        errors = validate_declaration(schema, declaration)
        assert any("id" in e.lower() for e in errors)

    def test_missing_domain_fails(self, schema):
        """metadata.domain is required."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"].pop("domain")
        errors = validate_declaration(schema, declaration)
        assert any("domain" in e.lower() for e in errors)

    def test_missing_team_fails(self, schema):
        """metadata.team is required."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"].pop("team")
        errors = validate_declaration(schema, declaration)
        assert any("team" in e.lower() for e in errors)

    def test_description_too_short(self, schema):
        """metadata.description must be at least 10 chars."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"]["description"] = "Too short"
        errors = validate_declaration(schema, declaration)
        assert any("description" in e.lower() for e in errors)


class TestSpecValidation:
    """Tests for spec field validation."""

    def test_missing_type_fails(self, schema):
        """spec.type is required."""
        declaration = {**VALID_SERVICE}
        declaration["spec"].pop("type")
        errors = validate_declaration(schema, declaration)
        assert any("type" in e.lower() for e in errors)

    def test_invalid_type_fails(self, schema):
        """spec.type must be one of the valid entity types."""
        declaration = {**VALID_SERVICE}
        declaration["spec"]["type"] = "invalid_type"
        errors = validate_declaration(schema, declaration)
        assert any("type" in e.lower() for e in errors)

    def test_tier_out_of_range(self, schema):
        """tier must be 0-3."""
        declaration = {**VALID_SERVICE}
        declaration["spec"]["tier"] = 5
        errors = validate_declaration(schema, declaration)
        assert any("tier" in e.lower() or "maximum" in e.lower() for e in errors)

    def test_invalid_lifecycle_fails(self, schema):
        """lifecycle must be a valid state."""
        declaration = {**VALID_SERVICE}
        declaration["spec"]["lifecycle"] = "nonexistent"
        errors = validate_declaration(schema, declaration)
        assert any("lifecycle" in e.lower() for e in errors)

    def test_valid_datastore_with_backup(self, schema):
        """A datastore entity with backup config should validate."""
        datastore = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": "nexus-db-wallet",
                "name": "Wallet PostgreSQL Database",
                "domain": "nexus-infra",
                "team": "nexus-platform",
                "description": "PostgreSQL database for the wallet service",
            },
            "spec": {
                "type": "datastore",
                "tier": 1,
                "lifecycle": "active",
                "protocols": [{"name": "postgres", "port": 5432}],
                "depends_on": [],
                "backup": {
                    "enabled": True,
                    "retention_days": 30,
                    "frequency": "daily",
                    "storage_location": "s3://nexus-backups/wallet-db",
                },
            },
        }
        errors = validate_declaration(schema, datastore)
        assert not errors, f"Expected no errors, got: {errors}"

    def test_sync_dep_requires_protocol_and_timeout(self, schema):
        """Sync dependencies require protocol and timeout_ms."""
        declaration = {**VALID_SERVICE}
        declaration["spec"]["depends_on"] = [
            {
                "target": "nexus-identity",
                "type": "sync",
                # Missing protocol and timeout_ms
            }
        ]
        errors = validate_declaration(schema, declaration)
        # The allOf condition should catch this
        assert any("protocol" in e.lower() or "timeout" in e.lower() for e in errors)


class TestAdditionalProperties:
    """Tests for additionalProperties: false enforcement."""

    def test_extra_metadata_field_fails(self, schema):
        """Unknown fields in metadata should be rejected."""
        declaration = {**VALID_SERVICE}
        declaration["metadata"]["extra_field"] = "should not exist"
        errors = validate_declaration(schema, declaration)
        assert any("extra" in e.lower() or "additional" in e.lower() for e in errors)

    def test_extra_spec_field_fails(self, schema):
        """Unknown fields in spec should be rejected."""
        declaration = {**VALID_SERVICE}
        declaration["spec"]["unknown_field"] = "value"
        errors = validate_declaration(schema, declaration)
        assert any("unknown" in e.lower() or "additional" in e.lower() for e in errors)

    def test_top_level_extra_field_fails(self, schema):
        """Unknown top-level fields should be rejected."""
        declaration = {**VALID_SERVICE, "extra": "field"}
        errors = validate_declaration(schema, declaration)
        assert any("extra" in e.lower() or "additional" in e.lower() for e in errors)
