"""CLI entrypoints for Moats Verify."""

from __future__ import annotations

import click
import uvicorn

from backend.config import settings


@click.group()
def cli() -> None:
    """Moats Verify command line interface."""


@cli.command()
@click.option("--host", default=settings.API_HOST, show_default=True, help="Host to bind.")
@click.option("--port", default=settings.API_PORT, show_default=True, type=int, help="Port to bind.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload.")
def serve(host: str, port: int, reload: bool) -> None:
    """Run the Moats Verify API server."""

    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
