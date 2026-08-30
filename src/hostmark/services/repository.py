from __future__ import annotations

import os
import posixpath
import re
import shutil
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hostmark.domain.errors import HostmarkError, RegistryValidationError

if TYPE_CHECKING:
    from git import Repo
    from git.exc import GitCommandError
    from git.remote import Remote

REPOSITORY_ATTRIBUTES_NAME = ".gitattributes"
REPOSITORY_ATTRIBUTES_BYTES = b"/.gitattributes text eol=lf\n/HOSTMARK_REPOSITORY -text\n/hosts.json text eol=lf\n"
REPOSITORY_MARKER_NAME = "HOSTMARK_REPOSITORY"
REPOSITORY_REGISTRY_NAME = "hosts.json"
REPOSITORY_ENV = "HOSTMARK_REPO"
REQUIRED_REPOSITORY_PATHS = frozenset(
    {
        REPOSITORY_ATTRIBUTES_NAME,
        REPOSITORY_MARKER_NAME,
        REPOSITORY_REGISTRY_NAME,
    }
)

_URL_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


@dataclass(frozen=True)
class RepositoryPaths:
    root: Path
    attributes: Path
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
        attributes=root / REPOSITORY_ATTRIBUTES_NAME,
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
    data = _read_required_file(paths.root, paths.marker, label="Hostmark repository marker")
    if data:
        raise HostmarkError(f"Hostmark repository marker must be exactly zero bytes: {paths.marker}")


def validate_repository_attributes(paths: RepositoryPaths) -> None:
    data = _read_required_file(paths.root, paths.attributes, label="Hostmark repository attributes file")
    if data != REPOSITORY_ATTRIBUTES_BYTES:
        raise HostmarkError(f"Hostmark repository attributes file is not canonical: {paths.attributes}")


def validate_repository_metadata(paths: RepositoryPaths) -> None:
    validate_repository_attributes(paths)
    validate_repository_marker(paths)


def require_initialized_repository(paths: RepositoryPaths) -> None:
    if not paths.root.exists():
        raise HostmarkError(
            f"Hostmark repository is not initialized at {paths.root}; run "
            "'hostmark repo init --dns-suffix <node-suffix> --site <site>' or "
            "'hostmark repo sync --remote <git-url>'"
        )
    validate_repository_metadata(paths)


def initialize_repository(
    paths: RepositoryPaths,
    *,
    dns_suffix: str,
    sites: Sequence[str],
) -> RepositoryInitResult:
    from hostmark.services.registry_store import initialize_registry, new_registry, read_registry

    registry = new_registry(dns_suffix=dns_suffix, sites=sites)
    _require_git()
    _require_empty_target(paths.root, operation="initialize")
    try:
        paths.root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HostmarkError(f"could not create Hostmark repository parent {paths.root.parent}: {exc}") from exc

    from git import Repo

    with _translate_git_failures(f"initialize Git repository at {paths.root}"):
        repo = Repo.init(paths.root, initial_branch="main")
        try:
            branch = _verify_initialized_repository(repo, paths.root)
        finally:
            repo.close()

    _create_exact_file(
        paths.attributes,
        REPOSITORY_ATTRIBUTES_BYTES,
        label="Hostmark repository attributes file",
    )
    _create_exact_file(paths.marker, b"", label="Hostmark repository marker")
    initialize_registry(paths.registry, registry)
    validate_repository_metadata(paths)
    read_registry(paths.registry, require_canonical=True)
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
        _clone_repository(paths, remote)
        return RepositorySyncResult(paths=paths, operation="cloned")

    validate_repository_metadata(paths)
    with _open_exact_repository(paths.root) as repo:
        _require_tracked_repository_files(repo, paths.root)
        remote_branch, origin = _origin_tracking(repo, paths.root)
        origin_url = _origin_url(origin, paths.root)
        if remote is not None and remote != origin_url:
            raise HostmarkError(f"supplied --remote does not match the configured origin for {paths.root}")
        with _translate_git_failures(f"inspect tracked Git status at {paths.root}"):
            dirty = repo.is_dirty(
                index=True,
                working_tree=True,
                untracked_files=False,
                submodules=False,
            )
        if dirty:
            raise HostmarkError(f"tracked changes must be committed or discarded before repository sync: {paths.root}")
        with _translate_git_failures(f"fast-forward Hostmark repository at {paths.root}"):
            with repo.git.custom_environment(**_git_environment(origin_url)):
                origin.pull(
                    remote_branch,
                    ff_only=True,
                    allow_unsafe_protocols=False,
                    allow_unsafe_options=False,
                )
        _validate_after_sync(paths, repo)
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


def _read_required_file(root: Path, path: Path, *, label: str) -> bytes:
    if not root.is_dir():
        raise HostmarkError(f"Hostmark repository path is not a directory: {root}")
    try:
        if not path.is_file():
            raise HostmarkError(f"{label} is missing or not a regular file: {path}")
        return path.read_bytes()
    except PermissionError as exc:
        raise HostmarkError(f"permission denied while reading {label.lower()}: {path}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not read {label.lower()} {path}: {exc}") from exc


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


def _create_exact_file(path: Path, data: bytes, *, label: str) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise HostmarkError(f"refusing to overwrite {label.lower()}: {path}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not create {label.lower()} {path}: {exc}") from exc


def _require_git() -> None:
    if shutil.which("git") is None:
        raise HostmarkError("git is not available in PATH")


def _git_environment(remote_url: str | None) -> dict[str, str]:
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
    }
    if remote_url is not None and (remote_url.startswith("git@") or remote_url.startswith("ssh://")):
        environment["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    return environment


def _clone_repository(paths: RepositoryPaths, remote_url: str) -> None:
    _require_git()
    try:
        paths.root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HostmarkError(f"could not create repository parent directory {paths.root.parent}: {exc}") from exc

    from git import Repo

    with _translate_git_failures(f"clone Hostmark repository into {paths.root}"):
        repo = Repo.clone_from(
            remote_url,
            paths.root,
            env=_git_environment(remote_url),
            allow_unsafe_protocols=False,
            allow_unsafe_options=False,
        )
        try:
            _verify_worktree_root(repo, paths.root)
            origin = _require_origin(repo, paths.root)
            if _origin_url(origin, paths.root) != remote_url:
                raise HostmarkError(f"cloned repository origin does not match the requested remote: {paths.root}")
            _validate_after_sync(paths, repo)
        finally:
            repo.close()


@contextmanager
def _open_exact_repository(root: Path) -> Iterator[Repo]:
    _require_git()
    from git import Repo
    from git.exc import InvalidGitRepositoryError, NoSuchPathError

    with _translate_git_failures(f"open Git worktree at {root}"):
        try:
            repo = Repo(root, search_parent_directories=False)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise HostmarkError(f"path is not a Git worktree: {root}") from exc
    try:
        with _translate_git_failures(f"inspect Git worktree at {root}"):
            _verify_worktree_root(repo, root)
        yield repo
    finally:
        with _translate_git_failures(f"close Git repository at {root}"):
            repo.close()


def _verify_worktree_root(repo: Repo, root: Path) -> None:
    if repo.bare or repo.working_tree_dir is None:
        raise HostmarkError(f"path is not a non-bare Git worktree: {root}")
    actual = Path(repo.working_tree_dir).resolve(strict=False)
    expected = root.resolve(strict=False)
    if actual != expected:
        raise HostmarkError(f"Git top-level root {actual} does not match Hostmark repository root {expected}")


def _verify_initialized_repository(repo: Repo, root: Path) -> str:
    _verify_worktree_root(repo, root)
    if repo.head.is_detached:
        raise HostmarkError(f"initialized Git repository has a detached HEAD: {root}")
    branch = repo.active_branch.name
    if branch != "main":
        raise HostmarkError(f"initialized Git repository has unexpected branch {branch!r}: {root}")
    if repo.head.is_valid():
        raise HostmarkError(f"initialized Git repository unexpectedly contains a commit: {root}")
    if repo.index.entries:
        raise HostmarkError(f"initialized Git repository unexpectedly contains staged files: {root}")
    if list(repo.remotes):
        raise HostmarkError(f"initialized Git repository unexpectedly contains a remote: {root}")
    return branch


def _origin_tracking(repo: Repo, root: Path) -> tuple[str, Remote]:
    with _translate_git_failures(f"inspect current Git branch at {root}"):
        if repo.head.is_detached:
            raise HostmarkError(f"Hostmark repository is on a detached HEAD: {root}")
        branch = repo.active_branch
        origin = _require_origin(repo, root)
        tracking = branch.tracking_branch()
        if tracking is None:
            raise HostmarkError(f"current branch {branch.name!r} has no upstream at {root}")
        if tracking.remote_name != "origin":
            raise HostmarkError(
                f"current branch tracks {tracking.name}, but Hostmark repository sync requires an origin/* upstream"
            )
        remote_branch = tracking.remote_head
        if not remote_branch:
            raise HostmarkError(f"current branch {branch.name!r} has an invalid origin upstream at {root}")
    return remote_branch, origin


def _require_origin(repo: Repo, root: Path) -> Remote:
    for remote in repo.remotes:
        if remote.name == "origin":
            return remote
    raise HostmarkError(f"Hostmark repository has no origin remote: {root}")


def _origin_url(origin: Remote, root: Path) -> str:
    with _translate_git_failures(f"read origin remote at {root}"):
        return origin.url


def _require_tracked_repository_files(repo: Repo, root: Path) -> None:
    tracked = {os.fspath(path).replace("\\", "/") for (path, stage) in repo.index.entries if stage == 0}
    missing = sorted(REQUIRED_REPOSITORY_PATHS - tracked)
    if missing:
        joined = ", ".join(missing)
        raise HostmarkError(f"required Hostmark repository files are not tracked at {root}: {joined}")


def _validate_after_sync(paths: RepositoryPaths, repo: Repo) -> None:
    from hostmark.services.registry_store import read_registry

    try:
        validate_repository_metadata(paths)
        _require_tracked_repository_files(repo, paths.root)
        read_registry(paths.registry, require_canonical=True)
    except RegistryValidationError as exc:
        raise RegistryValidationError(
            f"Git synchronization completed, but the resulting registry is invalid at {paths.registry}: {exc}"
        ) from exc
    except HostmarkError as exc:
        raise HostmarkError(
            f"Git synchronization completed, but the resulting Hostmark repository is invalid at {paths.root}: {exc}"
        ) from exc


@contextmanager
def _translate_git_failures(action: str) -> Iterator[None]:
    from git.exc import (
        GitCommandError,
        GitCommandNotFound,
        InvalidGitRepositoryError,
        NoSuchPathError,
        UnsafeOptionError,
        UnsafeProtocolError,
    )

    try:
        yield
    except GitCommandNotFound as exc:
        raise HostmarkError("git is not available in PATH") from exc
    except GitCommandError as exc:
        raise HostmarkError(f"could not {action}: {_git_command_message(exc)}") from exc
    except UnsafeProtocolError as exc:
        raise HostmarkError("Unsafe Git protocol is not allowed.") from exc
    except UnsafeOptionError as exc:
        raise HostmarkError("Unsafe Git option is not allowed.") from exc
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise HostmarkError(f"could not {action}: invalid Git repository or path") from exc
    except OSError as exc:
        raise HostmarkError(f"could not {action}: {exc}") from exc


def _git_command_message(exc: GitCommandError) -> str:
    message = _git_output(exc.stderr) or _git_output(exc.stdout) or "unknown Git error"
    return _redact_url_userinfo(message)


def _git_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return value.strip() if value else ""


def _redact_url_userinfo(message: str) -> str:
    return _URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}<redacted>@", message)


__all__ = [
    "REPOSITORY_ATTRIBUTES_BYTES",
    "REPOSITORY_ATTRIBUTES_NAME",
    "REPOSITORY_ENV",
    "REPOSITORY_MARKER_NAME",
    "REPOSITORY_REGISTRY_NAME",
    "REQUIRED_REPOSITORY_PATHS",
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
    "validate_repository_attributes",
    "validate_repository_marker",
    "validate_repository_metadata",
]
