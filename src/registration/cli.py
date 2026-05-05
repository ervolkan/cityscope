"""CityScope CLI entry point."""

import click

from rich.console import Console

console = Console()


@click.group()
def main():
    """CityScope — Infrastructure Ontology Platform."""
    pass


if __name__ == "__main__":
    main()
