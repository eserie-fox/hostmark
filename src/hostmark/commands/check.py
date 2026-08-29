"""CLI callback for on-demand local hostname drift detection."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hostmark.cli_support import command_boundary
from hostmark.services.host_state import check_host_state
from hostmark.services.identity_store import discover_identity, identity_paths
from hostmark.services.registry_store import read_registry, resolve_registry_path


@command_boundary
def check_command(
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
) -> None:
    """Report whether local identity and actual short hostname match the registry."""

    identity = discover_identity(identity_paths())
    path = resolve_registry_path(registry)
    document = read_registry(path, require_canonical=True)
    result = check_host_state(document.registry, identity)
    typer.echo(f"Identity file: {result.identity.path}")
    typer.echo(f"Host ID: {result.identity.host_id}")
    typer.echo(f"Registry name: {result.host.hostname}")
    typer.echo(f"Actual name: {result.actual.raw}")
    typer.echo(f"FQDN: {result.fqdn}")
    typer.echo("Status: match")


__all__ = ["check_command"]
