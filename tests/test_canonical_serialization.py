from __future__ import annotations

from hostmark.services.registry_validation import canonical_bytes
from tests.helpers import HOST_A, HOST_B, active_host, registry, retired_host


def test_exact_golden_bytes_cover_all_field_orders_and_unicode() -> None:
    document = registry(
        active_host(
            HOST_B,
            "nc1-fox-02",
            registered_at="2026-08-29T09:50:00Z",
            previous=["nc1-fox-beta", "nc1-fox-old"],
            notes="直接 Unicode",
        ),
        retired_host(replacement_host_id=HOST_B),
        sites=["nc1"],
    )

    expected = """{
  \"schema_version\": 1,
  \"dns_suffix\": \"node.infra.example.com\",
  \"sites\": [
    \"nc1\"
  ],
  \"hosts\": [
    {
      \"host_id\": \"f0c5ebce-b37e-45d5-9f62-5c5a12f25116\",
      \"hostname\": \"nc1-fox-01\",
      \"status\": \"retired\",
      \"registered_at\": \"2026-08-01T09:30:00Z\",
      \"previous_hostnames\": [],
      \"retirement\": {
        \"retired_at\": \"2026-08-29T10:00:00Z\",
        \"reason\": \"Synthetic rebuild\",
        \"replacement_host_id\": \"2c179ac7-7252-46be-8dc4-0db8d83e5de1\"
      },
      \"notes\": null
    },
    {
      \"host_id\": \"2c179ac7-7252-46be-8dc4-0db8d83e5de1\",
      \"hostname\": \"nc1-fox-02\",
      \"status\": \"active\",
      \"registered_at\": \"2026-08-29T09:50:00Z\",
      \"previous_hostnames\": [
        \"nc1-fox-beta\",
        \"nc1-fox-old\"
      ],
      \"retirement\": null,
      \"notes\": \"直接 Unicode\"
    }
  ]
}
""".encode()

    assert canonical_bytes(document) == expected


def test_sites_and_hosts_sort_but_previous_history_does_not() -> None:
    document = registry(
        active_host(HOST_B, "nc1-zulu-01", previous=["nc1-old-02", "nc1-old-01"]),
        active_host(HOST_A, "hk1-alpha-01"),
        sites=["nc1", "hk1"],
    )

    data = canonical_bytes(document)

    assert data.index(b'"hk1"') < data.index(b'"nc1"')
    assert data.index(b'"hostname": "hk1-alpha-01"') < data.index(b'"hostname": "nc1-zulu-01"')
    assert data.index(b'"nc1-old-02"') < data.index(b'"nc1-old-01"')
