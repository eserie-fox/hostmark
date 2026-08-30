from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import hostmark.commands.check as check_commands
import hostmark.commands.identity as identity_commands
import hostmark.commands.registry as registry_commands
import hostmark.commands.repo as repo_commands
from hostmark.cli import app
from hostmark.domain.errors import HostmarkError
from hostmark.domain.models import Registry
from hostmark.services.host_state import check_host_state
from hostmark.services.identity_store import IdentityPaths, LocalIdentity
from hostmark.services.registry_store import initialize_registry, new_registry, resolve_registry_path
from hostmark.services.repository import (
    RepositorySyncResult,
    repository_paths,
)
from hostmark.version import __version__
from tests.helpers import HOST_A, HOST_B, active_host, canonical, registry, retired_host

RUNNER = CliRunner()


def test_root_help_and_version() -> None:
    root = RUNNER.invoke(app, [])
    version = RUNNER.invoke(app, ["--version"])

    assert root.exit_code == 0
    assert "Usage:" in root.stdout
    assert all(command in root.stdout for command in ("identity", "repo", "registry", "check"))
    assert version.exit_code == 0
    assert version.stdout == f"{__version__}\n"


def test_missing_required_argument_uses_cli_usage_code_two() -> None:
    result = RUNNER.invoke(app, ["registry", "register"])

    assert result.exit_code == 2


def test_representative_project_errors_are_concise_without_tracebacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = IdentityPaths(system=tmp_path / "system-id", user=tmp_path / "user-id")
    monkeypatch.setattr(identity_commands, "identity_paths", lambda: paths)

    missing_identity = RUNNER.invoke(app, ["identity", "show"])

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"schema_version": 1}\n', encoding="utf-8")
    invalid_registry = RUNNER.invoke(app, ["registry", "validate", "--registry", str(invalid_path)])

    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("regular file", encoding="utf-8")
    filesystem_failure = RUNNER.invoke(
        app,
        [
            "registry",
            "init",
            "--registry",
            str(parent_file / "hosts.json"),
            "--dns-suffix",
            "node.infra.example.com",
            "--site",
            "nc1",
        ],
    )

    cases = [
        (missing_identity, 3, "local identity is not initialized"),
        (invalid_registry, 8, "invalid registry field"),
        (filesystem_failure, 1, "could not create registry parent directory"),
    ]
    for result, exit_code, message in cases:
        assert result.exit_code == exit_code
        assert result.stderr.startswith("Error: ")
        assert message in result.stderr
        assert "Traceback" not in result.output
        assert "Error(" not in result.output


def test_registry_init_register_list_show_and_validate_outputs(tmp_path: Path) -> None:
    path = tmp_path / "registry" / "hosts.json"

    initialized = RUNNER.invoke(
        app,
        [
            "registry",
            "init",
            "--registry",
            str(path),
            "--dns-suffix",
            "node.infra.example.com",
            "--site",
            "nc1",
        ],
    )
    registered = RUNNER.invoke(
        app,
        [
            "registry",
            "register",
            "nc1-orange",
            "--registry",
            str(path),
            "--host-id",
            HOST_A,
        ],
    )
    listed = RUNNER.invoke(app, ["registry", "list", "--registry", str(path)])
    shown = RUNNER.invoke(app, ["registry", "show", HOST_A, "--registry", str(path)])
    validated = RUNNER.invoke(app, ["registry", "validate", "--registry", str(path)])

    for result in (initialized, registered, listed, shown, validated):
        assert result.exit_code == 0, result.output
    assert f"Initialized registry: {path}" in initialized.stdout
    assert "Registered: nc1-orange" in registered.stdout
    assert HOST_A in registered.stdout
    assert "nc1-orange.node.infra.example.com" in registered.stdout
    assert "HOSTNAME\tSTATUS\tHOST ID" in listed.stdout
    assert "nc1-orange\tactive" in listed.stdout
    assert "Previous hostnames: -" in shown.stdout
    assert "Registry is valid and canonical" in validated.stdout


def test_register_uses_discovered_local_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "hosts.json"
    initialize_registry(path, new_registry(dns_suffix="node.infra.example.com", sites=["nc1"]))
    identity_file = tmp_path / "identity" / "host-id"
    identity_file.parent.mkdir(parents=True)
    identity_file.write_bytes(f"{HOST_A}\n".encode("ascii"))
    paths = IdentityPaths(system=tmp_path / "system" / "host-id", user=identity_file)
    monkeypatch.setattr(registry_commands, "identity_paths", lambda: paths)

    result = RUNNER.invoke(
        app,
        ["registry", "register", "nc1-orange", "--registry", str(path)],
    )

    assert result.exit_code == 0, result.output
    assert f"Host ID: {HOST_A}" in result.stdout


def test_mutation_dry_run_and_summary_outputs(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    original = canonical(registry(active_host(), active_host(HOST_B, "nc1-live-02")))
    path.write_bytes(original)

    dry = RUNNER.invoke(
        app,
        ["registry", "rename", HOST_A, "nc1-fox-02", "--registry", str(path), "--dry-run"],
    )
    assert path.read_bytes() == original
    renamed = RUNNER.invoke(
        app,
        ["registry", "rename", HOST_A, "nc1-fox-02", "--registry", str(path)],
    )
    retired = RUNNER.invoke(
        app,
        [
            "registry",
            "retire",
            "nc1-fox-02",
            "--reason",
            "Rebuilt",
            "--replacement",
            "nc1-live-02",
            "--registry",
            str(path),
        ],
    )

    assert dry.exit_code == 0, dry.output
    assert dry.stdout.startswith(f"--- {path}\n+++ {path}\n")
    assert "Dry run - would rename: nc1-fox-01 -> nc1-fox-02" in dry.stdout
    assert renamed.exit_code == 0 and "Renamed: nc1-fox-01 -> nc1-fox-02" in renamed.stdout
    assert retired.exit_code == 0 and "Retired: nc1-fox-02" in retired.stdout
    assert f"Replacement host ID: {HOST_B}" in retired.stdout


def test_show_resolves_replacement_and_reverse_relationship(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    path.write_bytes(canonical(registry(retired_host(replacement_host_id=HOST_B), active_host(HOST_B, "nc1-fox-02"))))

    old = RUNNER.invoke(app, ["registry", "show", HOST_A, "--registry", str(path)])
    new = RUNNER.invoke(app, ["registry", "show", HOST_B, "--registry", str(path)])

    assert old.exit_code == 0 and "Replacement hostname: nc1-fox-02" in old.stdout
    assert new.exit_code == 0 and "Replaces retired hosts: nc1-fox-01" in new.stdout


def test_list_filters_status_and_site(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    path.write_bytes(
        canonical(
            registry(
                retired_host(),
                active_host(HOST_B, "hk1-proxy-01"),
                sites=["nc1", "hk1"],
            )
        )
    )

    active = RUNNER.invoke(app, ["registry", "list", "-r", str(path), "--status", "active"])
    nc1 = RUNNER.invoke(app, ["registry", "list", "-r", str(path), "--site", "nc1"])

    assert active.exit_code == 0
    assert "hk1-proxy-01" in active.stdout and "nc1-fox-01" not in active.stdout
    assert nc1.exit_code == 0
    assert "nc1-fox-01" in nc1.stdout and "hk1-proxy-01" not in nc1.stdout


def test_format_and_baseline_validation_cli_summaries(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_bytes(canonical(registry(active_host(), sites=["nc1"])))
    candidate = registry(
        active_host(hostname="nc1-fox-02", previous=["nc1-fox-01"], notes="changed"),
        active_host(HOST_B, "hk1-proxy-01"),
        sites=["hk1", "nc1"],
        dns_suffix="node.new-example.com",
    )
    candidate_path.write_bytes(canonical(candidate))

    checked = RUNNER.invoke(app, ["registry", "format", "-r", str(candidate_path), "--check"])
    validated = RUNNER.invoke(
        app,
        ["registry", "validate", "-r", str(candidate_path), "--against", str(baseline_path)],
    )

    assert checked.exit_code == 0 and "canonical" in checked.stdout
    assert validated.exit_code == 0, validated.output
    assert "Additions: hk1-proxy-01" in validated.stdout
    assert "Renames: nc1-fox-01 -> nc1-fox-02" in validated.stdout
    assert "Notes changes: nc1-fox-02" in validated.stdout
    assert "Site additions: hk1" in validated.stdout
    assert "WARNING:" in validated.stdout and "every computed FQDN changes" in validated.stdout


def test_check_cli_success_and_stable_mismatch_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "hosts.json"
    path.write_bytes(canonical(registry(active_host())))
    identity = LocalIdentity(host_id=HOST_A, scope="user", path=tmp_path / "host-id")
    monkeypatch.setattr(check_commands, "discover_identity", lambda paths: identity)

    def controlled_check(document: Registry, local_identity: LocalIdentity):
        return check_host_state(document, local_identity, hostname_reader=lambda: "NC1-FOX-01.example.com.")

    monkeypatch.setattr(check_commands, "check_host_state", controlled_check)
    success = RUNNER.invoke(app, ["check", "--registry", str(path)])

    assert success.exit_code == 0, success.output
    assert f"Identity file: {identity.path}" in success.stdout
    assert "Actual name: NC1-FOX-01.example.com." in success.stdout
    assert "FQDN: nc1-fox-01.node.infra.example.com" in success.stdout

    def mismatch(document: Registry, local_identity: LocalIdentity):
        return check_host_state(document, local_identity, hostname_reader=lambda: "nc1-old-01")

    monkeypatch.setattr(check_commands, "check_host_state", mismatch)
    failure = RUNNER.invoke(app, ["check", "--registry", str(path)])
    assert failure.exit_code == 6
    assert "hostname drift" in failure.stderr


def test_direct_registry_overrides_preserve_old_layout_support(tmp_path: Path) -> None:
    explicit = resolve_registry_path(Path("chosen.json"), environ={}, cwd=tmp_path)
    configured = resolve_registry_path(None, environ={"HOSTMARK_REGISTRY": "env.json"}, cwd=tmp_path)
    old_layout = tmp_path / "old" / "registry" / "hosts.json"

    assert explicit == (tmp_path / "chosen.json").resolve()
    assert configured == (tmp_path / "env.json").resolve()
    assert resolve_registry_path(old_layout, environ={}, cwd=tmp_path) == old_layout.resolve()


def test_registry_path_resolves_repository_env_ancestor_and_default(tmp_path: Path) -> None:
    configured = repository_paths(tmp_path / "configured")
    configured.root.mkdir()
    configured.marker.write_bytes(b"")
    assert (
        resolve_registry_path(None, environ={"HOSTMARK_REPO": str(configured.root)}, cwd=tmp_path)
        == configured.registry
    )

    marked = repository_paths(tmp_path / "marked")
    nested = marked.root / "one" / "two"
    nested.mkdir(parents=True)
    marked.marker.write_bytes(b"")
    assert resolve_registry_path(None, environ={}, cwd=nested) == marked.registry

    home = tmp_path / "home"
    default = repository_paths(home / ".local" / "share" / "hostmark" / "repo")
    default.root.mkdir(parents=True)
    default.marker.write_bytes(b"")
    assert (
        resolve_registry_path(None, environ={}, cwd=tmp_path / "isolated", platform_name="linux", home=home)
        == default.registry
    )


def test_old_implicit_registry_layout_is_not_discovered_and_init_guidance_is_actionable(tmp_path: Path) -> None:
    old = tmp_path / "registry" / "hosts.json"
    old.parent.mkdir()
    old.write_bytes(b"placeholder")
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)

    with pytest.raises(HostmarkError) as exc_info:
        resolve_registry_path(
            None, environ={}, cwd=nested, platform_name="linux", home=tmp_path / "home", for_init=True
        )

    message = str(exc_info.value)
    assert "--registry" in message
    assert "hostmark repo init" in message
    assert "registry/hosts.json" not in message


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_repo_path_and_init_cli(tmp_path: Path) -> None:
    paths = repository_paths(tmp_path / "inventory")
    selected = RUNNER.invoke(app, ["repo", "path", "--repo", str(paths.root)])
    assert not paths.root.exists()
    initialized = RUNNER.invoke(
        app,
        [
            "repo",
            "init",
            "--repo",
            str(paths.root),
            "--dns-suffix",
            "node.infra.example.com",
            "--site",
            "nc1",
        ],
    )

    assert selected.exit_code == 0, selected.output
    assert f"Repository: {paths.root}" in selected.stdout
    assert f"Marker:     {paths.marker}" in selected.stdout
    assert initialized.exit_code == 0, initialized.output
    assert "Git branch: main" in initialized.stdout
    assert "git add HOSTMARK_REPOSITORY hosts.json" in initialized.stdout


def test_repo_sync_cli_summary_and_error_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = repository_paths(tmp_path / "clone")
    monkeypatch.setattr(
        repo_commands,
        "sync_repository",
        lambda selected, remote=None: RepositorySyncResult(paths=selected, operation="cloned"),
    )
    success = RUNNER.invoke(app, ["repo", "sync", "--repo", str(paths.root), "--remote", "file:///remote.git"])

    def fail_sync(selected: object, remote: str | None = None) -> RepositorySyncResult:
        del selected, remote
        raise HostmarkError("could not clone repository")

    monkeypatch.setattr(repo_commands, "sync_repository", fail_sync)
    failure = RUNNER.invoke(app, ["repo", "sync", "--repo", str(paths.root), "--remote", "file:///remote.git"])

    assert success.exit_code == 0
    assert f"Cloned repository: {paths.root}" in success.stdout
    assert failure.exit_code == 1
    assert "could not clone repository" in failure.stderr
    assert "Traceback" not in failure.output
