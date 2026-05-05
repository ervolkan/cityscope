"""Bootstrap Collector CLI entry point."""

import click

from rich.console import Console

console = Console()


@click.group()
def main():
    """Bootstrap Collector — Generate draft entity declarations from IaC."""
    pass


if __name__ == "__main__":
    main()
