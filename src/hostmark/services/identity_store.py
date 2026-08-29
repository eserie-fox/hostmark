"""Cross-platform local host identity discovery and exclusive creation."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from hostmark.domain.errors import (
    HostmarkError,
    IdentityConflictError,
    IdentityNotInitializedError,
    PlatformOperationError,
    PrivilegeRequiredError,
    RegistryValidationError,
)
from hostmark.services.registry_validation import validate_host_id

IdentityScope = Literal["system", "user"]
ExecFunction = Callable[[str, list[str]], object]


@dataclass(frozen=True)
class IdentityPaths:
    """The two fixed identity paths for one platform and environment."""

    system: Path
    user: Path


@dataclass(frozen=True)
class LocalIdentity:
    """A discovered or newly generated local identity."""

    host_id: str
    scope: IdentityScope
    path: Path


def identity_paths(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> IdentityPaths:
    """Resolve fixed system and explicit user-fallback paths without I/O."""

    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if platform_value.startswith("linux"):
        configured_home = environment.get("XDG_CONFIG_HOME")
        user_config = Path(configured_home).expanduser() if configured_home else user_home / ".config"
        return IdentityPaths(
            system=Path("/etc/hostmark/host-id"),
            user=user_config / "hostmark" / "host-id",
        )
    if platform_value == "darwin":
        return IdentityPaths(
            system=Path("/Library/Application Support/Hostmark/host-id"),
            user=user_home / "Library" / "Application Support" / "Hostmark" / "host-id",
        )
    if platform_value in {"win32", "cygwin"}:
        program_data = _windows_environment_value(environment, "PROGRAMDATA")
        local_app_data = _windows_environment_value(environment, "LOCALAPPDATA")
        system_base = Path(program_data) if program_data else user_home / "ProgramData"
        user_base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return IdentityPaths(
            system=system_base / "Hostmark" / "host-id",
            user=user_base / "Hostmark" / "host-id",
        )
    raise PlatformOperationError(f"unsupported platform for local identity storage: {platform_value}")


def _windows_environment_value(environ: Mapping[str, str], key: str) -> str | None:
    for name, value in environ.items():
        if name.upper() == key:
            return value
    return None


def discover_identity(paths: IdentityPaths) -> LocalIdentity:
    """Inspect both identity scopes and fail rather than choosing a duplicate."""

    system_exists = paths.system.exists()
    user_exists = paths.user.exists()
    if system_exists and user_exists:
        raise IdentityConflictError(
            "both system and user identity files exist; remove the unintended duplicate before continuing: "
            f"{paths.system} and {paths.user}"
        )
    if not system_exists and not user_exists:
        raise IdentityNotInitializedError(
            "local identity is not initialized; run 'hostmark identity init' or 'hostmark identity init --scope user'"
        )
    if system_exists:
        return _read_identity(paths.system, "system")
    return _read_identity(paths.user, "user")


def _read_identity(path: Path, scope: IdentityScope) -> LocalIdentity:
    try:
        data = path.read_bytes()
    except PermissionError as exc:
        raise HostmarkError(f"permission denied while reading identity file: {path}") from exc
    except OSError as exc:
        raise HostmarkError(f"could not read identity file {path}: {exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HostmarkError(f"identity file is not valid UTF-8: {path}") from exc
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise HostmarkError(f"identity file must contain exactly one canonical UUIDv4 plus LF: {path}")
    value = text[:-1]
    try:
        validate_host_id(value, field="identity file")
    except RegistryValidationError as exc:
        raise HostmarkError(f"malformed identity file {path}: {exc}") from exc
    return LocalIdentity(host_id=value, scope=scope, path=path)


def initialize_identity(
    *,
    scope: IdentityScope,
    paths: IdentityPaths,
    platform_name: str | None = None,
    is_root: Callable[[], bool] | None = None,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> LocalIdentity:
    """Create exactly one identity file with exclusive creation and durable bytes."""

    platform_value = sys.platform if platform_name is None else platform_name
    _require_supported_platform(platform_value)
    if scope not in {"system", "user"}:
        raise HostmarkError(f"invalid identity scope: {scope!r}")
    system_exists = paths.system.exists()
    user_exists = paths.user.exists()
    if system_exists and user_exists:
        raise IdentityConflictError(
            f"both identity files already exist: {paths.system} and {paths.user}; remove the unintended duplicate"
        )
    if system_exists:
        raise HostmarkError(f"identity is already initialized at system scope: {paths.system}")
    if user_exists:
        raise HostmarkError(f"identity is already initialized at user scope: {paths.user}")

    root_check = _running_as_root if is_root is None else is_root
    if scope == "system" and platform_value != "win32" and not platform_value.startswith("cygwin") and not root_check():
        raise PrivilegeRequiredError(
            "system-scope identity initialization requires root; retry with --sudo or choose --scope user explicitly"
        )
    target = paths.system if scope == "system" else paths.user
    generated = str(uuid_factory())
    try:
        validate_host_id(generated, field="generated host ID")
    except RegistryValidationError as exc:  # Defensive support for injected UUID factories.
        raise HostmarkError(str(exc)) from exc
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            created = True
            handle.write(f"{generated}\n".encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise HostmarkError(f"refusing to overwrite existing identity file: {target}") from exc
    except PermissionError as exc:
        if created:
            _remove_partial_identity(target)
        if scope == "system" and platform_value in {"win32", "cygwin"}:
            raise PrivilegeRequiredError(
                f"cannot write the system identity at {target}; run hostmark from an elevated Windows terminal"
            ) from exc
        if scope == "system":
            raise PrivilegeRequiredError(f"permission denied while creating identity file: {target}") from exc
        raise HostmarkError(f"permission denied while creating user identity file: {target}") from exc
    except OSError as exc:
        if created:
            _remove_partial_identity(target)
        raise HostmarkError(f"could not create identity file {target}: {exc}") from exc
    return LocalIdentity(host_id=generated, scope=scope, path=target)


def _remove_partial_identity(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _running_as_root() -> bool:
    get_effective_user_id = getattr(os, "geteuid", None)
    return bool(get_effective_user_id is not None and get_effective_user_id() == 0)


def _require_supported_platform(platform_name: str) -> None:
    if not (platform_name.startswith("linux") or platform_name == "darwin" or platform_name in {"win32", "cygwin"}):
        raise PlatformOperationError(f"unsupported platform for local identity storage: {platform_name}")


def sudo_reexec_argv(argv: Sequence[str], *, executable: str | None = None) -> list[str]:
    """Reconstruct the complete invocation as an argument array, never a shell string."""

    python = sys.executable if executable is None else executable
    forwarded = list(argv[1:]) if argv else []
    return ["sudo", python, "-m", "hostmark", *forwarded]


def maybe_reexec_for_system_scope(
    *,
    scope: IdentityScope,
    use_sudo: bool,
    platform_name: str | None = None,
    is_root: Callable[[], bool] | None = None,
    argv: Sequence[str] | None = None,
    executable: str | None = None,
    execvp: ExecFunction | None = None,
) -> bool:
    """Re-exec a complete POSIX command through sudo when explicitly requested."""

    if scope != "system":
        if use_sudo:
            raise HostmarkError("--sudo is only valid with --scope system")
        return False
    platform_value = sys.platform if platform_name is None else platform_name
    _require_supported_platform(platform_value)
    if platform_value in {"win32", "cygwin"}:
        if use_sudo:
            raise PrivilegeRequiredError("Unix sudo is unavailable on Windows; rerun from an elevated terminal")
        return False
    root_check = _running_as_root if is_root is None else is_root
    if root_check():
        return False
    invocation = sys.argv if argv is None else argv
    command = sudo_reexec_argv(invocation, executable=executable)
    if not use_sudo:
        raise PrivilegeRequiredError(
            "system-scope identity initialization requires root; retry with: " + shlex.join([*command, "--sudo"])
        )
    executor: ExecFunction = os.execvp if execvp is None else execvp
    executor("sudo", command)
    return True


__all__ = [
    "IdentityPaths",
    "IdentityScope",
    "LocalIdentity",
    "discover_identity",
    "identity_paths",
    "initialize_identity",
    "maybe_reexec_for_system_scope",
    "sudo_reexec_argv",
]
