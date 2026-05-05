"""Declaration validator — validates YAML manifests against the ontology JSON Schema."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from rich.console import Console

console = Console()


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    """Load and return the ontology JSON Schema."""
    with open(schema_path, "r") as f:
        return json.load(f)


def load_declaration(declaration_path: str | Path) -> dict[str, Any]:
    """Load a single YAML declaration manifest."""
    with open(declaration_path, "r") as f:
        return yaml.safe_load(f)


def validate_declaration(
    schema: dict[str, Any], declaration: dict[str, Any]
) -> list[str]:
    """Validate a single declaration against the schema.
    
    Returns a list of validation errors. Empty list means valid.
    """
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for error in validator.iter_errors(declaration):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_all_declarations(
    schema_path: str | Path, declarations_dir: str | Path
) -> dict[str, list[str]]:
    """Validate all declaration manifests in a directory.
    
    Returns a dict mapping filenames to their validation errors.
    """
    schema = load_schema(schema_path)
    declarations_dir = Path(declarations_dir)
    results: dict[str, list[str]] = {}
    
    for yaml_file in declarations_dir.glob("*.yaml"):
        if yaml_file.name.startswith("."):
            continue
        declaration = load_declaration(yaml_file)
        errors = validate_declaration(schema, declaration)
        results[yaml_file.name] = errors
    
    for yaml_file in declarations_dir.glob("*.yml"):
        if yaml_file.name.startswith("."):
            continue
        declaration = load_declaration(yaml_file)
        errors = validate_declaration(schema, declaration)
        results[yaml_file.name] = errors
    
    return results


def validate_schema_integrity(schema_path: str | Path) -> list[str]:
    """Validate the schema itself against the JSON Schema draft 2020-12 metaschema."""
    import jsonschema.validators
    schema = load_schema(schema_path)
    errors: list[str] = []
    
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")
    
    return errors
