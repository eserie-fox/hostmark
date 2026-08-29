"""Thin root Typer application for hostmark."""

from __future__ import annotations

from typing import Annotated

import typer

from hostmark.commands.check import check_command
from hostmark.commands.identity import app as identity_app
from hostmark.commands.registry import app as registry_app
from hostmark.version import __version__

app = typer.Typer(
    help="Cross-platform host identity and canonical hostname registry CLI backed by Git.",
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(identity_app, name="identity")
app.add_typer(registry_app, name="registry")
app.command("check")(check_command)


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the package version and exit.", is_eager=True),
    ] = False,
) -> None:
    """Show help by default and expose a single-source version flag."""

    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def main() -> None:
    """Run the installed console application."""

    app(prog_name="hostmark")


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app", "main"]
