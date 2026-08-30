from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
from git import Actor, Repo
from git.exc import GitCommandError, UnsafeOptionError, UnsafeProtocolError
from git.remote import Remote
from typer.testing import CliRunner

import hostmark.services.repository as repository_service
from hostmark.cli import app
from hostmark.domain.errors import HostmarkError, RegistryValidationError
from hostmark.services.registry_store import new_registry, read_registry
from hostmark.services.registry_validation import canonical_bytes
from hostmark.services.repository import (
    REPOSITORY_ATTRIBUTES_BYTES,
    REPOSITORY_ATTRIBUTES_NAME,
    REPOSITORY_ENV,
    REPOSITORY_MARKER_NAME,
    REPOSITORY_REGISTRY_NAME,
    default_repository_root,
    discover_repository_root,
    initialize_repository,
    repository_paths,
    resolve_repository_paths,
    sync_repository,
    validate_repository_attributes,
    validate_repository_marker,
    validate_repository_metadata,
)

GIT_ACTOR = Actor("Hostmark Tests", "tests@example.com")
RUNNER = CliRunner()
REQUIRED_PATHS = {
    REPOSITORY_ATTRIBUTES_NAME,
    REPOSITORY_MARKER_NAME,
    REPOSITORY_REGISTRY_NAME,
}
TEST_GIT_CONFIG_BYTES = b'[protocol "file"]\n\tallow = always\n'
GIT_ENVIRONMENT_OVERRIDES = {
    "GIT_ALLOW_PROTOCOL",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_EXEC_PATH",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PROTOCOL_FROM_USER",
    "GIT_SHALLOW_FILE",
    "GIT_TEMPLATE_DIR",
    "GIT_WORK_TREE",
}


@pytest.fixture(autouse=True)
def isolate_git_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        normalized_name = name.upper()
        if normalized_name.startswith("GIT_CONFIG_") or normalized_name in GIT_ENVIRONMENT_OVERRIDES:
            monkeypatch.delenv(name, raising=False)
    config = tmp_path / "hostmark-test.gitconfig"
    config.write_bytes(TEST_GIT_CONFIG_BYTES)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_ATTR_NOSYSTEM", "1")


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


@pytest.mark.parametrize("attributes_state", ["missing", "directory", "noncanonical"])
def test_invalid_repository_attributes_are_rejected(tmp_path: Path, attributes_state: str) -> None:
    paths = repository_paths(tmp_path / attributes_state)
    paths.root.mkdir()
    if attributes_state == "directory":
        paths.attributes.mkdir()
    elif attributes_state == "noncanonical":
        paths.attributes.write_bytes(b"/hosts.json text\n")

    with pytest.raises(HostmarkError, match="attributes"):
        validate_repository_attributes(paths)


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
def test_initialize_repository_creates_canonical_untracked_files_on_unborn_main(tmp_path: Path) -> None:
    paths = repository_paths(tmp_path / "inventory")

    result = initialize_repository(paths, dns_suffix="node.infra.example.com", sites=["nc1", "hk1"])

    assert result.branch == "main"
    assert paths.attributes.read_bytes() == REPOSITORY_ATTRIBUTES_BYTES
    assert paths.marker.read_bytes() == b""
    registry = read_registry(paths.registry, require_canonical=True).registry
    assert registry.sites == ["hk1", "nc1"]
    assert registry.hosts == []
    with Repo(paths.root, search_parent_directories=False) as repo:
        assert repo.active_branch.name == "main"
        assert not repo.head.is_valid()
        assert repo.index.entries == {}
        assert set(repo.untracked_files) == REQUIRED_PATHS
        assert list(repo.remotes) == []

    with pytest.raises(HostmarkError, match="not tracked"):
        sync_repository(paths)


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


def test_sync_passes_noninteractive_environment_to_ssh_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fail_clone(*args: object, **kwargs: object) -> None:
        del args
        captured.update(kwargs)
        raise GitCommandError(["git", "clone"], 128, stderr="synthetic clone failure")

    monkeypatch.setattr(repository_service.shutil, "which", lambda command: "git")
    monkeypatch.setattr(Repo, "clone_from", fail_clone)

    with pytest.raises(HostmarkError, match="could not clone"):
        sync_repository(repository_paths(tmp_path / "clone"), remote="git@example.com:infra/hosts.git")

    environment = captured["env"]
    assert isinstance(environment, Mapping)
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_ASKPASS"] == "echo"
    assert "BatchMode=yes" in environment["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in environment["GIT_SSH_COMMAND"]


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_clones_absent_and_empty_targets_and_validates_registry(tmp_path: Path) -> None:
    source, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    empty_clone = repository_paths(tmp_path / "empty-clone")
    empty_clone.root.mkdir()

    result = sync_repository(clone, remote=str(remote))
    empty_result = sync_repository(empty_clone, remote=str(remote))
    updated_result = sync_repository(clone, remote=str(remote))

    assert result.operation == "cloned"
    assert empty_result.operation == "cloned"
    assert updated_result.operation == "updated"
    assert clone.attributes.read_bytes() == REPOSITORY_ATTRIBUTES_BYTES
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
    with Repo(source.root, search_parent_directories=False) as repo:
        _commit(repo, [REPOSITORY_REGISTRY_NAME], "Update registry")
        repo.remotes.origin.push("main")

    (clone.root / "local-note.txt").write_text("untracked\n", encoding="utf-8")
    result = sync_repository(clone)
    assert result.operation == "updated"
    assert read_registry(clone.registry, require_canonical=True).registry.dns_suffix == "nodes.example.com"

    clone.registry.write_bytes(canonical_bytes(new_registry(dns_suffix="changed.example.com", sites=["nc1"])))
    with pytest.raises(HostmarkError, match="tracked changes"):
        sync_repository(clone)


@pytest.mark.parametrize("required_path", sorted(REQUIRED_PATHS))
@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_requires_every_hostmark_file_to_be_tracked(tmp_path: Path, required_path: str) -> None:
    _, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    sync_repository(clone, remote=str(remote))
    with Repo(clone.root, search_parent_directories=False) as repo:
        repo.index.remove([required_path], working_tree=False)

    with pytest.raises(HostmarkError, match=re.escape(required_path)):
        sync_repository(clone)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_requires_origin_tracking_branch_and_matching_remote(tmp_path: Path) -> None:
    _, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    sync_repository(clone, remote=str(remote))

    with Repo(clone.root, search_parent_directories=False) as repo:
        backup = repo.create_remote("backup", str(remote))
        backup.fetch()
        repo.active_branch.set_tracking_branch(backup.refs.main)

    with pytest.raises(HostmarkError, match=r"tracks backup/main.*origin/\*"):
        sync_repository(clone)

    with Repo(clone.root, search_parent_directories=False) as repo:
        repo.active_branch.set_tracking_branch(repo.remotes.origin.refs.main)
    with pytest.raises(HostmarkError, match="does not match"):
        sync_repository(clone, remote=str(tmp_path / "different.git"))


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_rejects_detached_head(tmp_path: Path) -> None:
    _, remote = _create_remote(tmp_path)
    detached = repository_paths(tmp_path / "detached")
    sync_repository(detached, remote=str(remote))
    with Repo(detached.root, search_parent_directories=False) as repo:
        repo.head.reference = repo.head.commit
    with pytest.raises(HostmarkError, match="detached HEAD"):
        sync_repository(detached)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_rejects_missing_upstream(tmp_path: Path) -> None:
    _, remote = _create_remote(tmp_path)
    no_upstream = repository_paths(tmp_path / "no-upstream")
    sync_repository(no_upstream, remote=str(remote))
    with Repo(no_upstream.root, search_parent_directories=False) as repo:
        repo.active_branch.set_tracking_branch(None)
    with pytest.raises(HostmarkError, match="no upstream"):
        sync_repository(no_upstream)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_rejects_missing_origin(tmp_path: Path) -> None:
    _, remote = _create_remote(tmp_path)
    no_origin = repository_paths(tmp_path / "no-origin")
    sync_repository(no_origin, remote=str(remote))
    with Repo(no_origin.root, search_parent_directories=False) as repo:
        repo.delete_remote(repo.remotes.origin)
    with pytest.raises(HostmarkError, match="no origin"):
        sync_repository(no_origin)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_sync_rejects_non_repository(tmp_path: Path) -> None:
    not_git = repository_paths(tmp_path / "not-git")
    not_git.root.mkdir()
    _write_repository_metadata(not_git)
    with pytest.raises(HostmarkError, match="not a Git worktree"):
        sync_repository(not_git)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_linked_worktree_is_accepted_at_its_exact_root_and_rejected_below_it(tmp_path: Path) -> None:
    source, _ = _create_remote(tmp_path)
    linked_root = tmp_path / "linked"
    with Repo(source.root, search_parent_directories=False) as repo:
        repo.git.worktree("add", "-b", "linked", str(linked_root), "origin/main")

    assert (linked_root / ".git").is_file()
    result = sync_repository(repository_paths(linked_root))
    assert result.operation == "updated"

    nested = repository_paths(linked_root / "nested")
    nested.root.mkdir()
    _write_repository_metadata(nested)
    with pytest.raises(HostmarkError, match="not a Git worktree"):
        sync_repository(nested)


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_autocrlf_hostmark_clone_preserves_canonical_repository_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, remote = _create_remote(tmp_path)
    config = tmp_path / "gitconfig"
    config.write_bytes(TEST_GIT_CONFIG_BYTES + b"[core]\n\tautocrlf = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    clone = repository_paths(tmp_path / "autocrlf-clone")

    result = sync_repository(clone, remote=str(remote))

    attributes_data = clone.attributes.read_bytes()
    registry_data = clone.registry.read_bytes()
    assert result.operation == "cloned"
    assert attributes_data == REPOSITORY_ATTRIBUTES_BYTES
    assert b"\r\n" not in attributes_data
    assert registry_data == source.registry.read_bytes()
    assert b"\r\n" not in registry_data
    assert clone.marker.read_bytes() == b""
    validate_repository_metadata(clone)
    registry = read_registry(clone.registry, require_canonical=True).registry
    assert canonical_bytes(registry) == registry_data
    validated = RUNNER.invoke(app, ["registry", "validate", "--registry", str(clone.registry)])
    assert validated.exit_code == 0, validated.output


@pytest.mark.parametrize(
    ("git_error", "expected_message"),
    [
        (
            UnsafeProtocolError("ext::https://user:password@example.com/private.git"),
            "Unsafe Git protocol is not allowed.",
        ),
        (
            UnsafeOptionError("--upload-pack=https://user:password@example.com/helper"),
            "Unsafe Git option is not allowed.",
        ),
    ],
)
def test_unsafe_gitpython_errors_cross_cli_boundary_without_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_error: Exception,
    expected_message: str,
) -> None:
    def reject_clone(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise git_error

    monkeypatch.setattr(Repo, "clone_from", reject_clone)
    result = RUNNER.invoke(
        app,
        [
            "repo",
            "sync",
            "--repo",
            str(tmp_path / "clone"),
            "--remote",
            "ext::https://user:password@example.com/private.git",
        ],
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert expected_message in result.stderr
    assert "Traceback" not in result.output
    assert "UnsafeProtocolError" not in result.output
    assert "UnsafeOptionError" not in result.output
    assert "password" not in result.output
    assert "example.com" not in result.output


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_gitpython_failure_is_sanitized_and_repository_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, remote = _create_remote(tmp_path)
    clone = repository_paths(tmp_path / "clone")
    sync_repository(clone, remote=str(remote))
    closed: list[Path] = []
    original_close = Repo.close

    def record_close(repo: Repo) -> None:
        if repo.working_tree_dir is not None:
            closed.append(Path(repo.working_tree_dir))
        original_close(repo)

    def fail_pull(self: Remote, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        raise GitCommandError(
            ["git", "pull", "https://user:password@example.com/private.git"],
            128,
            stderr="fatal: could not read https://user:password@example.com/private.git",
        )

    monkeypatch.setattr(Repo, "close", record_close)
    monkeypatch.setattr(Remote, "pull", fail_pull)

    with pytest.raises(HostmarkError) as caught:
        sync_repository(clone)

    message = str(caught.value)
    assert "fast-forward" in message
    assert "password" not in message
    assert "git pull" not in message
    assert clone.root in closed

    cli_result = RUNNER.invoke(app, ["repo", "sync", "--repo", str(clone.root)])
    assert cli_result.exit_code == 1
    assert "fast-forward" in cli_result.stderr
    assert "password" not in cli_result.output
    assert "Traceback" not in cli_result.output


@pytest.mark.skipif(shutil.which("git") is None, reason="system Git is required")
def test_post_clone_registry_validation_preserves_registry_exit_code(tmp_path: Path) -> None:
    source, remote = _create_remote(tmp_path)
    source.registry.write_bytes(b"{}\n")
    with Repo(source.root, search_parent_directories=False) as repo:
        _commit(repo, [REPOSITORY_REGISTRY_NAME], "Break registry")
        repo.remotes.origin.push("main")

    with pytest.raises(RegistryValidationError) as caught:
        sync_repository(repository_paths(tmp_path / "clone"), remote=str(remote))

    assert caught.value.exit_code == 8
    assert "Git synchronization completed" in str(caught.value)
    assert "resulting registry is invalid" in str(caught.value)


def _commit(repo: Repo, paths: list[str], message: str) -> None:
    repo.index.add(paths)
    repo.index.commit(message, author=GIT_ACTOR, committer=GIT_ACTOR)


def _create_remote(tmp_path: Path) -> tuple[repository_service.RepositoryPaths, Path]:
    source = repository_paths(tmp_path / "source")
    initialize_repository(source, dns_suffix="node.infra.example.com", sites=["nc1"])
    with Repo(source.root, search_parent_directories=False) as repo:
        _commit(repo, sorted(REQUIRED_PATHS), "Initialize inventory")

    remote = tmp_path / "remote.git"
    with Repo.init(remote, bare=True, initial_branch="main"):
        pass
    with Repo(source.root, search_parent_directories=False) as repo:
        origin = repo.create_remote("origin", str(remote))
        origin.push("main:main", set_upstream=True)
    return source, remote


def _write_repository_metadata(paths: repository_service.RepositoryPaths) -> None:
    paths.attributes.write_bytes(REPOSITORY_ATTRIBUTES_BYTES)
    paths.marker.write_bytes(b"")
    paths.registry.write_bytes(canonical_bytes(new_registry(dns_suffix="node.example.com", sites=["nc1"])))
