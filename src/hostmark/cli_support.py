from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import typer

from hostmark.domain.errors import HostmarkError

P = ParamSpec("P")
R = TypeVar("R")


def command_boundary(function: Callable[P, R]) -> Callable[P, R]:
    """Convert only known project errors into stable, traceback-free exits."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except HostmarkError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=exc.exit_code) from None

    return wrapped


__all__ = ["command_boundary"]
