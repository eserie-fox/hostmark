from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Retirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    retired_at: str
    reason: str
    replacement_host_id: str | None


class HostRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    host_id: str
    hostname: str
    status: Literal["active", "retired"]
    registered_at: str
    previous_hostnames: list[str]
    retirement: Retirement | None
    notes: str | None


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    dns_suffix: str
    sites: list[str]
    hosts: list[HostRecord]


__all__ = ["HostRecord", "Registry", "Retirement"]
