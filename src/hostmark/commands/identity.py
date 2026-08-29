from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from hostmark.cli_support import command_boundary
from hostmark.domain.errors import HostmarkError
from hostmark.services.identity_store import (
    IdentityPaths,
    IdentityScope,
    discover_identity,
    identity_paths,
    initialize_identity,
    maybe_reexec_for_system_scope,
    require_identity_absent,
)


class Scope(StrEnum):
    system = "system"
    user = "user"


app = typer.Typer(help="Initialize and inspect the stable local host ID.", no_args_is_help=True)


@app.command("init")
@command_boundary
def init_identity(
    scope: Annotated[Scope, typer.Option(help="Identity storage scope.")] = Scope.system,
    sudo: Annotated[bool, typer.Option("--sudo", help="Re-exec system initialization through sudo on POSIX.")] = False,
    invoking_user_identity_path: Annotated[
        Path | None,
        typer.Option("--_invoking-user-identity-path", hidden=True),
    ] = None,
) -> None:
    """Generate and durably store one UUIDv4 identity."""

    scope_value: IdentityScope = "system" if scope is Scope.system else "user"
    paths = identity_paths()
    if invoking_user_identity_path is not None:
        if not invoking_user_identity_path.is_absolute():
            raise HostmarkError("internal invoking-user identity path must be absolute")
        paths = IdentityPaths(system=paths.system, user=invoking_user_identity_path)
    if scope_value == "user" and sudo:
        maybe_reexec_for_system_scope(
            scope=scope_value,
            use_sudo=True,
            invoking_user_identity_path=paths.user,
        )
    # Both checks are intentional: the first runs as the invoking user, and
    # initialize_identity repeats it in the sudo child immediately before creation.
    require_identity_absent(paths)
    if maybe_reexec_for_system_scope(
        scope=scope_value,
        use_sudo=sudo,
        invoking_user_identity_path=paths.user,
    ):
        return
    result = initialize_identity(scope=scope_value, paths=paths)
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
