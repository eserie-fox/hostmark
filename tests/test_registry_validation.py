from __future__ import annotations

import json

import pytest

from hostmark.domain.errors import NonCanonicalRegistryError, RegistryValidationError
from hostmark.domain.models import Registry, Retirement
from hostmark.services.registry_validation import registry_from_bytes, validate_snapshot
from tests.helpers import HOST_A, HOST_B, active_host, canonical, json_bytes, mapping, registry, retired_host


def test_valid_empty_registry() -> None:
    document = registry()

    assert registry_from_bytes(canonical(document), require_canonical=True) == document


def test_valid_active_and_retired_records() -> None:
    document = registry(
        retired_host(replacement_host_id=HOST_B),
        active_host(HOST_B, "nc1-fox-02"),
    )

    validate_snapshot(document)


@pytest.mark.parametrize(
    "host_id",
    [
        "F0C5EBCE-B37E-45D5-9F62-5C5A12F25116",
        "f0c5ebce-b37e-15d5-9f62-5c5a12f25116",
        "not-a-uuid",
    ],
)
def test_rejects_noncanonical_wrong_version_and_malformed_host_ids(host_id: str) -> None:
    document = registry(active_host())
    raw = mapping(document)
    raw["hosts"][0]["host_id"] = host_id

    with pytest.raises(RegistryValidationError, match="UUID"):
        registry_from_bytes(json_bytes(raw))


def test_rejects_duplicate_host_ids() -> None:
    document = registry(active_host(), active_host(HOST_A, "nc1-fox-02"))

    with pytest.raises(RegistryValidationError, match="duplicate host_id"):
        validate_snapshot(document)


@pytest.mark.parametrize(
    "payload,key",
    [
        ('{"schema_version":1,"schema_version":1,"dns_suffix":"x.example","sites":[],"hosts":[]}', "schema_version"),
        (
            '{"schema_version":1,"dns_suffix":"x.example","sites":["nc1"],"hosts":['
            '{"host_id":"f0c5ebce-b37e-45d5-9f62-5c5a12f25116",'
            '"hostname":"nc1-fox-01","hostname":"nc1-fox-01","status":"active",'
            '"registered_at":"2026-08-01T09:30:00Z","previous_hostnames":[],"retirement":null,"notes":null}]}',
            "hostname",
        ),
    ],
)
def test_rejects_duplicate_json_keys_at_any_depth(payload: str, key: str) -> None:
    with pytest.raises(RegistryValidationError, match=f"duplicate JSON object key: '{key}'"):
        registry_from_bytes(payload.encode())


def test_rejects_unknown_fields() -> None:
    raw = mapping(registry())
    raw["unexpected"] = True

    with pytest.raises(RegistryValidationError, match="unexpected"):
        registry_from_bytes(json_bytes(raw))


def test_rejects_missing_fields_including_nullable_fields() -> None:
    raw = mapping(registry(active_host()))
    del raw["hosts"][0]["notes"]

    with pytest.raises(RegistryValidationError, match="notes"):
        registry_from_bytes(json_bytes(raw))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-01 09:30:00Z",
        "2026-08-01T09:30:00+00:00",
        "2026-08-01T09:30:00.123Z",
        "2026-13-01T09:30:00Z",
    ],
)
def test_rejects_invalid_registration_timestamps(timestamp: str) -> None:
    document = registry(active_host(registered_at=timestamp))

    with pytest.raises(RegistryValidationError, match="registered_at"):
        validate_snapshot(document)


@pytest.mark.parametrize(
    "suffix",
    [
        "localhost",
        "Node.example.com",
        "*.example.com",
        "192.0.2.1",
        f"{'a' * 64}.example.com",
    ],
)
def test_rejects_invalid_dns_suffixes(suffix: str) -> None:
    document = registry(dns_suffix=suffix)

    with pytest.raises(RegistryValidationError, match=r"dns_suffix|DNS suffix|IP literal"):
        validate_snapshot(document)


@pytest.mark.parametrize("site", ["n1", "NC1", "nc0", "abcdefg1"])
def test_rejects_invalid_site_codes(site: str) -> None:
    document = registry(sites=[site])

    with pytest.raises(RegistryValidationError, match="site code"):
        validate_snapshot(document)


def test_rejects_duplicate_sites() -> None:
    with pytest.raises(RegistryValidationError, match="duplicate site"):
        validate_snapshot(registry(sites=["nc1", "nc1"]))


@pytest.mark.parametrize(
    "hostname",
    [
        "nc1",
        "NC1-fox",
        "nc1--fox",
        "nc1-verylonghost",
    ],
)
def test_rejects_invalid_hostname_syntax_or_length(hostname: str) -> None:
    with pytest.raises(RegistryValidationError, match="hostname"):
        validate_snapshot(registry(active_host(hostname=hostname)))


def test_rejects_hostname_with_missing_site_prefix() -> None:
    with pytest.raises(RegistryValidationError, match="absent from sites"):
        validate_snapshot(registry(active_host(hostname="hk1-proxy-01")))


def test_rejects_duplicate_previous_hostname_and_current_in_history() -> None:
    with pytest.raises(RegistryValidationError, match="duplicate previous"):
        validate_snapshot(registry(active_host(previous=["nc1-old-01", "nc1-old-01"])))
    with pytest.raises(RegistryValidationError, match="also appears"):
        validate_snapshot(registry(active_host(previous=["nc1-fox-01"])))


def test_rejects_global_current_or_historical_name_collision() -> None:
    with pytest.raises(RegistryValidationError, match="appears more than once"):
        validate_snapshot(
            registry(
                active_host(),
                active_host(HOST_B, "nc1-fox-02", previous=["nc1-fox-01"]),
            )
        )


def test_rejects_active_retirement_and_retired_without_retirement() -> None:
    active = active_host().model_copy(
        update={
            "retirement": Retirement(
                retired_at="2026-08-29T10:00:00Z",
                reason="Wrong state",
                replacement_host_id=None,
            )
        }
    )
    retired = active_host().model_copy(update={"status": "retired"})

    with pytest.raises(RegistryValidationError, match="active host"):
        validate_snapshot(registry(active))
    with pytest.raises(RegistryValidationError, match="retired host"):
        validate_snapshot(registry(retired))


def test_rejects_retirement_before_registration() -> None:
    with pytest.raises(RegistryValidationError, match="earlier"):
        validate_snapshot(registry(retired_host(retired_at="2026-07-31T23:59:59Z")))


def test_rejects_replacement_missing_self_and_cycles() -> None:
    with pytest.raises(RegistryValidationError, match="does not exist"):
        validate_snapshot(registry(retired_host(replacement_host_id=HOST_B)))
    with pytest.raises(RegistryValidationError, match="replace itself"):
        validate_snapshot(registry(retired_host(replacement_host_id=HOST_A)))
    with pytest.raises(RegistryValidationError, match="cycle"):
        validate_snapshot(
            registry(
                retired_host(replacement_host_id=HOST_B),
                retired_host(HOST_B, "nc1-fox-02", replacement_host_id=HOST_A),
            )
        )


def test_allows_replacement_target_that_later_became_retired() -> None:
    validate_snapshot(
        registry(
            retired_host(replacement_host_id=HOST_B),
            retired_host(HOST_B, "nc1-fox-02"),
        )
    )


def test_rejects_empty_notes() -> None:
    with pytest.raises(RegistryValidationError, match="notes"):
        validate_snapshot(registry(active_host(notes=" ")))


def test_rejects_empty_retirement_reason() -> None:
    with pytest.raises(RegistryValidationError, match="reason"):
        validate_snapshot(registry(retired_host(reason=" ")))


def test_complete_fqdn_length_boundary() -> None:
    valid_suffix = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 55))
    validate_snapshot(registry(active_host(hostname="nc1-a"), dns_suffix=valid_suffix))

    overlong_suffix = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 56))
    with pytest.raises(RegistryValidationError, match=r"FQDN.*253"):
        validate_snapshot(registry(active_host(hostname="nc1-a"), dns_suffix=overlong_suffix))


@pytest.mark.parametrize(
    ("field", "document"),
    [
        ("notes", registry(active_host(notes="\ud800"))),
        ("retirement reason", registry(retired_host(reason="\ud800"))),
    ],
    ids=["notes", "retirement-reason"],
)
def test_rejects_non_utf8_encodable_free_text(field: str, document: Registry) -> None:
    with pytest.raises(RegistryValidationError, match=field):
        validate_snapshot(document)


def test_rejects_wrong_schema_version_and_non_object_json() -> None:
    raw = mapping(registry())
    raw["schema_version"] = 2
    with pytest.raises(RegistryValidationError, match="schema_version"):
        registry_from_bytes(json_bytes(raw))
    with pytest.raises(RegistryValidationError, match="JSON object"):
        registry_from_bytes(b"[]\n")


def test_rejects_bom_and_nonstandard_json_constants() -> None:
    with pytest.raises(RegistryValidationError, match="BOM"):
        registry_from_bytes(b"\xef\xbb\xbf{}")
    with pytest.raises(RegistryValidationError, match="non-standard"):
        registry_from_bytes(b'{"value": NaN}')


def test_noncanonical_registry_is_distinguishable_from_invalid_registry() -> None:
    document = registry()
    compact = json.dumps(mapping(document), separators=(",", ":")).encode()

    assert registry_from_bytes(compact, require_canonical=False) == document
    with pytest.raises(NonCanonicalRegistryError, match="semantically valid but not canonical"):
        registry_from_bytes(compact, require_canonical=True)
