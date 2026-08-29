"""OS hostname normalization and local drift behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hostmark.domain.errors import HostnameMismatchError, RegistryEntryNotFoundError, RetiredHostError
from hostmark.services.host_state import check_host_state, normalize_actual_hostname
from hostmark.services.identity_store import LocalIdentity
from tests.helpers import HOST_A, HOST_B, active_host, registry, retired_host

IDENTITY = LocalIdentity(host_id=HOST_A, scope="user", path=Path("/tmp/host-id"))


@pytest.mark.parametrize(
    ("raw", "short"),
    [
        ("nc1-fox-01", "nc1-fox-01"),
        ("NC1-FOX-01", "nc1-fox-01"),
        ("nc1-fox-01.node.infra.example.com", "nc1-fox-01"),
        (" nc1-fox-01.node.example.com. \n", "nc1-fox-01"),
    ],
)
def test_normalizes_exact_case_fqdn_and_trailing_dot(raw: str, short: str) -> None:
    assert normalize_actual_hostname(raw).short == short


def test_check_exact_and_case_only_match_with_expected_fqdn() -> None:
    document = registry(active_host())

    exact = check_host_state(document, IDENTITY, hostname_reader=lambda: "nc1-fox-01")
    uppercase = check_host_state(document, IDENTITY, hostname_reader=lambda: "NC1-FOX-01")

    assert exact.fqdn == "nc1-fox-01.node.infra.example.com"
    assert uppercase.actual.short == "nc1-fox-01"


def test_mismatch_and_previous_hostname_diagnostics() -> None:
    document = registry(active_host(previous=["nc1-old-01"]))

    with pytest.raises(HostnameMismatchError, match="expected FQDN"):
        check_host_state(document, IDENTITY, hostname_reader=lambda: "other")
    with pytest.raises(HostnameMismatchError, match="previous hostname 'nc1-old-01'"):
        check_host_state(document, IDENTITY, hostname_reader=lambda: "nc1-old-01.example.com")


def test_unknown_local_uuid_and_retired_local_uuid_have_stable_error_types() -> None:
    with pytest.raises(RegistryEntryNotFoundError) as unknown:
        check_host_state(registry(), IDENTITY, hostname_reader=lambda: "nc1-fox-01")
    assert unknown.value.exit_code == 5

    retired_identity = LocalIdentity(host_id=HOST_B, scope="system", path=Path("/tmp/system-id"))
    with pytest.raises(RetiredHostError) as retired:
        check_host_state(
            registry(retired_host(HOST_B, "nc1-fox-02")),
            retired_identity,
            hostname_reader=lambda: "nc1-fox-02",
        )
    assert retired.value.exit_code == 7


def test_mismatch_has_stable_exit_code() -> None:
    with pytest.raises(HostnameMismatchError) as mismatch:
        check_host_state(registry(active_host()), IDENTITY, hostname_reader=lambda: "nc1-other-01")

    assert mismatch.value.exit_code == 6
