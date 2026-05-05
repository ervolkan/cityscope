"""Bootstrap Collector — parse IaC repositories and generate draft entity declarations."""

import json
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

from src.bootstrap.helm_parser import HelmValuesParser
from src.bootstrap.terraform_parser import TerraformParser
from src.bootstrap.generator import DeclarationGenerator

console = Console()


@click.group()
def main():
    """Bootstrap Collector — Generate draft entity declarations from IaC repositories."""
    pass


@main.command()
@click.option(
    "--source",
    "-s",
    "source_paths",
    multiple=True,
    required=True,
    help="Path(s) to IaC repository directories (Helm values, Terraform files). Can be specified multiple times.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    required=True,
    help="Output directory for generated declaration manifests.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print declarations to stdout without writing files.",
)
@click.option(
    "--entity-type",
    "-t",
    multiple=True,
    default=["service", "gateway", "datastore", "cache", "messagebus", "storage", "compute", "network"],
    help="Filter entity types to extract. Default: all types.",
)
def extract(
    source_paths: tuple[str, ...],
    output: str,
    dry_run: bool,
    entity_type: tuple[str, ...],
):
    """Parse IaC repositories and generate draft entity declaration manifests.
    
    Supported sources:
    - Helm values files (betcorewin-cd style)
    - Terraform files (infra-main style)
    """
    console.print("[bold blue]Bootstrap Collector[/bold blue]")
    console.print(f"  Source directories: {', '.join(source_paths)}")
    console.print(f"  Output directory: {output}")
    console.print(f"  Entity types: {', '.join(entity_type)}")
    console.print()

    generator = DeclarationGenerator()
    total_entities = 0
    total_warnings = 0

    for source_path in source_paths:
        path = Path(source_path)
        if not path.exists():
            console.print(f"[red]✗[/red] Source path does not exist: {source_path}")
            continue

        console.print(f"[blue]Processing:[/blue] {path}")
        
        # Detect IaC type and parse
        helm_parser = HelmValuesParser(path)
        helm_entities = helm_parser.parse()
        console.print(f"  Found {len(helm_entities)} Helm entities")
        
        tf_parser = TerraformParser(path)
        tf_entities = tf_parser.parse()
        console.print(f"  Found {len(tf_entities)} Terraform entities")
        
        # Combine and filter
        all_entities = helm_entities + tf_entities
        filtered = [e for e in all_entities if e.get("spec", {}).get("type") in entity_type]
        
        # Add TODO markers for unextractable fields
        for entity in filtered:
            generator.mark_todos(entity)
            total_warnings += len([k for k, v in entity.get("_todos", {}).items() if v])
        
        # Generate declarations
        declarations = generator.generate_declarations(filtered)
        total_entities += len(declarations)
        
        if dry_run:
            for filename, content in declarations.items():
                console.print(f"\n[bold]=== {filename} ===[/bold]")
                console.print(yaml.dump(content, default_flow_style=False, sort_keys=False))
        else:
            # Write to output directory
            out_path = Path(output)
            out_path.mkdir(parents=True, exist_ok=True)
            for filename, content in declarations.items():
                file_path = out_path / filename
                with open(file_path, "w") as f:
                    yaml.dump(content, f, default_flow_style=False, sort_keys=False, width=120)
                console.print(f"  [green]✓[/green] Created {filename}")

    console.print()
    console.print(f"[bold green]Summary:[/bold green] {total_entities} draft declarations generated with {total_warnings} TODO fields")
    console.print("[yellow]⚠[/yellow] Fields marked as TODO require manual engineer review")
    if not dry_run:
        console.print(f"[blue]📁[/blue] Declarations written to: {output}")


@main.command()
@click.option(
    "--manifest",
    "-m",
    "manifest_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to a declaration manifest YAML file.",
)
@click.option(
    "--schema",
    "-s",
    "schema_path",
    type=click.Path(exists=True),
    default="src/ontology/ontology-schema.json",
    help="Path to ontology JSON Schema.",
)
def validate(manifest_path: str, schema_path: str):
    """Validate a single declaration manifest against the ontology schema."""
    from src.registration.validator import load_schema, validate_declaration

    console.print(f"[blue]Validating:[/blue] {manifest_path}")
    schema = load_schema(schema_path)
    
    with open(manifest_path, "r") as f:
        declaration = yaml.safe_load(f)
    
    errors = validate_declaration(schema, declaration)
    if errors:
        console.print(f"[red]✗ Validation failed with {len(errors)} errors:[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise click.Abort()
    else:
        console.print("[green]✓ Manifest is valid[/green]")


@main.command()
@click.option(
    "--before",
    "before_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to the old declaration manifest.",
)
@click.option(
    "--after",
    "after_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to the new declaration manifest.",
)
def diff(before_path: str, after_path: str):
    """Compare two declaration manifests and show differences."""
    with open(before_path, "r") as f:
        before = yaml.safe_load(f)
    with open(after_path, "r") as f:
        after = yaml.safe_load(f)

    before_json = json.dumps(before, indent=2, sort_keys=True)
    after_json = json.dumps(after, indent=2, sort_keys=True)

    if before_json == after_json:
        console.print("[green]✓ No differences found[/green]")
    else:
        # Simple key-level diff
        def flatten_dict(d: dict, prefix: str = "") -> dict[str, Any]:
            result = {}
            for k, v in d.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    result.update(flatten_dict(v, key))
                elif isinstance(v, list):
                    result[key] = [
                        flatten_dict(i, f"{key}[{j}]") if isinstance(i, dict) else i
                        for j, i in enumerate(v)
                    ]
                else:
                    result[key] = v
            return result

        flat_before = flatten_dict(before)
        flat_after = flatten_dict(after)
        
        all_keys = set(flat_before.keys()) | set(flat_after.keys())
        
        console.print(f"[yellow]Differences found:[/yellow]")
        for key in sorted(all_keys):
            b_val = flat_before.get(key)
            a_val = flat_after.get(key)
            if b_val != a_val:
                console.print(f"  [yellow]{key}[/yellow]")
                console.print(f"    before: {b_val}")
                console.print(f"    after:  {a_val}")


if __name__ == "__main__":
    main()
