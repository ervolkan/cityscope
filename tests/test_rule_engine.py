"""Tests for the rule engine."""

import pytest

from src.registration.rule_engine import (
    check_rule_r001_tier_dependency,
    check_rule_r008_circular_dependencies,
    check_rule_r009_unique_ids,
    check_rule_r010_retirement_date,
    run_all_rules,
)
from src.registration.reference_validator import load_all_declarations


class TestRuleR001:
    """R001: Tier-0 cannot depend on tier-3."""

    def test_tier0_depends_on_tier3_fails(self):
        entities = {
            "tier0-service": {
                "metadata": {"id": "tier0-service"},
                "spec": {
                    "type": "service",
                    "tier": 0,
                    "depends_on": [{"target": "tier3-tool"}],
                },
            },
            "tier3-tool": {
                "metadata": {"id": "tier3-tool"},
                "spec": {
                    "type": "service",
                    "tier": 3,
                    "depends_on": [],
                },
            },
        }
        errors = check_rule_r001_tier_dependency(entities)
        assert len(errors) == 1
        assert "R001" in errors[0]

    def test_tier0_depends_on_tier1_passes(self):
        entities = {
            "tier0-service": {
                "metadata": {"id": "tier0-service"},
                "spec": {
                    "type": "service",
                    "tier": 0,
                    "depends_on": [{"target": "tier1-support"}],
                },
            },
            "tier1-support": {
                "metadata": {"id": "tier1-support"},
                "spec": {
                    "type": "service",
                    "tier": 1,
                    "depends_on": [],
                },
            },
        }
        errors = check_rule_r001_tier_dependency(entities)
        assert not errors


class TestRuleR008:
    """R008: No circular dependencies."""

    def test_cycle_detected(self):
        entities = {
            "a": {
                "metadata": {"id": "a"},
                "spec": {
                    "depends_on": [{"target": "b"}],
                },
            },
            "b": {
                "metadata": {"id": "b"},
                "spec": {
                    "depends_on": [{"target": "a"}],
                },
            },
        }
        errors = check_rule_r008_circular_dependencies(entities)
        assert len(errors) == 1
        assert "R008" in errors[0]

    def test_no_cycle_passes(self):
        entities = {
            "a": {
                "metadata": {"id": "a"},
                "spec": {
                    "depends_on": [{"target": "b"}],
                },
            },
            "b": {
                "metadata": {"id": "b"},
                "spec": {
                    "depends_on": [],
                },
            },
        }
        errors = check_rule_r008_circular_dependencies(entities)
        assert not errors


class TestRuleR009:
    """R009: Unique entity IDs."""

    def test_duplicate_ids_fail(self):
        entities = {
            "file1.yaml": {
                "metadata": {"id": "nexus-wallet"},
                "spec": {},
            },
            "file2.yaml": {
                "metadata": {"id": "nexus-wallet"},
                "spec": {},
            },
        }
        errors = check_rule_r009_unique_ids(entities)
        assert len(errors) == 1
        assert "R009" in errors[0]

    def test_unique_ids_pass(self):
        entities = {
            "file1.yaml": {
                "metadata": {"id": "nexus-wallet"},
                "spec": {},
            },
            "file2.yaml": {
                "metadata": {"id": "nexus-payment"},
                "spec": {},
            },
        }
        errors = check_rule_r009_unique_ids(entities)
        assert not errors


class TestRuleR010:
    """R010: Deprecated/retired entities need retirement_date."""

    def test_deprecated_without_date_fails(self):
        entities = {
            "old-service": {
                "metadata": {"id": "old-service"},
                "spec": {
                    "lifecycle": "deprecated",
                },
            },
        }
        errors = check_rule_r010_retirement_date(entities)
        assert len(errors) == 1
        assert "R010" in errors[0]

    def test_deprecated_with_date_passes(self):
        entities = {
            "old-service": {
                "metadata": {"id": "old-service"},
                "spec": {
                    "lifecycle": "deprecated",
                    "retirement_date": "2026-06-01",
                },
            },
        }
        errors = check_rule_r010_retirement_date(entities)
        assert not errors


class TestAllRules:
    """Integration test for run_all_rules."""

    def test_empty_graph_passes(self):
        errors = run_all_rules({})
        assert not errors
