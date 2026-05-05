"""CityScope registration CLI — validate and consolidate entity declarations."""

import json
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from src.registration.validator import (
    load_schema,
    validate_all_declarations,
    validate_schema_integrity,
)
from src.registration.reference_validator import (
    validate_references,
    load_all_declarations,
)
from src.registration.rule_engine import run_all_rules

console = Console()


@click.group()
def main():
    """CityScope Registration Pipeline — validate declarations and produce ontology.json."""
    pass


@main.command()
@click.option(
    "--schema",
    "-s",
    type=click.Path(exists=True),
    default="src/ontology/ontology-schema.json",
    help="Path to ontology JSON Schema.",
)
@click.option(
    "--declarations",
    "-d",
    type=click.Path(exists=True),
    default="declarations",
    help="Path to declarations directory.",
)
@click.option(
    "--rules-file",
    "-r",
    type=click.Path(exists=True),
    default="src/ontology/rules.yaml",
    help="Path to rules YAML file.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Path to write ontology.json (default: print to stdout).",
)
def validate(schema: str, declarations: str, rules_file: str, output: str | None):
    """Validate all declarations against schema and rules."""
    errors_found = False

    # Stage 1: Schema integrity
    console.print("[bold blue]Stage 1:[/bold blue] Validating ontology schema integrity...")
    schema_errors = validate_schema_integrity(schema)
    if schema_errors:
        errors_found = True
        for err in schema_errors:
            console.print(f"  [red]✗[/red] {err}")
    else:
        console.print("  [green]✓[/green] Schema is valid")

    # Stage 2: Declaration validation
    console.print("[bold blue]Stage 2:[/bold blue] Validating declarations against schema...")
    results = validate_all_declarations(schema, declarations)
    if not results:
        console.print("  [yellow]⚠[/yellow] No declarations found to validate")
    for filename, errors in results.items():
        if errors:
            errors_found = True
            console.print(f"  [red]✗[/red] {filename}")
            for err in errors:
                console.print(f"    - {err}")
        else:
            console.print(f"  [green]✓[/green] {filename}")

    # Stage 3: Reference validation
    console.print("[bold blue]Stage 3:[/bold blue] Validating cross-entity references...")
    ref_errors = validate_references(declarations)
    if ref_errors:
        errors_found = True
        for err in ref_errors:
            console.print(f"  [red]✗[/red] {err}")
    else:
        console.print("  [green]✓[/green] All references valid")

    # Stage 4: Rule enforcement
    console.print("[bold blue]Stage 4:[/bold blue] Running ontology rules...")
    entities = load_all_declarations(declarations)
    rule_errors = run_all_rules(entities)
    if rule_errors:
        errors_found = True
        for err in rule_errors:
            console.print(f"  [red]✗[/red] {err}")
    else:
        console.print("  [green]✓[/green] All rules pass")

    # Summary
    if errors_found:
        console.print("\n[bold red]✗ Validation FAILED[/bold red]")
        sys.exit(1)
    else:
        console.print("\n[bold green]✓ Validation PASSED[/bold green]")
        
        # Generate ontology.json
        ontology = _consolidate(entities)
        if output:
            with open(output, "w") as f:
                json.dump(ontology, f, indent=2)
            console.print(f"[green]✓[/green] Wrote ontology to {output}")
        else:
            console.print(json.dumps(ontology, indent=2))


def _consolidate(entities: dict[str, dict]) -> dict:
    """Consolidate entity declarations into a single ontology structure."""
    return {
        "apiVersion": "cityscope.dev/v1",
        "kind": "Ontology",
        "metadata": {
            "name": "cityscope-ontology",
            "entity_count": len(entities),
        },
        "entities": entities,
    }


if __name__ == "__main__":
    main()
