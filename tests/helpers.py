"""Synthetic registry builders shared by deterministic tests."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from hostmark.domain.models import HostRecord, Registry, Retirement
from hostmark.services.registry_validation import canonical_bytes

HOST_A = "f0c5ebce-b37e-45d5-9f62-5c5a12f25116"
HOST_B = "2c179ac7-7252-46be-8dc4-0db8d83e5de1"
HOST_C = "91a3c228-f85f-4f15-a428-1a81386cf021"


def active_host(
    host_id: str = HOST_A,
    hostname: str = "nc1-fox-01",
    *,
    registered_at: str = "2026-08-01T09:30:00Z",
    previous: list[str] | None = None,
    notes: str | None = None,
) -> HostRecord:
    return HostRecord(
        host_id=host_id,
        hostname=hostname,
        status="active",
        registered_at=registered_at,
        previous_hostnames=[] if previous is None else previous,
        retirement=None,
        notes=notes,
    )


def retired_host(
    host_id: str = HOST_A,
    hostname: str = "nc1-fox-01",
    *,
    registered_at: str = "2026-08-01T09:30:00Z",
    previous: list[str] | None = None,
    retired_at: str = "2026-08-29T10:00:00Z",
    reason: str = "Synthetic rebuild",
    replacement_host_id: str | None = None,
    notes: str | None = None,
) -> HostRecord:
    return HostRecord(
        host_id=host_id,
        hostname=hostname,
        status="retired",
        registered_at=registered_at,
        previous_hostnames=[] if previous is None else previous,
        retirement=Retirement(
            retired_at=retired_at,
            reason=reason,
            replacement_host_id=replacement_host_id,
        ),
        notes=notes,
    )


def registry(
    *hosts: HostRecord,
    sites: list[str] | None = None,
    dns_suffix: str = "node.infra.example.com",
) -> Registry:
    return Registry(
        schema_version=1,
        dns_suffix=dns_suffix,
        sites=["nc1"] if sites is None else sites,
        hosts=list(hosts),
    )


def canonical(registry_value: Registry) -> bytes:
    return canonical_bytes(registry_value)


def mapping(registry_value: Registry) -> dict[str, Any]:
    return deepcopy(registry_value.model_dump(mode="json"))


def json_bytes(value: dict[str, Any], *, indent: int | None = 2, final_newline: bool = True) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return (text + ("\n" if final_newline else "")).encode("utf-8")


__all__ = [
    "HOST_A",
    "HOST_B",
    "HOST_C",
    "active_host",
    "canonical",
    "json_bytes",
    "mapping",
    "registry",
    "retired_host",
]
