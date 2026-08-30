from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

import hostmark.services.repository as repository_service
from hostmark.domain.errors import HostmarkError
from hostmark.services.registry_store import new_registry, read_registry
from hostmark.services.registry_validation import canonical_bytes
from hostmark.services.repository import (
    REPOSITORY_ENV,
    REPOSITORY_MARKER_NAME,
    default_repository_root,
    discover_repository_root,
    initialize_repository,
    repository_paths,
    resolve_repository_paths,
    sync_repository,
    validate_repository_marker,
)


@pytest.mark.parametrize(
    ("platform_name", "environ", "home", "expected"),
    [
        ("linux", {}, Path("/home/example"), Path("/home/example/.local/share/hostmark/repo")),
        (
            "linux",
            {"XDG_DATA_HOME": "/custom/data"},
            Path("/home/example"),
            Path("/custom/data/hostmark/repo"),
        ),
        (
            "linux",
            {"XDG_DATA_HOME": "relative/data"},
            Path("/home/example"),
            Path("/home/example/.local/share/hostmark/repo"),
        ),
        (
            "darwin",
            {},
            Path("/Users/example"),
            Path("/Users/example/Library/Application Support/Hostmark/repo"),
        ),
        (
            "win32",
            {"localappdata": "C:/Users/Fox/AppData/Local"},
            Path("C:/Users/Fox"),
            Path("C:/Users/Fox/AppData/Local/Hostmark/repo"),
        ),
        (
            "win32",
            {},
            Path("C:/Users/Fox"),
            Path("C:/Users/Fox/AppData/Local/Hostmark/repo"),
        ),
    ],
)
def test_default_repository_paths(
    platform_name: str,
    environ: dict[str, str],
    home: Path,
    expected: Path,
) -> None:
    assert default_repository_root(platform_name=platform_name, environ=environ, home=home) == expected


def test_repository_resolution_precedence_discovery_and_default(tmp_path: Path) -> None:
    marked = tmp_path / "inventory"
    nested = marked / "one" / "two"
    nested.mkdir(parents=True)
    (marked / REPOSITORY_MARKER_NAME).write_bytes(b"")
    explicit = tmp_path / "explicit"
    configured = tmp_path / "configured"

    assert resolve_repository_paths(explicit, environ={REPOSITORY_ENV: str(configured)}, cwd=nested).root == explicit
    assert resolve_repository_paths(None, environ={REPOSITORY_ENV: str(configured)}, cwd=nested).root == configured
    assert resolve_repository_paths(None, environ={}, cwd=nested).root == marked.resolve()

    isolated = tmp_path / "isolated" / "child"
    isolated.mkdir(parents=True)
    fallback = resolve_repository_paths(
        None,
        environ={},
        cwd=isolated,
        platform_name="linux",
        home=tmp_path / "home",
    )
    assert fallback.root == tmp_path / "home" / ".local" / "share" / "hostmark" / "repo"


@pytest.mark.parametrize("marker_state", ["missing", "directory", "nonempty"])
def test_invalid_repository_markers_are_rejected(tmp_path: Path, marker_state: str) -> None:
    paths = repository_paths(tmp_path / marker_state)
    paths.root.mkdir()
    if marker_state == "directory":
        paths.marker.mkdir()
    elif marker_state == "nonempty":
        paths.marker.write_bytes(b"not empty")

    with pytest.raises(HostmarkError, match="marker"):
        validate_repository_marker(paths)


def test_zero_byte_repository_marker_is_valid(tmp_path: Path) -> None:
    paths = repository_paths(tmp_path / "arbitrary-directory-name")
    paths.root.mkdir()
    paths.marker.write_bytes(b"")

    validate_repository_marker(paths)
    assert paths.marker.read_bytes() == b""


def test_nearer_invalid_marker_blocks_farther_repository(tmp_path: Path) -> None:
    (tmp_path / REPOSITORY_MARKER_NAME).write_bytes(b"")
    nearer = tmp_path / "nearer"
    child = nearer / "child"
    child.mkdir(parents=True)
    (nearer / REPOSITORY_MARKER_NAME).write_bytes(b"invalid")

    with pytest.raises(HostmarkError, match="zero bytes"):
        discover_repository_root(child)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_initialize_repository_creates_unborn_main_without_staging_or_remote(tmp_path: Path) -> None:
    paths = repository_paths(tmp_path / "inventory")

    result = initialize_repository(paths, dns_suffix="node.infra.example.com", sites=["nc1", "hk1"])

    assert result.branch == "main"
    assert paths.marker.read_bytes() == b""
    registry = read_registry(paths.registry, require_canonical=True).registry
    assert registry.sites == ["hk1", "nc1"]
    assert registry.hosts == []
    assert _git(paths.root, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert _git(paths.root, "rev-parse", "--verify", "HEAD", check=False).returncode != 0
    assert set(_git(paths.root, "status", "--porcelain").stdout.splitlines()) == {
        "?? HOSTMARK_REPOSITORY",
        "?? hosts.json",
    }
    assert _git(paths.root, "remote").stdout == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_initialize_repository_accepts_empty_target_and_rejects_occupied_target(tmp_path: Path) -> None:
    empty = repository_paths(tmp_path / "empty")
    empty.root.mkdir()
    initialize_repository(empty, dns_suffix="node.infra.example.com", sites=["nc1"])

    occupied = repository_paths(tmp_path / "occupied")
    occupied.root.mkdir()
    (occupied.root / "unrelated.txt").write_text("occupied\n", encoding="utf-8")
    with pytest.raises(HostmarkError, match="not empty"):
        initialize_repository(occupied, dns_suffix="node.infra.example.com", sites=["nc1"])


def test_sync_requires_remote_and_system_git_for_new_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = repository_paths(tmp_path / "clone")
    with pytest.raises(HostmarkError, match="--remote"):
        sync_repository(paths)

    monkeypatch.setattr(repository_service.shutil, "which", lambda command: None)
    with pytest.raises(HostmarkError, match="git is not available"):
        sync_repository(paths, remote=str(tmp_path / "remote.git"))

    git_environment = repository_service._git_environment("git@example.com:infra/hosts.git")
    assert git_environment["GIT_TERMINAL_PROMPT"] == "0"
    assert git_environment["GIT_ASKPASS"] == "echo"
    assert "BatchMode=yes" in git_environment["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in git_environment["GIT_SSH_COMMAND"]
    assert "https://<redacted>@example.com" in repository_service._redact_url_userinfo(
        "https://user:password@example.com/repo.git"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_clones_local_remote_and_validates_registry(tmp_path: Path) -> None:
    source, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    empty_clone = repository_paths(tmp_path / "empty-clone")
    empty_clone.root.mkdir()

    result = sync_repository(clone, remote=str(remote))
    empty_result = sync_repository(empty_clone, remote=str(remote))

    assert result.operation == "cloned"
    assert empty_result.operation == "cloned"
    assert clone.marker.read_bytes() == b""
    assert (
        read_registry(clone.registry, require_canonical=True).registry
        == read_registry(source.registry, require_canonical=True).registry
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_fast_forwards_with_untracked_files_and_rejects_tracked_changes(tmp_path: Path) -> None:
    source, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    sync_repository(clone, remote=str(remote))

    updated = new_registry(dns_suffix="nodes.example.com", sites=["nc1", "hk1"])
    source.registry.write_bytes(canonical_bytes(updated))
    _git(source.root, "add", "hosts.json")
    _git(source.root, "commit", "-m", "Update registry")
    _git(source.root, "push")

    (clone.root / "local-note.txt").write_text("untracked\n", encoding="utf-8")
    result = sync_repository(clone)
    assert result.operation == "updated"
    assert read_registry(clone.registry, require_canonical=True).registry.dns_suffix == "nodes.example.com"

    clone.registry.write_bytes(canonical_bytes(new_registry(dns_suffix="changed.example.com", sites=["nc1"])))
    with pytest.raises(HostmarkError, match="tracked changes"):
        sync_repository(clone)


def test_existing_repository_git_preflight_errors_are_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repository_service.shutil, "which", lambda command: "/usr/bin/git")
    scenarios = {
        "detached": "detached HEAD",
        "no-upstream": "no upstream",
        "no-origin": "no origin",
        "remote-mismatch": "does not match",
        "root-mismatch": "top-level root",
        "not-git": "not a Git worktree",
    }
    for scenario, expected in scenarios.items():
        paths = repository_paths(tmp_path / scenario)
        paths.root.mkdir()
        paths.marker.write_bytes(b"")
        paths.registry.write_bytes(canonical_bytes(new_registry(dns_suffix="node.example.com", sites=["nc1"])))
        monkeypatch.setattr(repository_service, "_run_git", _preflight_git_runner(scenario, paths))
        supplied = "file:///different.git" if scenario == "remote-mismatch" else None
        with pytest.raises(HostmarkError, match=expected):
            sync_repository(paths, remote=supplied)

    synchronized = repository_paths(tmp_path / "synchronized")
    synchronized.root.mkdir()
    synchronized.marker.write_bytes(b"")
    synchronized.registry.write_bytes(canonical_bytes(new_registry(dns_suffix="node.example.com", sites=["nc1"])))
    commands: list[tuple[str, ...]] = []

    def successful_run_git(
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        remote_url: str | None = None,
        action: str,
    ) -> str:
        del cwd, remote_url, action
        command = tuple(arguments)
        commands.append(command)
        outputs = {
            ("rev-parse", "--show-toplevel"): str(synchronized.root),
            ("symbolic-ref", "--quiet", "--short", "HEAD"): "main",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            ("remote", "get-url", "origin"): "file:///expected.git",
            ("status", "--porcelain=v1", "--untracked-files=no"): "",
            ("pull", "--ff-only"): "Already up to date.",
        }
        return outputs[command]

    monkeypatch.setattr(repository_service, "_run_git", successful_run_git)
    sync_repository(synchronized)
    assert ("status", "--porcelain=v1", "--untracked-files=no") in commands
    assert commands[-1] == ("pull", "--ff-only")


def test_post_clone_registry_validation_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = repository_paths(tmp_path / "clone")
    monkeypatch.setattr(repository_service.shutil, "which", lambda command: "/usr/bin/git")

    def fake_clone(
        arguments: list[str] | tuple[str, ...],
        *,
        cwd: Path | None = None,
        remote_url: str | None = None,
        action: str,
    ) -> str:
        del cwd, remote_url, action
        assert tuple(arguments[:1]) == ("clone",)
        paths.root.mkdir()
        paths.marker.write_bytes(b"")
        paths.registry.write_bytes(b"{}\n")
        return ""

    monkeypatch.setattr(repository_service, "_run_git", fake_clone)
    with pytest.raises(HostmarkError, match=r"synchronization completed.*invalid"):
        sync_repository(paths, remote="file:///synthetic.git")


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def _create_remote(tmp_path: Path) -> tuple[repository_service.RepositoryPaths, Path]:
    source = repository_paths(tmp_path / "source")
    initialize_repository(source, dns_suffix="node.infra.example.com", sites=["nc1"])
    _git(source.root, "config", "user.email", "tests@example.com")
    _git(source.root, "config", "user.name", "Hostmark Tests")
    _git(source.root, "add", REPOSITORY_MARKER_NAME, "hosts.json")
    _git(source.root, "commit", "-m", "Initialize inventory")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(source.root, "remote", "add", "origin", str(remote))
    _git(source.root, "push", "-u", "origin", "main")
    return source, remote


def _preflight_git_runner(
    scenario: str,
    paths: repository_service.RepositoryPaths,
) -> Callable[..., str]:
    def fake_run_git(
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        remote_url: str | None = None,
        action: str,
    ) -> str:
        del cwd, remote_url, action
        command = tuple(arguments)
        if command == ("rev-parse", "--show-toplevel"):
            if scenario == "not-git":
                raise HostmarkError("synthetic non-repository")
            if scenario == "root-mismatch":
                return str(paths.root.parent)
            return str(paths.root)
        if command == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            if scenario == "detached":
                raise HostmarkError("synthetic detached HEAD")
            return "main"
        if command == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
            if scenario == "no-upstream":
                raise HostmarkError("synthetic missing upstream")
            return "origin/main"
        if command == ("remote", "get-url", "origin"):
            if scenario == "no-origin":
                raise HostmarkError("synthetic missing origin")
            return "file:///expected.git"
        raise AssertionError(f"unexpected Git command: {command}")

    return fake_run_git
