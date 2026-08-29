from __future__ import annotations

import pytest

from hostmark.domain.errors import RegistryValidationError
from hostmark.domain.models import HostRecord, Registry, Retirement
from hostmark.services.registry_validation import validate_against_baseline
from tests.helpers import HOST_B, HOST_C, active_host, registry, retired_host


def with_hosts(base: Registry, *hosts: HostRecord) -> Registry:
    return base.model_copy(update={"hosts": list(hosts)})


def test_allows_additions_notes_changes_and_historical_tombstone_import() -> None:
    baseline = registry(active_host())
    candidate = registry(
        active_host(notes="updated"),
        active_host(HOST_B, "nc1-fox-02"),
        retired_host(HOST_C, "nc1-old-03"),
    )

    summary = validate_against_baseline(candidate, baseline)

    assert summary.additions == ("nc1-fox-02", "nc1-old-03")
    assert summary.notes_changes == ("nc1-fox-01",)


def test_rejects_host_deletion_and_hidden_identity_replacement() -> None:
    baseline = registry(active_host())
    with pytest.raises(RegistryValidationError, match="cannot be deleted"):
        validate_against_baseline(registry(), baseline)
    with pytest.raises(RegistryValidationError, match="cannot be deleted"):
        validate_against_baseline(registry(active_host(HOST_B, "nc1-fox-01")), baseline)


def test_rejects_registered_at_rewrite_and_retired_resurrection() -> None:
    baseline = registry(active_host())
    changed = registry(active_host(registered_at="2026-08-02T00:00:00Z"))
    with pytest.raises(RegistryValidationError, match="registered_at"):
        validate_against_baseline(changed, baseline)

    retired = registry(retired_host())
    with pytest.raises(RegistryValidationError, match="cannot become active"):
        validate_against_baseline(registry(active_host()), retired)


def test_rejects_history_deletion_reordering_or_append_without_rename() -> None:
    baseline = registry(active_host(previous=["nc1-old-01", "nc1-old-02"]))
    deleted = registry(active_host(previous=["nc1-old-01"]))
    reordered = registry(active_host(previous=["nc1-old-02", "nc1-old-01"]))
    appended = registry(active_host(previous=["nc1-old-01", "nc1-old-02", "nc1-extra-01"]))

    for candidate in (deleted, reordered):
        with pytest.raises(RegistryValidationError, match="exact existing prefix"):
            validate_against_baseline(candidate, baseline)
    with pytest.raises(RegistryValidationError, match="cannot change without renaming"):
        validate_against_baseline(appended, baseline)


def test_allows_correct_rename_and_multi_rename_extension() -> None:
    baseline = registry(active_host(previous=["nc1-old-01"]))
    renamed = registry(active_host(hostname="nc1-fox-02", previous=["nc1-old-01", "nc1-fox-01"]))
    multi = registry(
        active_host(
            hostname="nc1-fox-04",
            previous=["nc1-old-01", "nc1-fox-01", "nc1-fox-02", "nc1-fox-03"],
        )
    )

    assert validate_against_baseline(renamed, baseline).renames == ("nc1-fox-01 -> nc1-fox-02",)
    assert validate_against_baseline(multi, baseline).renames == ("nc1-fox-01 -> nc1-fox-04",)


def test_rejects_rename_without_baseline_name_first() -> None:
    baseline = registry(active_host(previous=["nc1-old-01"]))
    candidate = registry(active_host(hostname="nc1-fox-03", previous=["nc1-old-01", "nc1-fox-02", "nc1-fox-01"]))

    with pytest.raises(RegistryValidationError, match="baseline current hostname first"):
        validate_against_baseline(candidate, baseline)


def test_rejects_name_ownership_transfer() -> None:
    baseline = registry(active_host())
    candidate = registry(
        active_host(hostname="nc1-fox-02", previous=["nc1-fox-01"]),
        active_host(HOST_B, "nc1-fox-01"),
    )

    with pytest.raises(RegistryValidationError, match="appears more than once"):
        validate_against_baseline(candidate, baseline)


def test_allows_rename_and_retirement_in_same_candidate() -> None:
    baseline = registry(active_host(), active_host(HOST_B, "nc1-live-02"))
    candidate = registry(
        retired_host(
            hostname="nc1-fox-02",
            previous=["nc1-fox-01"],
            replacement_host_id=HOST_B,
        ),
        active_host(HOST_B, "nc1-live-02"),
    )

    summary = validate_against_baseline(candidate, baseline)

    assert summary.renames == ("nc1-fox-01 -> nc1-fox-02",)
    assert summary.retirements == ("nc1-fox-02",)


def test_new_retirement_replacement_must_be_active() -> None:
    baseline = registry(active_host(), active_host(HOST_B, "nc1-fox-02"))
    candidate = registry(
        retired_host(replacement_host_id=HOST_B),
        retired_host(HOST_B, "nc1-fox-02"),
    )

    with pytest.raises(RegistryValidationError, match="must be active"):
        validate_against_baseline(candidate, baseline)


def test_retired_host_allows_only_notes_reason_and_one_replacement_assignment() -> None:
    baseline = registry(retired_host(), active_host(HOST_B, "nc1-fox-02"))
    old = baseline.hosts[0]
    assert old.retirement is not None
    changed = old.model_copy(
        update={
            "notes": "corrected",
            "retirement": old.retirement.model_copy(
                update={"reason": "Corrected reason", "replacement_host_id": HOST_B}
            ),
        }
    )
    candidate = with_hosts(baseline, changed, baseline.hosts[1])

    summary = validate_against_baseline(candidate, baseline)

    assert summary.notes_changes == ("nc1-fox-01",)
    assert summary.reason_corrections == ("nc1-fox-01",)
    assert summary.replacement_assignments == ("nc1-fox-01",)


def test_new_replacement_on_retired_host_requires_active_target() -> None:
    baseline = registry(retired_host(), retired_host(HOST_B, "nc1-fox-02"))
    old = baseline.hosts[0]
    assert old.retirement is not None
    changed = old.model_copy(update={"retirement": old.retirement.model_copy(update={"replacement_host_id": HOST_B})})

    with pytest.raises(RegistryValidationError, match="must be active"):
        validate_against_baseline(with_hosts(baseline, changed, baseline.hosts[1]), baseline)


@pytest.mark.parametrize("new_value", [None, HOST_C])
def test_rejects_clearing_or_changing_non_null_replacement(new_value: str | None) -> None:
    baseline = registry(retired_host(replacement_host_id=HOST_B), active_host(HOST_B, "nc1-fox-02"))
    old = baseline.hosts[0]
    assert old.retirement is not None
    changed = old.model_copy(
        update={"retirement": old.retirement.model_copy(update={"replacement_host_id": new_value})}
    )
    extra = [] if new_value != HOST_C else [active_host(HOST_C, "nc1-fox-03")]

    with pytest.raises(RegistryValidationError, match="cannot be cleared or changed"):
        validate_against_baseline(with_hosts(baseline, changed, baseline.hosts[1], *extra), baseline)


def test_rejects_retired_hostname_history_and_retired_at_mutations() -> None:
    baseline = registry(retired_host(previous=["nc1-old-01"]))
    old = baseline.hosts[0]
    assert old.retirement is not None
    candidates = [
        retired_host(hostname="nc1-fox-02", previous=["nc1-old-01"]),
        retired_host(previous=["nc1-old-01", "nc1-other-01"]),
        old.model_copy(
            update={
                "retirement": Retirement(
                    retired_at="2026-08-30T00:00:00Z",
                    reason=old.retirement.reason,
                    replacement_host_id=None,
                )
            }
        ),
    ]

    for changed in candidates:
        with pytest.raises(RegistryValidationError, match="immutable"):
            validate_against_baseline(registry(changed), baseline)


def test_site_addition_is_allowed_and_removal_is_rejected() -> None:
    baseline = registry(sites=["nc1"])
    summary = validate_against_baseline(registry(sites=["hk1", "nc1"]), baseline)
    assert summary.site_additions == ("hk1",)

    with pytest.raises(RegistryValidationError, match="cannot be removed"):
        validate_against_baseline(registry(sites=["nc1"]), registry(sites=["hk1", "nc1"]))


def test_dns_suffix_change_produces_prominent_warning() -> None:
    summary = validate_against_baseline(
        registry(dns_suffix="node.new-example.com"),
        registry(dns_suffix="node.old-example.com"),
    )

    assert summary.dns_suffix_warning is not None
    assert "every computed FQDN changes" in summary.dns_suffix_warning
