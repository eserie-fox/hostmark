from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hostmark.domain.errors import RegistryEntryNotFoundError, RegistryValidationError, RetiredHostError
from hostmark.services.registry_store import register_host, rename_host, resolve_host, retire_host
from tests.helpers import HOST_A, HOST_B, HOST_C, active_host, registry, retired_host

NOW = datetime(2026, 8, 29, 12, 34, 56, 987654, tzinfo=UTC)


def fixed_clock() -> datetime:
    return NOW


def test_register_with_explicit_uuid_sets_complete_active_record() -> None:
    candidate = register_host(
        registry(),
        host_id=HOST_A,
        hostname="nc1-orange",
        notes=None,
        clock=fixed_clock,
    )

    host = candidate.hosts[0]
    assert host.host_id == HOST_A
    assert host.hostname == "nc1-orange"
    assert host.status == "active"
    assert host.registered_at == "2026-08-29T12:34:56Z"
    assert host.previous_hostnames == []
    assert host.retirement is None
    assert host.notes is None


def test_register_rejects_duplicate_id_current_name_and_historical_name() -> None:
    baseline = registry(active_host(previous=["nc1-older-01"]))

    with pytest.raises(RegistryValidationError, match="already registered"):
        register_host(baseline, host_id=HOST_A, hostname="nc1-fox-02", notes=None)
    with pytest.raises(RegistryValidationError, match="permanently reserved"):
        register_host(baseline, host_id=HOST_B, hostname="nc1-fox-01", notes=None)
    with pytest.raises(RegistryValidationError, match="permanently reserved"):
        register_host(baseline, host_id=HOST_B, hostname="nc1-older-01", notes=None)


def test_register_rejects_missing_site_and_empty_notes() -> None:
    with pytest.raises(RegistryValidationError, match="absent"):
        register_host(registry(), host_id=HOST_A, hostname="hk1-proxy-01", notes=None)
    with pytest.raises(RegistryValidationError, match="notes"):
        register_host(registry(), host_id=HOST_A, hostname="nc1-orange", notes=" ")


def test_rename_appends_history_and_preserves_identity_metadata() -> None:
    old = active_host(previous=["nc1-fox-old"], notes="keep")
    candidate = rename_host(registry(old), selector=HOST_A, new_hostname="nc1-fox-02")
    renamed = candidate.hosts[0]

    assert renamed.hostname == "nc1-fox-02"
    assert renamed.previous_hostnames == ["nc1-fox-old", "nc1-fox-01"]
    assert renamed.host_id == old.host_id
    assert renamed.registered_at == old.registered_at
    assert renamed.status == old.status
    assert renamed.retirement == old.retirement
    assert renamed.notes == old.notes


def test_multiple_sequential_renames_preserve_chronology() -> None:
    first = rename_host(registry(active_host()), selector="nc1-fox-01", new_hostname="nc1-fox-02")
    second = rename_host(first, selector=HOST_A, new_hostname="nc1-fox-03")

    assert second.hosts[0].previous_hostnames == ["nc1-fox-01", "nc1-fox-02"]


def test_rename_rejects_same_reserved_or_retired_name() -> None:
    baseline = registry(active_host(), active_host(HOST_B, "nc1-fox-02", previous=["nc1-old-02"]))
    with pytest.raises(RegistryValidationError, match="must differ"):
        rename_host(baseline, selector=HOST_A, new_hostname="nc1-fox-01")
    with pytest.raises(RegistryValidationError, match="permanently reserved"):
        rename_host(baseline, selector=HOST_A, new_hostname="nc1-old-02")
    with pytest.raises(RetiredHostError, match="cannot be renamed"):
        rename_host(registry(retired_host()), selector=HOST_A, new_hostname="nc1-fox-02")


def test_mutation_selector_never_resolves_previous_hostname() -> None:
    baseline = registry(active_host(previous=["nc1-old-01"]))

    with pytest.raises(RegistryEntryNotFoundError):
        resolve_host(baseline, "nc1-old-01")


def test_retire_without_replacement_retains_tombstone() -> None:
    candidate = retire_host(
        registry(active_host(notes="retain")),
        selector="nc1-fox-01",
        reason="Decommissioned permanently",
        clock=fixed_clock,
    )
    host = candidate.hosts[0]

    assert len(candidate.hosts) == 1
    assert host.status == "retired"
    assert host.hostname == "nc1-fox-01"
    assert host.notes == "retain"
    assert host.retirement is not None
    assert host.retirement.retired_at == "2026-08-29T12:34:56Z"
    assert host.retirement.reason == "Decommissioned permanently"
    assert host.retirement.replacement_host_id is None


def test_retire_with_active_replacement_uses_target_uuid() -> None:
    candidate = retire_host(
        registry(active_host(), active_host(HOST_B, "nc1-fox-02")),
        selector=HOST_A,
        reason="Rebuilt",
        replacement_selector="nc1-fox-02",
        clock=fixed_clock,
    )

    assert candidate.hosts[0].retirement is not None
    assert candidate.hosts[0].retirement.replacement_host_id == HOST_B
    assert candidate.hosts[1].status == "active"


def test_retire_rejects_invalid_replacement_empty_reason_and_double_retirement() -> None:
    baseline = registry(active_host(), retired_host(HOST_B, "nc1-fox-02"))
    with pytest.raises(RegistryEntryNotFoundError):
        retire_host(baseline, selector=HOST_A, reason="x", replacement_selector=HOST_C)
    with pytest.raises(RetiredHostError, match="must be active"):
        retire_host(baseline, selector=HOST_A, reason="x", replacement_selector=HOST_B)
    with pytest.raises(RegistryValidationError, match="own replacement"):
        retire_host(baseline, selector=HOST_A, reason="x", replacement_selector=HOST_A)
    with pytest.raises(RegistryValidationError, match="reason"):
        retire_host(baseline, selector=HOST_A, reason=" ")
    with pytest.raises(RetiredHostError, match="already retired"):
        retire_host(baseline, selector=HOST_B, reason="Again")


def test_retirement_cannot_precede_registration() -> None:
    future_host = active_host(registered_at="2026-08-30T00:00:00Z")

    with pytest.raises(RegistryValidationError, match="earlier"):
        retire_host(registry(future_host), selector=HOST_A, reason="Clock issue", clock=fixed_clock)
