from __future__ import annotations

import typer
from rich.console import Console

from ..config import _resolve_data_dir, get_config_path, load_config
from .engine import create_engine_and_factory, run_migrations

app = typer.Typer(help="Carapace database migration utilities", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    """Keep ``upgrade`` a named subcommand (Typer otherwise collapses a lone command)."""


@app.command()
def upgrade() -> None:
    """Apply Alembic migrations up to the latest revision."""
    config_path = get_config_path()
    config = load_config()
    data_dir = _resolve_data_dir(config_path, config)
    engine, _ = create_engine_and_factory(config.database, data_dir)
    run_migrations(engine)
    engine.dispose()
    console.print("[green]Database upgraded to head.[/green]")


if __name__ == "__main__":
    app()
