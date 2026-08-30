from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hostmark.cli_support import command_boundary
from hostmark.services.repository import (
    initialize_repository,
    resolve_repository_paths,
    sync_repository,
    validate_repository_marker,
)

app = typer.Typer(help="Discover, initialize, and fast-forward a Hostmark inventory repository.", no_args_is_help=True)


@app.command("path")
@command_boundary
def path_command(
    repo: Annotated[Path | None, typer.Option("--repo", help="Repository root path.")] = None,
) -> None:
    """Show the selected repository, marker, and registry paths."""

    paths = resolve_repository_paths(repo)
    if paths.root.exists():
        validate_repository_marker(paths)
    typer.echo(f"Repository: {paths.root}")
    typer.echo(f"Marker:     {paths.marker}")
    typer.echo(f"Registry:   {paths.registry}")


@app.command("init")
@command_boundary
def init_command(
    dns_suffix: Annotated[str, typer.Option("--dns-suffix", help="Lower-case node DNS suffix.")],
    site: Annotated[list[str], typer.Option("--site", help="Site code; repeat for multiple sites.")],
    repo: Annotated[Path | None, typer.Option("--repo", help="Repository root path.")] = None,
) -> None:
    """Initialize an empty local Git repository and canonical registry."""

    result = initialize_repository(
        resolve_repository_paths(repo),
        dns_suffix=dns_suffix,
        sites=site,
    )
    typer.echo(f"Initialized repository: {result.paths.root}")
    typer.echo(f"Marker: {result.paths.marker}")
    typer.echo(f"Registry: {result.paths.registry}")
    typer.echo(f"Git branch: {result.branch}")
    typer.echo("Next steps:")
    typer.echo(f"  cd {result.paths.root}")
    typer.echo("  git add HOSTMARK_REPOSITORY hosts.json")
    typer.echo('  git commit -m "Initialize hostmark repository"')
    typer.echo("  git remote add origin <remote-url>")
    typer.echo("  git push -u origin main")


@app.command("sync")
@command_boundary
def sync_command(
    repo: Annotated[Path | None, typer.Option("--repo", help="Repository root path.")] = None,
    remote: Annotated[
        str | None, typer.Option("--remote", help="Remote URL used only for clone or verification.")
    ] = None,
) -> None:
    """Clone or fast-forward the selected repository and validate its registry."""

    result = sync_repository(resolve_repository_paths(repo), remote=remote)
    action = "Cloned" if result.operation == "cloned" else "Synchronized"
    typer.echo(f"{action} repository: {result.paths.root}")
    typer.echo(f"Registry: {result.paths.registry}")


__all__ = ["app"]
