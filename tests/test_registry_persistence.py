from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from hostmark.domain.errors import (
    ConcurrentModificationError,
    HostmarkError,
    NonCanonicalRegistryError,
    RegistryValidationError,
)
from hostmark.services.registry_store import (
    format_registry,
    initialize_registry,
    mutate_registry,
    new_registry,
    rename_host,
)
from tests.helpers import HOST_A, active_host, canonical, json_bytes, mapping, registry


def write_registry(path: Path) -> bytes:
    data = canonical(registry(active_host()))
    path.write_bytes(data)
    return data


def test_dry_run_emits_unified_lf_diff_and_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    original = write_registry(path)

    result = mutate_registry(
        path,
        lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"),
        dry_run=True,
    )

    assert path.read_bytes() == original
    assert result.wrote is False
    assert result.diff is not None
    assert result.diff.startswith(f"--- {path}\n+++ {path}\n")
    assert '-      "hostname": "nc1-fox-01"' in result.diff
    assert '+      "hostname": "nc1-fox-02"' in result.diff
    assert "\r" not in result.diff


def test_mutation_atomically_replaces_registry(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    write_registry(path)

    result = mutate_registry(path, lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"))

    assert result.wrote is True
    assert b'"hostname": "nc1-fox-02"' in path.read_bytes()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are required")
def test_mutation_preserves_posix_permissions(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    write_registry(path)
    path.chmod(0o640)

    mutate_registry(path, lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_source_change_during_mutation_aborts_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    write_registry(path)
    concurrent = canonical(registry(active_host(notes="concurrent edit")))

    def change_source() -> None:
        path.write_bytes(concurrent)

    with pytest.raises(ConcurrentModificationError):
        mutate_registry(
            path,
            lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"),
            before_compare=change_source,
        )

    assert path.read_bytes() == concurrent


def test_temporary_file_is_cleaned_after_replace_failure(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    original = write_registry(path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("synthetic replace failure")

    with pytest.raises(HostmarkError, match="atomically replace"):
        mutate_registry(
            path,
            lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"),
            replace=fail_replace,
        )

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".hosts.json.*.tmp")) == []


def test_registry_parent_creation_failure_is_a_project_error(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("regular file", encoding="utf-8")
    path = parent_file / "hosts.json"

    with pytest.raises(HostmarkError, match="could not create registry parent directory"):
        initialize_registry(path, new_registry(dns_suffix="node.infra.example.com", sites=["nc1"]))

    assert parent_file.read_text(encoding="utf-8") == "regular file"


def test_post_write_reread_is_strictly_validated(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    write_registry(path)

    def corrupt_after_replace(source: Path, destination: Path) -> None:
        os.replace(source, destination)
        destination.write_bytes(b"{}\n")

    with pytest.raises(RegistryValidationError):
        mutate_registry(
            path,
            lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"),
            replace=corrupt_after_replace,
        )


def test_ordinary_mutation_requires_canonical_source(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    path.write_bytes(json_bytes(mapping(registry(active_host())), indent=None))

    with pytest.raises(NonCanonicalRegistryError, match="registry format"):
        mutate_registry(path, lambda value: rename_host(value, selector=HOST_A, new_hostname="nc1-fox-02"))


def test_format_check_and_rewrite_are_representation_only(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    noncanonical = json_bytes(mapping(registry(active_host())), indent=None, final_newline=False)
    path.write_bytes(noncanonical)

    with pytest.raises(NonCanonicalRegistryError) as exc_info:
        format_registry(path, check=True)
    assert exc_info.value.exit_code == 8
    assert path.read_bytes() == noncanonical

    result = format_registry(path, check=False)
    assert result.changed is True and result.wrote is True
    assert path.read_bytes() == canonical(registry(active_host()))
    assert format_registry(path, check=True).changed is False
    assert format_registry(path, check=False).changed is False


def test_format_refuses_semantically_invalid_data_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    raw = mapping(registry(active_host()))
    raw["hosts"][0]["hostname"] = "INVALID"
    invalid = json_bytes(raw, indent=None)
    path.write_bytes(invalid)

    with pytest.raises(RegistryValidationError):
        format_registry(path, check=False)

    assert path.read_bytes() == invalid
