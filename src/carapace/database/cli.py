from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from ..config import _resolve_data_dir, get_config_path, load_config
from .engine import create_engine_and_factory, run_migrations
from .importer import import_all

app = typer.Typer(help="Carapace database migration utilities", no_args_is_help=True)
console = Console()


def _load_factory_and_data_dir():
    config_path = get_config_path()
    config = load_config()
    data_dir = _resolve_data_dir(config_path, config)
    engine, factory = create_engine_and_factory(config.database)
    return engine, factory, data_dir


@app.command()
def upgrade() -> None:
    """Apply Alembic migrations up to the latest revision."""
    config = load_config()
    engine, _ = create_engine_and_factory(config.database)
    run_migrations(engine)
    engine.dispose()
    console.print("[green]Database upgraded to head.[/green]")


@app.command("import-yaml")
def import_yaml(
    dry_run: Annotated[bool, typer.Option(help="Parse and count without writing.")] = False,
    purge: Annotated[bool, typer.Option(help="Empty target tables before importing.")] = False,
) -> None:
    """Import existing YAML/file storage into the database (idempotent)."""
    engine, factory, data_dir = _load_factory_and_data_dir()
    run_migrations(engine)  # ensure schema exists
    console.print(f"Importing from [cyan]{data_dir}[/cyan] (dry_run={dry_run}, purge={purge}) ...")
    counts = import_all(factory, data_dir, purge=purge, dry_run=dry_run)
    console.print(f"[green]{counts.summary()}[/green]")
    if counts.skipped:
        console.print(f"[yellow]Skipped {len(counts.skipped)} existing record(s).[/yellow]")
    engine.dispose()


if __name__ == "__main__":
    app()
