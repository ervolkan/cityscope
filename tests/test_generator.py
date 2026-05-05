"""Tests for the Bootstrap Collector declaration generator."""

import pytest

from src.bootstrap.generator import DeclarationGenerator


class TestDeclarationGenerator:
    """Tests for the declaration generator."""

    def test_generate_declarations_creates_files(self):
        """Declarations should be generated with correct filenames."""
        entities = [
            {
                "apiVersion": "cityscope.dev/v1",
                "kind": "Entity",
                "metadata": {"id": "nexus-wallet"},
                "spec": {"type": "service"},
                "_todos": {"domain": True, "tier": True},
            },
            {
                "apiVersion": "cityscope.dev/v1",
                "kind": "Entity",
                "metadata": {"id": "nexus-payment"},
                "spec": {"type": "service"},
                "_todos": {"domain": True},
            },
        ]
        generator = DeclarationGenerator()
        declarations = generator.generate_declarations(entities)
        
        assert "nexus-wallet.yaml" in declarations
        assert "nexus-payment.yaml" in declarations
        assert "_todos" not in declarations["nexus-wallet.yaml"]
        assert "_todos" not in declarations["nexus-payment.yaml"]

    def test_mark_todos_adds_domain_todo(self):
        """Empty domain should be marked as TODO."""
        entity = {
            "metadata": {"id": "test", "domain": ""},
            "spec": {"type": "service", "tier": 0},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["domain"] is True

    def test_mark_todos_adds_team_todo(self):
        """Empty team should be marked as TODO."""
        entity = {
            "metadata": {"id": "test", "team": ""},
            "spec": {"type": "service", "tier": 0},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["team"] is True

    def test_mark_todos_adds_description_todo(self):
        """Auto-extracted description should be marked as TODO."""
        entity = {
            "metadata": {"id": "test", "description": "Auto-extracted from Terraform: test"},
            "spec": {"type": "service", "tier": 0},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["description"] is True

    def test_mark_todos_adds_tier_todo(self):
        """Default tier 0 should be marked as TODO."""
        entity = {
            "metadata": {"id": "test", "domain": "nexus-core", "team": "nexus-backend", "description": "Test service"},
            "spec": {"type": "service", "tier": 0},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["tier"] is True

    def test_mark_todos_adds_slo_todo(self):
        """SLO should always be marked as TODO (bootstrap can't know real targets)."""
        entity = {
            "metadata": {"id": "test", "domain": "nexus-core", "team": "nexus-backend", "description": "Test"},
            "spec": {"type": "service", "tier": 0},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["slo"] is True

    def test_mark_todos_adds_backup_for_datastore(self):
        """Datastore entities should have backup TODO."""
        entity = {
            "metadata": {"id": "test-db", "domain": "nexus-infra", "team": "nexus-platform", "description": "Test DB"},
            "spec": {"type": "datastore", "tier": 1},
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert entity["_todos"]["backup"] is True

    def test_mark_todos_adds_sync_timeout_for_deps(self):
        """Sync dependencies without timeout should be marked as TODO."""
        entity = {
            "metadata": {"id": "test", "domain": "nexus-core", "team": "nexus-backend", "description": "Test"},
            "spec": {
                "type": "service",
                "tier": 0,
                "depends_on": [
                    {"target": "other-service", "type": "sync", "protocol": "grpc"}
                ],
            },
        }
        generator = DeclarationGenerator()
        generator.mark_todos(entity)
        assert "sync_timeout_other-service" in entity["_todos"]
        # The dependency should have timeout_ms set to placeholder
        assert entity["spec"]["depends_on"][0]["timeout_ms"] == 0
