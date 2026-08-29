from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass

from hostmark.domain.errors import (
    HostnameMismatchError,
    PlatformOperationError,
    RegistryEntryNotFoundError,
    RetiredHostError,
)
from hostmark.domain.models import HostRecord, Registry
from hostmark.services.identity_store import LocalIdentity
from hostmark.services.registry_store import fqdn


@dataclass(frozen=True)
class ActualHostname:
    raw: str
    short: str


@dataclass(frozen=True)
class CheckResult:
    identity: LocalIdentity
    host: HostRecord
    actual: ActualHostname
    fqdn: str


def normalize_actual_hostname(raw: str) -> ActualHostname:
    if not isinstance(raw, str):
        raise PlatformOperationError("operating-system hostname reader returned a non-string value")
    trimmed = raw.strip()
    if trimmed.endswith("."):
        trimmed = trimmed[:-1]
    short = trimmed.split(".", 1)[0].lower()
    if not short:
        raise PlatformOperationError(f"operating-system hostname is empty or unusable: {raw!r}")
    return ActualHostname(raw=raw, short=short)


def read_actual_hostname(reader: Callable[[], str] = socket.gethostname) -> ActualHostname:
    try:
        raw = reader()
    except OSError as exc:
        raise PlatformOperationError(f"could not read the operating-system hostname: {exc}") from exc
    return normalize_actual_hostname(raw)


def check_host_state(
    registry: Registry,
    identity: LocalIdentity,
    *,
    hostname_reader: Callable[[], str] = socket.gethostname,
) -> CheckResult:
    """Check current state without modifying the OS, registry, DNS, or Git."""

    host = next((item for item in registry.hosts if item.host_id == identity.host_id), None)
    if host is None:
        raise RegistryEntryNotFoundError(f"local host ID is not registered: {identity.host_id}")
    if host.status == "retired":
        raise RetiredHostError(f"local host ID is retired: {identity.host_id} ({host.hostname})")
    actual = read_actual_hostname(hostname_reader)
    expected_fqdn = fqdn(registry, host)
    if actual.short != host.hostname.lower():
        previous_detail = ""
        if actual.short in host.previous_hostnames:
            previous_detail = f"; actual name matches this identity's previous hostname {actual.short!r}"
        raise HostnameMismatchError(
            f"hostname drift: expected {host.hostname!r}, actual raw value {actual.raw!r} "
            f"(short {actual.short!r}); expected FQDN {expected_fqdn}{previous_detail}"
        )
    return CheckResult(identity=identity, host=host, actual=actual, fqdn=expected_fqdn)


__all__ = [
    "ActualHostname",
    "CheckResult",
    "check_host_state",
    "normalize_actual_hostname",
    "read_actual_hostname",
]
