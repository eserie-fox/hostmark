from __future__ import annotations

import difflib
import hashlib
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hostmark.domain.errors import (
    ConcurrentModificationError,
    HostmarkError,
    NonCanonicalRegistryError,
    RegistryEntryNotFoundError,
    RegistryValidationError,
    RetiredHostError,
)
from hostmark.domain.models import HostRecord, Registry, Retirement
from hostmark.services.registry_validation import (
    BaselineSummary,
    canonical_bytes,
    format_timestamp,
    hostname_site,
    registry_from_bytes,
    validate_against_baseline,
    validate_dns_suffix,
    validate_host_id,
    validate_site_code,
    validate_snapshot,
)

Clock = Callable[[], datetime]
RegistryTransition = Callable[[Registry], Registry]
ReplaceFunction = Callable[[Path, Path], None]


@dataclass(frozen=True)
class RegistryDocument:
    """A validated registry plus the exact bytes used for concurrency checks."""

    path: Path
    registry: Registry
    data: bytes
    sha256: str


@dataclass(frozen=True)
class MutationResult:
    original: Registry
    candidate: Registry
    changed: bool
    wrote: bool
    diff: str | None = None


@dataclass(frozen=True)
class FormatResult:
    changed: bool
    wrote: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def resolve_registry_path(
    explicit: Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    for_init: bool = False,
) -> Path:
    """Resolve a registry path using CLI, environment, then upward discovery."""

    environment = os.environ if environ is None else environ
    working_directory = Path.cwd() if cwd is None else cwd
    if explicit is not None:
        return _absolute_path(explicit, working_directory)
    configured = environment.get("HOSTMARK_REGISTRY")
    if configured:
        return _absolute_path(Path(configured), working_directory)

    current = working_directory.expanduser().resolve()
    while True:
        candidate = current / "registry" / "hosts.json"
        if candidate.is_file():
            return candidate.resolve()
        if current.parent == current:
            break
        current = current.parent

    if for_init:
        return (working_directory / "registry" / "hosts.json").expanduser().resolve()
    raise HostmarkError(
        "registry path not found; pass --registry PATH, set HOSTMARK_REGISTRY, or place the file at registry/hosts.json"
    )


def _absolute_path(path: Path, cwd: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = cwd / expanded
    return expanded.resolve(strict=False)


def read_registry(path: Path, *, require_canonical: bool = True) -> RegistryDocument:
    """Read exact bytes and perform strict complete registry validation."""

    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise HostmarkError(f"registry file does not exist: {path}") from exc
    except IsADirectoryError as exc:
        raise HostmarkError(f"registry path is a directory: {path}") from exc
    except PermissionError as exc:
        raise HostmarkError(f"permission denied while reading registry: {path}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not read registry {path}: {exc}") from exc
    registry = registry_from_bytes(data, require_canonical=require_canonical)
    return RegistryDocument(path=path, registry=registry, data=data, sha256=hashlib.sha256(data).hexdigest())


def new_registry(*, dns_suffix: str, sites: Sequence[str]) -> Registry:
    validate_dns_suffix(dns_suffix)
    if not sites:
        raise RegistryValidationError("at least one --site is required")
    for site in sites:
        validate_site_code(site)
    if len(set(sites)) != len(sites):
        raise RegistryValidationError("site codes supplied to registry init must be unique")
    registry = Registry(schema_version=1, dns_suffix=dns_suffix, sites=list(sites), hosts=[])
    validate_snapshot(registry)
    return registry


def initialize_registry(path: Path, registry: Registry) -> None:
    """Create a canonical registry without overwriting any existing path."""

    if path.exists():
        raise HostmarkError(f"refusing to overwrite existing registry: {path}")
    data = canonical_bytes(registry)
    _atomic_write(path, data, expected=None, expected_sha256=None, require_absent=True)
    written = read_registry(path, require_canonical=True)
    if written.data != data:
        raise ConcurrentModificationError(f"registry changed immediately after creation: {path}")


def resolve_host(registry: Registry, selector: str) -> HostRecord:
    """Resolve only a current canonical hostname or canonical UUIDv4."""

    for host in registry.hosts:
        if selector == host.hostname or selector == host.host_id:
            return host
    raise RegistryEntryNotFoundError(f"no registry host matches current hostname or host ID: {selector!r}")


def fqdn(registry: Registry, host: HostRecord) -> str:
    return f"{host.hostname}.{registry.dns_suffix}"


def register_host(
    registry: Registry,
    *,
    host_id: str,
    hostname: str,
    notes: str | None,
    clock: Clock = utc_now,
) -> Registry:
    validate_host_id(host_id)
    site = hostname_site(hostname)
    if site not in registry.sites:
        raise RegistryValidationError(f"hostname site {site!r} is absent from the registry sites list")
    if any(host.host_id == host_id for host in registry.hosts):
        raise RegistryValidationError(f"host_id is already registered: {host_id}")
    _ensure_hostname_available(registry, hostname)
    if notes is not None and not notes.strip():
        raise RegistryValidationError("notes must be omitted or a non-empty string")
    host = HostRecord(
        host_id=host_id,
        hostname=hostname,
        status="active",
        registered_at=format_timestamp(clock()),
        previous_hostnames=[],
        retirement=None,
        notes=notes,
    )
    candidate = registry.model_copy(update={"hosts": [*registry.hosts, host]})
    validate_snapshot(candidate)
    return candidate


def rename_host(registry: Registry, *, selector: str, new_hostname: str) -> Registry:
    old = resolve_host(registry, selector)
    if old.status == "retired":
        raise RetiredHostError(f"retired host {old.hostname} cannot be renamed")
    if new_hostname == old.hostname:
        raise RegistryValidationError(f"new hostname must differ from the current hostname {old.hostname!r}")
    site = hostname_site(new_hostname)
    if site not in registry.sites:
        raise RegistryValidationError(f"hostname site {site!r} is absent from the registry sites list")
    _ensure_hostname_available(registry, new_hostname)
    replacement = old.model_copy(
        update={
            "hostname": new_hostname,
            "previous_hostnames": [*old.previous_hostnames, old.hostname],
        }
    )
    candidate = _replace_host(registry, replacement)
    validate_snapshot(candidate)
    return candidate


def retire_host(
    registry: Registry,
    *,
    selector: str,
    reason: str,
    replacement_selector: str | None = None,
    clock: Clock = utc_now,
) -> Registry:
    target = resolve_host(registry, selector)
    if target.status == "retired":
        raise RetiredHostError(f"host {target.hostname} is already retired")
    if not reason.strip():
        raise RegistryValidationError("retirement reason must be non-empty")
    replacement_id: str | None = None
    if replacement_selector is not None:
        replacement = resolve_host(registry, replacement_selector)
        if replacement.host_id == target.host_id:
            raise RegistryValidationError("a host cannot be its own replacement")
        if replacement.status != "active":
            raise RetiredHostError(f"replacement host {replacement.hostname} must be active")
        replacement_id = replacement.host_id
    retired = target.model_copy(
        update={
            "status": "retired",
            "retirement": Retirement(
                retired_at=format_timestamp(clock()),
                reason=reason,
                replacement_host_id=replacement_id,
            ),
        }
    )
    candidate = _replace_host(registry, retired)
    validate_snapshot(candidate)
    return candidate


def _replace_host(registry: Registry, replacement: HostRecord) -> Registry:
    hosts = [replacement if host.host_id == replacement.host_id else host for host in registry.hosts]
    return registry.model_copy(update={"hosts": hosts})


def _ensure_hostname_available(registry: Registry, hostname: str) -> None:
    for host in registry.hosts:
        if hostname == host.hostname or hostname in host.previous_hostnames:
            raise RegistryValidationError(f"hostname is permanently reserved by host {host.host_id}: {hostname}")


def unified_registry_diff(path: Path, before: bytes, after: bytes) -> str:
    """Create a deterministic LF-only unified diff for a dry run."""

    lines = difflib.unified_diff(
        before.decode("utf-8").splitlines(keepends=True),
        after.decode("utf-8").splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
    )
    return "".join(lines).replace("\r\n", "\n")


def mutate_registry(
    path: Path,
    transition: RegistryTransition,
    *,
    dry_run: bool = False,
    before_compare: Callable[[], None] | None = None,
    replace: ReplaceFunction | None = None,
) -> MutationResult:
    """Execute one complete optimistic, validated registry transaction."""

    document = read_registry(path, require_canonical=True)
    candidate = transition(document.registry)
    validate_snapshot(candidate)
    candidate_data = canonical_bytes(candidate)
    if candidate_data == document.data:
        raise HostmarkError("requested registry transition made no change")
    if dry_run:
        return MutationResult(
            original=document.registry,
            candidate=candidate,
            changed=True,
            wrote=False,
            diff=unified_registry_diff(path, document.data, candidate_data),
        )
    if before_compare is not None:
        before_compare()
    _atomic_write(
        path,
        candidate_data,
        expected=document.data,
        expected_sha256=document.sha256,
        require_absent=False,
        replace=replace,
    )
    reread = read_registry(path, require_canonical=True)
    if reread.data != candidate_data:
        raise ConcurrentModificationError(f"registry changed during post-write verification: {path}")
    return MutationResult(
        original=document.registry,
        candidate=candidate,
        changed=True,
        wrote=True,
    )


def format_registry(
    path: Path,
    *,
    check: bool,
    before_compare: Callable[[], None] | None = None,
    replace: ReplaceFunction | None = None,
) -> FormatResult:
    """Check or rewrite representation without repairing semantic data."""

    document = read_registry(path, require_canonical=False)
    formatted = canonical_bytes(document.registry)
    changed = formatted != document.data
    if check:
        if changed:
            raise NonCanonicalRegistryError(f"registry formatting is required: {path}")
        return FormatResult(changed=False, wrote=False)
    if not changed:
        return FormatResult(changed=False, wrote=False)
    if before_compare is not None:
        before_compare()
    _atomic_write(
        path,
        formatted,
        expected=document.data,
        expected_sha256=document.sha256,
        require_absent=False,
        replace=replace,
    )
    reread = read_registry(path, require_canonical=True)
    if reread.data != formatted:
        raise ConcurrentModificationError(f"registry changed during post-format verification: {path}")
    return FormatResult(changed=True, wrote=True)


def validate_registry_files(candidate_path: Path, baseline_path: Path | None = None) -> BaselineSummary | None:
    candidate = read_registry(candidate_path, require_canonical=True).registry
    if baseline_path is None:
        return None
    baseline = read_registry(baseline_path, require_canonical=False).registry
    return validate_against_baseline(candidate, baseline)


def _atomic_write(
    path: Path,
    data: bytes,
    *,
    expected: bytes | None,
    expected_sha256: str | None,
    require_absent: bool,
    replace: ReplaceFunction | None = None,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HostmarkError(f"could not create registry parent directory {path.parent} for {path}: {exc}") from exc
    if require_absent:
        if path.exists():
            raise HostmarkError(f"refusing to overwrite existing registry: {path}")
        existing_mode = None
    else:
        try:
            current = path.read_bytes()
            existing_mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError as exc:
            raise ConcurrentModificationError(f"registry disappeared during mutation: {path}") from exc
        except OSError as exc:
            raise HostmarkError(f"could not re-read registry before writing {path}: {exc}") from exc
        if (
            expected is None
            or expected_sha256 is None
            or hashlib.sha256(current).hexdigest() != expected_sha256
            or current != expected
        ):
            raise ConcurrentModificationError(f"registry changed concurrently; no update was written: {path}")

    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise HostmarkError(f"could not create temporary registry file in {path.parent} for {path}: {exc}") from exc
    temporary = Path(temporary_name)
    try:
        try:
            handle = os.fdopen(descriptor, "wb")
        except OSError as exc:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise HostmarkError(f"could not open temporary registry file {temporary} for {path}: {exc}") from exc
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise HostmarkError(
                f"could not write and sync temporary registry file {temporary} for {path}: {exc}"
            ) from exc
        if existing_mode is not None:
            try:
                os.chmod(temporary, existing_mode)
            except OSError:
                pass
        if require_absent:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise HostmarkError(f"refusing to overwrite registry created concurrently: {path}") from exc
            except PermissionError as exc:
                raise HostmarkError(f"permission denied while atomically creating registry {path}") from exc
            except OSError as exc:
                raise HostmarkError(f"could not atomically create registry {path}: {exc}") from exc
            _fsync_parent(path.parent)
            return
        replace_operation: ReplaceFunction = os.replace if replace is None else replace
        try:
            replace_operation(temporary, path)
        except PermissionError as exc:
            raise HostmarkError(
                f"could not atomically replace registry {path}; check permissions and whether another program "
                "has it open"
            ) from exc
        except OSError as exc:
            raise HostmarkError(f"could not atomically replace registry {path}: {exc}") from exc
        _fsync_parent(path.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _fsync_parent(parent: Path) -> None:
    """Directory fsync is best-effort because it is not portable across platforms/filesystems."""

    if os.name != "posix":
        return
    try:
        descriptor = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def hosts_filtered(
    registry: Registry,
    *,
    status_filter: Literal["active", "retired"] | None = None,
    site_filter: str | None = None,
) -> list[HostRecord]:
    if site_filter is not None:
        validate_site_code(site_filter)
        if site_filter not in registry.sites:
            raise RegistryValidationError(f"site is absent from registry: {site_filter}")
    return sorted(
        (
            host
            for host in registry.hosts
            if (status_filter is None or host.status == status_filter)
            and (site_filter is None or host.hostname.startswith(f"{site_filter}-"))
        ),
        key=lambda host: (host.hostname, host.host_id),
    )


__all__ = [
    "FormatResult",
    "MutationResult",
    "RegistryDocument",
    "format_registry",
    "fqdn",
    "hosts_filtered",
    "initialize_registry",
    "mutate_registry",
    "new_registry",
    "read_registry",
    "register_host",
    "rename_host",
    "resolve_host",
    "resolve_registry_path",
    "retire_host",
    "unified_registry_diff",
    "utc_now",
    "validate_registry_files",
]
