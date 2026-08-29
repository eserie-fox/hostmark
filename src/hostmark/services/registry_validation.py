from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from hostmark.domain.errors import NonCanonicalRegistryError, RegistryValidationError
from hostmark.domain.models import HostRecord, Registry, Retirement

SCHEMA_VERSION = 1
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_SITE_RE = re.compile(r"^[a-z]{2,6}[1-9][0-9]*$")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class BaselineSummary:
    additions: tuple[str, ...] = ()
    renames: tuple[str, ...] = ()
    retirements: tuple[str, ...] = ()
    notes_changes: tuple[str, ...] = ()
    reason_corrections: tuple[str, ...] = ()
    replacement_assignments: tuple[str, ...] = ()
    site_additions: tuple[str, ...] = ()
    dns_suffix_warning: str | None = None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegistryValidationError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RegistryValidationError(f"non-standard JSON constant is forbidden: {value}")


def strict_json_loads(data: bytes) -> dict[str, Any]:
    """Decode UTF-8 JSON while rejecting BOMs, duplicate keys, and constants."""

    if data.startswith(b"\xef\xbb\xbf"):
        raise RegistryValidationError("registry must be UTF-8 without a BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RegistryValidationError("registry is not valid UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except RegistryValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise RegistryValidationError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise RegistryValidationError("registry document must be a JSON object")
    return value


def validate_host_id(value: object, *, field: str = "host_id") -> str:
    if not isinstance(value, str):
        raise RegistryValidationError(f"{field} must be a canonical UUIDv4 string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise RegistryValidationError(f"{field} is not a valid UUID: {value!r}") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise RegistryValidationError(f"{field} must be a canonical lower-case UUIDv4: {value!r}")
    return value


def validate_site_code(value: object) -> str:
    if not isinstance(value, str) or len(value) > 8 or _SITE_RE.fullmatch(value) is None:
        raise RegistryValidationError(
            f"invalid site code {value!r}; expected 2-6 lower-case letters followed by a positive site number"
        )
    return value


def hostname_site(value: object) -> str:
    """Validate a short canonical hostname and return its site component."""

    if not isinstance(value, str):
        raise RegistryValidationError("hostname must be a string")
    if len(value) > 15:
        raise RegistryValidationError(f"hostname exceeds 15 characters: {value!r}")
    if _HOSTNAME_RE.fullmatch(value) is None or "--" in value:
        raise RegistryValidationError(
            f"invalid hostname {value!r}; use lower-case ASCII letters, digits, and single hyphens"
        )
    if "-" not in value:
        raise RegistryValidationError(f"hostname must begin with a site code followed by '-': {value!r}")
    site = value.split("-", 1)[0]
    validate_site_code(site)
    return site


def validate_dns_suffix(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryValidationError("dns_suffix must be a non-empty string")
    if value != value.lower() or not value.isascii():
        raise RegistryValidationError("dns_suffix must contain lower-case ASCII only")
    if value.endswith(".") or "*" in value:
        raise RegistryValidationError("dns_suffix must not contain a wildcard or trailing dot")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise RegistryValidationError("dns_suffix must not be an IP literal")
    labels = value.split(".")
    if len(labels) < 2:
        raise RegistryValidationError("dns_suffix must contain at least two labels")
    if len(value) > 253 or any(_DNS_LABEL_RE.fullmatch(label) is None for label in labels):
        raise RegistryValidationError(f"invalid DNS suffix: {value!r}")
    return value


def parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise RegistryValidationError(f"{field} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise RegistryValidationError(f"{field} is not a valid UTC timestamp: {value!r}") from exc
    return parsed.replace(tzinfo=UTC)


def format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise RegistryValidationError("clock must return an aware UTC datetime")
    return value.replace(microsecond=0).strftime(TIMESTAMP_FORMAT)


def _format_pydantic_error(exc: ValidationError) -> str:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first["loc"]) or "registry"
    return f"invalid registry field {location}: {first['msg']}"


def registry_from_bytes(data: bytes, *, require_canonical: bool = False) -> Registry:
    """Strictly decode and fully validate one registry document."""

    raw = strict_json_loads(data)
    try:
        registry = Registry.model_validate(raw)
    except ValidationError as exc:
        raise RegistryValidationError(_format_pydantic_error(exc)) from exc
    validate_snapshot(registry)
    if require_canonical and canonical_bytes(registry) != data:
        raise NonCanonicalRegistryError(
            "registry is semantically valid but not canonical; run 'hostmark registry format'"
        )
    return registry


def validate_snapshot(registry: Registry) -> None:
    """Validate all invariants that can be established from a current snapshot."""

    if registry.schema_version != SCHEMA_VERSION:
        raise RegistryValidationError(f"unsupported schema_version {registry.schema_version!r}; expected 1")
    validate_dns_suffix(registry.dns_suffix)

    site_set: set[str] = set()
    for site in registry.sites:
        validate_site_code(site)
        if site in site_set:
            raise RegistryValidationError(f"duplicate site code: {site}")
        site_set.add(site)

    hosts_by_id: dict[str, HostRecord] = {}
    hostname_owners: dict[str, str] = {}
    for host in registry.hosts:
        validate_host_id(host.host_id)
        if host.host_id in hosts_by_id:
            raise RegistryValidationError(f"duplicate host_id: {host.host_id}")
        hosts_by_id[host.host_id] = host

        site = hostname_site(host.hostname)
        if site not in site_set:
            raise RegistryValidationError(f"hostname {host.hostname!r} uses site {site!r}, which is absent from sites")
        if len(f"{host.hostname}.{registry.dns_suffix}") > 253:
            raise RegistryValidationError(f"FQDN for hostname {host.hostname!r} exceeds 253 ASCII characters")
        _claim_hostname(hostname_owners, host.hostname, host.host_id)

        seen_previous: set[str] = set()
        for previous in host.previous_hostnames:
            previous_site = hostname_site(previous)
            if previous_site not in site_set:
                raise RegistryValidationError(
                    f"previous hostname {previous!r} uses site {previous_site!r}, which is absent from sites"
                )
            if previous in seen_previous:
                raise RegistryValidationError(f"duplicate previous hostname {previous!r} for {host.host_id}")
            if previous == host.hostname:
                raise RegistryValidationError(f"current hostname {host.hostname!r} also appears in previous_hostnames")
            seen_previous.add(previous)
            _claim_hostname(hostname_owners, previous, host.host_id)

        registered_at = parse_timestamp(host.registered_at, field=f"hosts[{host.host_id}].registered_at")
        if host.notes is not None:
            if not isinstance(host.notes, str) or not host.notes.strip():
                raise RegistryValidationError(f"notes for {host.host_id} must be null or a non-empty string")
            _validate_utf8_text(host.notes, field=f"notes for {host.host_id}")

        if host.status == "active":
            if host.retirement is not None:
                raise RegistryValidationError(f"active host {host.host_id} must have retirement = null")
        elif host.status == "retired":
            if host.retirement is None:
                raise RegistryValidationError(f"retired host {host.host_id} must contain retirement metadata")
            _validate_retirement(host, registered_at)

    for host in registry.hosts:
        retirement = host.retirement
        if retirement is None or retirement.replacement_host_id is None:
            continue
        replacement = retirement.replacement_host_id
        validate_host_id(replacement, field=f"hosts[{host.host_id}].retirement.replacement_host_id")
        if replacement == host.host_id:
            raise RegistryValidationError(f"host {host.host_id} cannot replace itself")
        if replacement not in hosts_by_id:
            raise RegistryValidationError(f"replacement_host_id {replacement} for {host.host_id} does not exist")

    _validate_replacement_cycles(hosts_by_id)


def _claim_hostname(owners: dict[str, str], hostname: str, host_id: str) -> None:
    previous_owner = owners.get(hostname)
    if previous_owner is not None:
        raise RegistryValidationError(
            f"hostname {hostname!r} appears more than once (owners {previous_owner} and {host_id})"
        )
    owners[hostname] = host_id


def _validate_retirement(host: HostRecord, registered_at: datetime) -> None:
    retirement = host.retirement
    assert retirement is not None
    retired_at = parse_timestamp(retirement.retired_at, field=f"hosts[{host.host_id}].retirement.retired_at")
    if retired_at < registered_at:
        raise RegistryValidationError(f"retired_at for {host.host_id} is earlier than registered_at")
    if not isinstance(retirement.reason, str) or not retirement.reason.strip():
        raise RegistryValidationError(f"retirement reason for {host.host_id} must be non-empty")
    _validate_utf8_text(retirement.reason, field=f"retirement reason for {host.host_id}")


def _validate_utf8_text(value: str, *, field: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RegistryValidationError(f"{field} must be UTF-8 encodable") from exc


def _validate_replacement_cycles(hosts_by_id: dict[str, HostRecord]) -> None:
    for start in hosts_by_id:
        seen: set[str] = set()
        current = start
        while current not in seen:
            seen.add(current)
            host = hosts_by_id[current]
            if host.retirement is None or host.retirement.replacement_host_id is None:
                break
            current = host.retirement.replacement_host_id
        else:
            raise RegistryValidationError(f"replacement_host_id graph contains a cycle involving {current}")


def _retirement_mapping(retirement: Retirement | None) -> dict[str, object] | None:
    if retirement is None:
        return None
    return {
        "retired_at": retirement.retired_at,
        "reason": retirement.reason,
        "replacement_host_id": retirement.replacement_host_id,
    }


def canonical_mapping(registry: Registry) -> dict[str, object]:
    """Return the fixed-order, canonically sorted JSON-compatible mapping."""

    hosts = sorted(registry.hosts, key=lambda host: (host.hostname, host.host_id))
    return {
        "schema_version": registry.schema_version,
        "dns_suffix": registry.dns_suffix,
        "sites": sorted(registry.sites),
        "hosts": [
            {
                "host_id": host.host_id,
                "hostname": host.hostname,
                "status": host.status,
                "registered_at": host.registered_at,
                "previous_hostnames": list(host.previous_hostnames),
                "retirement": _retirement_mapping(host.retirement),
                "notes": host.notes,
            }
            for host in hosts
        ],
    }


def canonical_bytes(registry: Registry) -> bytes:
    """Serialize canonical registry bytes independent of the host platform."""

    validate_snapshot(registry)
    text = json.dumps(canonical_mapping(registry), ensure_ascii=False, indent=2)
    try:
        return (text + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RegistryValidationError("registry text must be UTF-8 encodable") from exc


def validate_against_baseline(candidate: Registry, baseline: Registry) -> BaselineSummary:
    """Enforce append-only identity, name ownership, and lifecycle history."""

    validate_snapshot(baseline)
    validate_snapshot(candidate)
    if candidate.schema_version != baseline.schema_version:
        raise RegistryValidationError("schema_version cannot change without an explicit migration")

    removed_sites = sorted(set(baseline.sites) - set(candidate.sites))
    if removed_sites:
        raise RegistryValidationError(f"site codes cannot be removed: {', '.join(removed_sites)}")

    candidate_by_id = {host.host_id: host for host in candidate.hosts}
    baseline_by_id = {host.host_id: host for host in baseline.hosts}
    deleted_ids = sorted(set(baseline_by_id) - set(candidate_by_id))
    if deleted_ids:
        raise RegistryValidationError(f"existing host IDs cannot be deleted: {', '.join(deleted_ids)}")

    additions = tuple(sorted(host.hostname for key, host in candidate_by_id.items() if key not in baseline_by_id))
    renames: list[str] = []
    retirements: list[str] = []
    notes_changes: list[str] = []
    reason_corrections: list[str] = []
    replacement_assignments: list[str] = []

    for host_id, old in baseline_by_id.items():
        new = candidate_by_id[host_id]
        if new.registered_at != old.registered_at:
            raise RegistryValidationError(f"registered_at is immutable for {host_id}")
        if new.notes != old.notes:
            notes_changes.append(new.hostname)
        if old.status == "active":
            _validate_existing_active(old, new, candidate_by_id)
            if new.hostname != old.hostname:
                renames.append(f"{old.hostname} -> {new.hostname}")
            if new.status == "retired":
                retirements.append(new.hostname)
        else:
            reason_changed, replacement_assigned = _validate_existing_retired(old, new, candidate_by_id)
            if reason_changed:
                reason_corrections.append(new.hostname)
            if replacement_assigned:
                replacement_assignments.append(new.hostname)

    dns_warning = None
    if candidate.dns_suffix != baseline.dns_suffix:
        dns_warning = (
            f"dns_suffix changed from {baseline.dns_suffix!r} to {candidate.dns_suffix!r}; every computed FQDN changes"
        )
    return BaselineSummary(
        additions=additions,
        renames=tuple(sorted(renames)),
        retirements=tuple(sorted(retirements)),
        notes_changes=tuple(sorted(notes_changes)),
        reason_corrections=tuple(sorted(reason_corrections)),
        replacement_assignments=tuple(sorted(replacement_assignments)),
        site_additions=tuple(sorted(set(candidate.sites) - set(baseline.sites))),
        dns_suffix_warning=dns_warning,
    )


def _validate_history_transition(old: HostRecord, new: HostRecord) -> None:
    old_history = old.previous_hostnames
    new_history = new.previous_hostnames
    if new_history[: len(old_history)] != old_history:
        raise RegistryValidationError(f"previous_hostnames for {old.host_id} must retain its exact existing prefix")
    if new.hostname == old.hostname:
        if new_history != old_history:
            raise RegistryValidationError(
                f"previous_hostnames cannot change without renaming active host {old.hostname}"
            )
        return
    appended = new_history[len(old_history) :]
    if not appended or appended[0] != old.hostname:
        raise RegistryValidationError(
            f"rename of {old.hostname} must append the baseline current hostname first in previous_hostnames"
        )


def _require_active_replacement(host: HostRecord, hosts_by_id: dict[str, HostRecord]) -> None:
    retirement = host.retirement
    if retirement is None or retirement.replacement_host_id is None:
        return
    target = hosts_by_id[retirement.replacement_host_id]
    if target.status != "active":
        raise RegistryValidationError(
            f"new replacement target {target.hostname} for {host.hostname} must be active in the candidate"
        )


def _validate_existing_active(
    old: HostRecord,
    new: HostRecord,
    candidate_by_id: dict[str, HostRecord],
) -> None:
    _validate_history_transition(old, new)
    if new.status == "retired":
        _require_active_replacement(new, candidate_by_id)


def _validate_existing_retired(
    old: HostRecord,
    new: HostRecord,
    candidate_by_id: dict[str, HostRecord],
) -> tuple[bool, bool]:
    if new.status != "retired":
        raise RegistryValidationError(f"retired host {old.hostname} cannot become active")
    if new.hostname != old.hostname:
        raise RegistryValidationError(f"retired hostname is immutable for {old.host_id}")
    if new.previous_hostnames != old.previous_hostnames:
        raise RegistryValidationError(f"previous_hostnames are immutable for retired host {old.hostname}")
    assert old.retirement is not None and new.retirement is not None
    if new.retirement.retired_at != old.retirement.retired_at:
        raise RegistryValidationError(f"retired_at is immutable for {old.hostname}")
    old_replacement = old.retirement.replacement_host_id
    new_replacement = new.retirement.replacement_host_id
    if old_replacement is not None and new_replacement != old_replacement:
        raise RegistryValidationError(f"non-null replacement_host_id cannot be cleared or changed for {old.hostname}")
    replacement_assigned = old_replacement is None and new_replacement is not None
    if replacement_assigned:
        _require_active_replacement(new, candidate_by_id)
    return new.retirement.reason != old.retirement.reason, replacement_assigned


__all__ = [
    "SCHEMA_VERSION",
    "BaselineSummary",
    "canonical_bytes",
    "canonical_mapping",
    "format_timestamp",
    "hostname_site",
    "parse_timestamp",
    "registry_from_bytes",
    "strict_json_loads",
    "validate_against_baseline",
    "validate_dns_suffix",
    "validate_host_id",
    "validate_site_code",
    "validate_snapshot",
]
