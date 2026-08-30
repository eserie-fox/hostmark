from __future__ import annotations

import os
import posixpath
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hostmark.domain.errors import HostmarkError

REPOSITORY_MARKER_NAME = "HOSTMARK_REPOSITORY"
REPOSITORY_REGISTRY_NAME = "hosts.json"
REPOSITORY_ENV = "HOSTMARK_REPO"

_URL_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


@dataclass(frozen=True)
class RepositoryPaths:
    root: Path
    marker: Path
    registry: Path


@dataclass(frozen=True)
class RepositoryInitResult:
    paths: RepositoryPaths
    branch: str


@dataclass(frozen=True)
class RepositorySyncResult:
    paths: RepositoryPaths
    operation: Literal["cloned", "updated"]


def repository_paths(root: Path) -> RepositoryPaths:
    return RepositoryPaths(
        root=root,
        marker=root / REPOSITORY_MARKER_NAME,
        registry=root / REPOSITORY_REGISTRY_NAME,
    )


def default_repository_root(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if platform_value.startswith("linux"):
        configured_home = environment.get("XDG_DATA_HOME")
        data_home = (
            Path(configured_home)
            if configured_home and posixpath.isabs(configured_home)
            else user_home / ".local" / "share"
        )
        return data_home / "hostmark" / "repo"
    if platform_value == "darwin":
        return user_home / "Library" / "Application Support" / "Hostmark" / "repo"
    if platform_value in {"win32", "cygwin"}:
        local_app_data = _windows_environment_value(environment, "LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / "Hostmark" / "repo"
    raise HostmarkError(f"unsupported platform for Hostmark repository storage: {platform_value}")


def resolve_repository_paths(
    explicit: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> RepositoryPaths:
    environment = os.environ if environ is None else environ
    working_directory = Path.cwd() if cwd is None else cwd
    if explicit is not None:
        return repository_paths(_absolute_path(explicit, working_directory))
    configured = environment.get(REPOSITORY_ENV)
    if configured:
        return repository_paths(_absolute_path(Path(configured), working_directory))
    discovered = discover_repository_root(working_directory)
    if discovered is not None:
        return repository_paths(discovered)
    return repository_paths(
        default_repository_root(
            platform_name=platform_name,
            environ=environment,
            home=home,
        )
    )


def discover_repository_root(cwd: Path) -> Path | None:
    current = cwd.expanduser().resolve()
    for candidate in (current, *current.parents):
        marker = candidate / REPOSITORY_MARKER_NAME
        try:
            marker_present = marker.exists() or marker.is_symlink()
        except OSError as exc:
            raise HostmarkError(f"could not inspect Hostmark repository marker {marker}: {exc}") from exc
        if marker_present:
            paths = repository_paths(candidate)
            validate_repository_marker(paths)
            return candidate
    return None


def validate_repository_marker(paths: RepositoryPaths) -> None:
    if not paths.root.is_dir():
        raise HostmarkError(f"Hostmark repository path is not a directory: {paths.root}")
    try:
        if not paths.marker.is_file():
            raise HostmarkError(f"Hostmark repository marker is missing or not a regular file: {paths.marker}")
        data = paths.marker.read_bytes()
    except PermissionError as exc:
        raise HostmarkError(f"permission denied while reading Hostmark repository marker: {paths.marker}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not read Hostmark repository marker {paths.marker}: {exc}") from exc
    if data:
        raise HostmarkError(f"Hostmark repository marker must be exactly zero bytes: {paths.marker}")


def require_initialized_repository(paths: RepositoryPaths) -> None:
    if not paths.root.exists():
        raise HostmarkError(
            f"Hostmark repository is not initialized at {paths.root}; run "
            "'hostmark repo init --dns-suffix <node-suffix> --site <site>' or "
            "'hostmark repo sync --remote <git-url>'"
        )
    validate_repository_marker(paths)


def initialize_repository(
    paths: RepositoryPaths,
    *,
    dns_suffix: str,
    sites: Sequence[str],
) -> RepositoryInitResult:
    from hostmark.services.registry_store import initialize_registry, new_registry, read_registry

    registry = new_registry(dns_suffix=dns_suffix, sites=sites)
    _require_git()
    target_existed = paths.root.exists()
    _require_empty_target(paths.root, operation="initialize")
    try:
        paths.root.parent.mkdir(parents=True, exist_ok=True)
        if not target_existed:
            paths.root.mkdir()
    except OSError as exc:
        raise HostmarkError(f"could not create Hostmark repository directory {paths.root}: {exc}") from exc
    _require_empty_target(paths.root, operation="initialize")

    _run_git(
        ["init", "--initial-branch=main", str(paths.root)],
        action=f"initialize Git repository at {paths.root}",
    )
    _create_marker(paths.marker)
    initialize_registry(paths.registry, registry)
    validate_repository_marker(paths)
    read_registry(paths.registry, require_canonical=True)
    branch = _run_git(
        ["symbolic-ref", "--short", "HEAD"],
        cwd=paths.root,
        action=f"read current Git branch at {paths.root}",
    )
    if branch != "main":
        raise HostmarkError(f"initialized Git repository has unexpected branch {branch!r}: {paths.root}")
    return RepositoryInitResult(paths=paths, branch=branch)


def sync_repository(paths: RepositoryPaths, *, remote: str | None = None) -> RepositorySyncResult:
    root_exists = paths.root.exists()
    if root_exists and not paths.root.is_dir():
        raise HostmarkError(f"Hostmark repository path exists but is not a directory: {paths.root}")
    target_empty = root_exists and _directory_is_empty(paths.root)
    if not root_exists or target_empty:
        if remote is None or not remote.strip():
            raise HostmarkError(
                f"Hostmark repository is not initialized at {paths.root}. Run "
                "'hostmark repo sync --remote <git-url>' to clone one, or "
                "'hostmark repo init --dns-suffix <node-suffix> --site <site>' to create one."
            )
        _require_git()
        try:
            paths.root.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HostmarkError(f"could not create repository parent directory {paths.root.parent}: {exc}") from exc
        _run_git(
            ["clone", remote, str(paths.root)],
            remote_url=remote,
            action=f"clone Hostmark repository into {paths.root}",
        )
        _validate_after_sync(paths)
        return RepositorySyncResult(paths=paths, operation="cloned")

    validate_repository_marker(paths)
    _require_git()
    _require_git_worktree_root(paths.root)
    branch = _current_branch(paths.root)
    _require_upstream(paths.root, branch)
    origin = _origin_url(paths.root)
    if remote is not None and remote != origin:
        raise HostmarkError(f"supplied --remote does not match the configured origin for {paths.root}")
    tracked_status = _run_git(
        ["status", "--porcelain=v1", "--untracked-files=no"],
        cwd=paths.root,
        action=f"inspect tracked Git status at {paths.root}",
    )
    if tracked_status:
        raise HostmarkError(f"tracked changes must be committed or discarded before repository sync: {paths.root}")
    _run_git(
        ["pull", "--ff-only"],
        cwd=paths.root,
        remote_url=origin,
        action=f"fast-forward Hostmark repository at {paths.root}",
    )
    _validate_after_sync(paths)
    return RepositorySyncResult(paths=paths, operation="updated")


def _absolute_path(path: Path, cwd: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = cwd / expanded
    return expanded.resolve(strict=False)


def _windows_environment_value(environ: Mapping[str, str], key: str) -> str | None:
    for name, value in environ.items():
        if name.upper() == key:
            return value
    return None


def _require_empty_target(path: Path, *, operation: str) -> None:
    if not path.exists():
        return
    if not path.is_dir():
        raise HostmarkError(f"cannot {operation} Hostmark repository because the target is not a directory: {path}")
    if not _directory_is_empty(path):
        raise HostmarkError(f"cannot {operation} Hostmark repository because the target is not empty: {path}")


def _directory_is_empty(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError as exc:
        raise HostmarkError(f"could not inspect repository directory {path}: {exc}") from exc
    return False


def _create_marker(path: Path) -> None:
    try:
        with path.open("xb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise HostmarkError(f"refusing to overwrite Hostmark repository marker: {path}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not create Hostmark repository marker {path}: {exc}") from exc


def _require_git() -> str:
    git = shutil.which("git")
    if git is None:
        raise HostmarkError("git is not available in PATH")
    return git


def _git_environment(remote_url: str | None) -> dict[str, str]:
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
    }
    if remote_url is not None and (remote_url.startswith("git@") or remote_url.startswith("ssh://")):
        environment["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    return environment


def _run_git(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    remote_url: str | None = None,
    action: str,
) -> str:
    git = _require_git()
    try:
        process = subprocess.run(
            [git, *arguments],
            cwd=cwd,
            env=_git_environment(remote_url),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HostmarkError(f"could not {action}: {exc}") from exc
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "unknown Git error"
        raise HostmarkError(f"could not {action}: {_redact_url_userinfo(message)}")
    return process.stdout.strip()


def _require_git_worktree_root(root: Path) -> None:
    try:
        top_level = _run_git(
            ["rev-parse", "--show-toplevel"],
            cwd=root,
            action=f"locate Git worktree root for {root}",
        )
    except HostmarkError as exc:
        raise HostmarkError(f"path is not a Git worktree: {root}") from exc
    if Path(top_level).resolve(strict=False) != root.resolve(strict=False):
        raise HostmarkError(f"Git top-level root {top_level} does not match Hostmark repository root {root}")


def _current_branch(root: Path) -> str:
    try:
        return _run_git(
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=root,
            action=f"read current Git branch at {root}",
        )
    except HostmarkError as exc:
        raise HostmarkError(f"Hostmark repository is on a detached HEAD: {root}") from exc


def _require_upstream(root: Path, branch: str) -> None:
    try:
        _run_git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd=root,
            action=f"read upstream for branch {branch} at {root}",
        )
    except HostmarkError as exc:
        raise HostmarkError(f"current branch {branch!r} has no upstream at {root}") from exc


def _origin_url(root: Path) -> str:
    try:
        return _run_git(
            ["remote", "get-url", "origin"],
            cwd=root,
            action=f"read origin remote at {root}",
        )
    except HostmarkError as exc:
        raise HostmarkError(f"Hostmark repository has no origin remote: {root}") from exc


def _validate_after_sync(paths: RepositoryPaths) -> None:
    from hostmark.services.registry_store import read_registry

    try:
        validate_repository_marker(paths)
        read_registry(paths.registry, require_canonical=True)
    except HostmarkError as exc:
        raise HostmarkError(
            f"Git synchronization completed, but the resulting Hostmark repository is invalid at {paths.root}: {exc}"
        ) from exc


def _redact_url_userinfo(message: str) -> str:
    return _URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}<redacted>@", message)


__all__ = [
    "REPOSITORY_ENV",
    "REPOSITORY_MARKER_NAME",
    "REPOSITORY_REGISTRY_NAME",
    "RepositoryInitResult",
    "RepositoryPaths",
    "RepositorySyncResult",
    "default_repository_root",
    "discover_repository_root",
    "initialize_repository",
    "repository_paths",
    "require_initialized_repository",
    "resolve_repository_paths",
    "sync_repository",
    "validate_repository_marker",
]
