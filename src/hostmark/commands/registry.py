from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import typer

from hostmark.cli_support import command_boundary
from hostmark.domain.models import HostRecord, Registry
from hostmark.services.identity_store import discover_identity, identity_paths
from hostmark.services.registry_store import (
    format_registry,
    fqdn,
    hosts_filtered,
    initialize_registry,
    mutate_registry,
    new_registry,
    read_registry,
    register_host,
    rename_host,
    resolve_host,
    resolve_registry_path,
    retire_host,
    validate_registry_files,
)


class StatusFilter(StrEnum):
    active = "active"
    retired = "retired"


app = typer.Typer(help="Create, mutate, inspect, format, and validate registries.", no_args_is_help=True)


def _registry_path(explicit: Path | None, *, for_init: bool = False) -> Path:
    return resolve_registry_path(explicit, for_init=for_init)


def _print_dry_run(diff: str | None) -> None:
    if diff:
        typer.echo(diff, nl=not diff.endswith("\n"))


@app.command("init")
@command_boundary
def init_registry(
    dns_suffix: Annotated[str, typer.Option("--dns-suffix", help="Lower-case node DNS suffix.")],
    site: Annotated[list[str], typer.Option("--site", help="Site code; repeat for multiple sites.")],
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
) -> None:
    """Create a new canonical empty registry."""

    path = _registry_path(registry, for_init=True)
    document = new_registry(dns_suffix=dns_suffix, sites=site)
    initialize_registry(path, document)
    typer.echo(f"Initialized registry: {path}")
    typer.echo("Next: hostmark registry register <hostname>")


@app.command("register")
@command_boundary
def register_command(
    hostname: Annotated[str, typer.Argument(help="New canonical short hostname.")],
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
    host_id: Annotated[str | None, typer.Option("--host-id", help="Explicit canonical UUIDv4.")] = None,
    notes: Annotated[str | None, typer.Option("--notes", help="Optional non-empty note.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and print a diff without writing.")] = False,
) -> None:
    """Register one active host identity."""

    path = _registry_path(registry)
    selected_id = host_id
    if selected_id is None:
        selected_id = discover_identity(identity_paths()).host_id
    result = mutate_registry(
        path,
        lambda current: register_host(current, host_id=selected_id, hostname=hostname, notes=notes),
        dry_run=dry_run,
    )
    registered = resolve_host(result.candidate, selected_id)
    _print_dry_run(result.diff)
    prefix = "Dry run - would register" if dry_run else "Registered"
    typer.echo(f"{prefix}: {registered.hostname}")
    typer.echo(f"Host ID: {registered.host_id}")
    typer.echo(f"FQDN: {fqdn(result.candidate, registered)}")


@app.command("rename")
@command_boundary
def rename_command(
    host: Annotated[str, typer.Argument(help="Current hostname or host UUID.")],
    new_hostname: Annotated[str, typer.Argument(help="New canonical short hostname.")],
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and print a diff without writing.")] = False,
) -> None:
    """Rename the same active identity and append its old name to history."""

    path = _registry_path(registry)
    result = mutate_registry(
        path,
        lambda current: rename_host(current, selector=host, new_hostname=new_hostname),
        dry_run=dry_run,
    )
    before = resolve_host(result.original, host)
    after = next(item for item in result.candidate.hosts if item.host_id == before.host_id)
    _print_dry_run(result.diff)
    prefix = "Dry run - would rename" if dry_run else "Renamed"
    typer.echo(f"{prefix}: {before.hostname} -> {after.hostname}")
    typer.echo(f"Expected FQDN: {fqdn(result.candidate, after)}")


@app.command("retire")
@command_boundary
def retire_command(
    host: Annotated[str, typer.Argument(help="Current hostname or host UUID.")],
    reason: Annotated[str, typer.Option("--reason", help="Required non-empty retirement reason.")],
    replacement: Annotated[
        str | None,
        typer.Option("--replacement", help="Optional active replacement hostname or UUID."),
    ] = None,
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and print a diff without writing.")] = False,
) -> None:
    """Retire one host identity permanently."""

    path = _registry_path(registry)
    result = mutate_registry(
        path,
        lambda current: retire_host(
            current,
            selector=host,
            reason=reason,
            replacement_selector=replacement,
        ),
        dry_run=dry_run,
    )
    before = resolve_host(result.original, host)
    after = next(item for item in result.candidate.hosts if item.host_id == before.host_id)
    assert after.retirement is not None
    _print_dry_run(result.diff)
    prefix = "Dry run - would retire" if dry_run else "Retired"
    typer.echo(f"{prefix}: {after.hostname} ({after.host_id})")
    typer.echo(f"Retired at: {after.retirement.retired_at}")
    typer.echo(f"Reason: {after.retirement.reason}")
    typer.echo(f"Replacement host ID: {after.retirement.replacement_host_id or '-'}")


@app.command("list")
@command_boundary
def list_command(
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
    status: Annotated[StatusFilter | None, typer.Option("--status", help="Filter by lifecycle status.")] = None,
    site: Annotated[str | None, typer.Option("--site", help="Filter by site code.")] = None,
) -> None:
    """List hosts in canonical hostname order."""

    document = read_registry(_registry_path(registry), require_canonical=True)
    status_value: Literal["active", "retired"] | None = None
    if status is not None:
        status_value = "active" if status is StatusFilter.active else "retired"
    hosts = hosts_filtered(document.registry, status_filter=status_value, site_filter=site)
    by_id = {host.host_id: host for host in document.registry.hosts}
    typer.echo("HOSTNAME\tSTATUS\tHOST ID\tFQDN\tREPLACEMENT")
    for host in hosts:
        replacement_name = "-"
        if host.retirement is not None and host.retirement.replacement_host_id is not None:
            replacement_name = by_id[host.retirement.replacement_host_id].hostname
        typer.echo(
            f"{host.hostname}\t{host.status}\t{host.host_id}\t{fqdn(document.registry, host)}\t{replacement_name}"
        )


@app.command("show")
@command_boundary
def show_command(
    host: Annotated[str, typer.Argument(help="Current hostname or host UUID.")],
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
) -> None:
    """Show one current registry record and derived relationships."""

    document = read_registry(_registry_path(registry), require_canonical=True)
    selected = resolve_host(document.registry, host)
    _print_host(document.registry, selected)


def _print_host(registry: Registry, host: HostRecord) -> None:
    by_id = {item.host_id: item for item in registry.hosts}
    retirement = host.retirement
    replacement_id = retirement.replacement_host_id if retirement is not None else None
    replacement_name = by_id[replacement_id].hostname if replacement_id is not None else "-"
    replaces = sorted(
        item.hostname
        for item in registry.hosts
        if item.retirement is not None and item.retirement.replacement_host_id == host.host_id
    )
    typer.echo(f"Host ID: {host.host_id}")
    typer.echo(f"Hostname: {host.hostname}")
    typer.echo(f"FQDN: {fqdn(registry, host)}")
    typer.echo(f"Status: {host.status}")
    typer.echo(f"Registered at: {host.registered_at}")
    typer.echo(f"Previous hostnames: {', '.join(host.previous_hostnames) if host.previous_hostnames else '-'}")
    typer.echo(f"Retired at: {retirement.retired_at if retirement is not None else '-'}")
    typer.echo(f"Retirement reason: {retirement.reason if retirement is not None else '-'}")
    typer.echo(f"Replacement host ID: {replacement_id or '-'}")
    typer.echo(f"Replacement hostname: {replacement_name}")
    typer.echo(f"Notes: {host.notes if host.notes is not None else '-'}")
    typer.echo(f"Replaces retired hosts: {', '.join(replaces) if replaces else '-'}")


@app.command("format")
@command_boundary
def format_command(
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Registry path.")] = None,
    check: Annotated[bool, typer.Option("--check", help="Check exact canonical bytes without writing.")] = False,
) -> None:
    """Check or apply canonical JSON representation."""

    path = _registry_path(registry)
    result = format_registry(path, check=check)
    if check:
        typer.echo(f"Registry formatting is canonical: {path}")
    elif result.changed:
        typer.echo(f"Formatted registry: {path}")
    else:
        typer.echo(f"Registry already canonical: {path}")


@app.command("validate")
@command_boundary
def validate_command(
    registry: Annotated[Path | None, typer.Option("--registry", "-r", help="Candidate registry path.")] = None,
    against: Annotated[Path | None, typer.Option("--against", help="Older authoritative baseline path.")] = None,
) -> None:
    """Validate a complete snapshot and optional history transition."""

    path = _registry_path(registry)
    baseline = None if against is None else against.expanduser().resolve(strict=False)
    summary = validate_registry_files(path, baseline)
    typer.echo(f"Registry is valid and canonical: {path}")
    if summary is None:
        return
    typer.echo(f"Baseline transition is valid: {baseline}")
    _print_baseline_summary(summary)


def _print_baseline_summary(summary: object) -> None:
    from hostmark.services.registry_validation import BaselineSummary

    assert isinstance(summary, BaselineSummary)
    typer.echo(f"Additions: {', '.join(summary.additions) if summary.additions else '-'}")
    typer.echo(f"Renames: {', '.join(summary.renames) if summary.renames else '-'}")
    typer.echo(f"Retirements: {', '.join(summary.retirements) if summary.retirements else '-'}")
    typer.echo(f"Notes changes: {', '.join(summary.notes_changes) if summary.notes_changes else '-'}")
    typer.echo(f"Site additions: {', '.join(summary.site_additions) if summary.site_additions else '-'}")
    if summary.reason_corrections:
        typer.echo(f"Retirement reason corrections: {', '.join(summary.reason_corrections)}")
    if summary.replacement_assignments:
        typer.echo(f"Replacement assignments: {', '.join(summary.replacement_assignments)}")
    if summary.dns_suffix_warning is not None:
        typer.echo(f"WARNING: {summary.dns_suffix_warning}")


__all__ = ["StatusFilter", "app"]
