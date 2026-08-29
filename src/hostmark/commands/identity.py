"""CLI callbacks for local identity storage."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from hostmark.cli_support import command_boundary
from hostmark.services.identity_store import (
    IdentityScope,
    discover_identity,
    identity_paths,
    initialize_identity,
    maybe_reexec_for_system_scope,
)


class Scope(StrEnum):
    """User-selectable identity storage scope."""

    system = "system"
    user = "user"


app = typer.Typer(help="Initialize and inspect the stable local host ID.", no_args_is_help=True)


@app.command("init")
@command_boundary
def init_identity(
    scope: Annotated[Scope, typer.Option(help="Identity storage scope.")] = Scope.system,
    sudo: Annotated[bool, typer.Option("--sudo", help="Re-exec system initialization through sudo on POSIX.")] = False,
) -> None:
    """Generate and durably store one UUIDv4 identity."""

    scope_value: IdentityScope = "system" if scope is Scope.system else "user"
    if maybe_reexec_for_system_scope(scope=scope_value, use_sudo=sudo):
        return
    result = initialize_identity(scope=scope_value, paths=identity_paths())
    typer.echo(f"Host ID: {result.host_id}")
    typer.echo(f"Scope: {result.scope}")
    typer.echo(f"Identity file: {result.path}")
    typer.echo(f"Next: hostmark registry register <hostname> --host-id {result.host_id}")


@app.command("show")
@command_boundary
def show_identity(
    raw: Annotated[bool, typer.Option("--raw", help="Print only the UUID.")] = False,
) -> None:
    """Show the single discovered local identity."""

    result = discover_identity(identity_paths())
    if raw:
        typer.echo(result.host_id)
        return
    typer.echo(f"Host ID: {result.host_id}")
    typer.echo(f"Scope: {result.scope}")
    typer.echo(f"Identity file: {result.path}")


__all__ = ["Scope", "app"]
