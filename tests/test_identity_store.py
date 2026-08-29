from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

import hostmark.commands.identity as identity_commands
from hostmark.cli import app
from hostmark.domain.errors import (
    HostmarkError,
    IdentityConflictError,
    IdentityNotInitializedError,
    PlatformOperationError,
    PrivilegeRequiredError,
)
from hostmark.services.identity_store import (
    IdentityPaths,
    discover_identity,
    identity_paths,
    initialize_identity,
    maybe_reexec_for_system_scope,
)
from tests.helpers import HOST_A

RUNNER = CliRunner()
FIXED_UUID = UUID(HOST_A)


def local_paths(tmp_path: Path) -> IdentityPaths:
    return IdentityPaths(system=tmp_path / "system" / "host-id", user=tmp_path / "user" / "host-id")


def test_linux_system_user_and_xdg_paths() -> None:
    home = Path("/home/example")
    default = identity_paths(platform_name="linux", environ={}, home=home)
    configured = identity_paths(
        platform_name="linux",
        environ={"XDG_CONFIG_HOME": "/custom/config"},
        home=home,
    )

    assert default.system == Path("/etc/hostmark/host-id")
    assert default.user == Path("/home/example/.config/hostmark/host-id")
    assert configured.user == Path("/custom/config/hostmark/host-id")


def test_relative_xdg_config_home_uses_home_fallback() -> None:
    paths = identity_paths(
        platform_name="linux",
        environ={"XDG_CONFIG_HOME": "relative/config"},
        home=Path("/home/example"),
    )

    assert paths.user == Path("/home/example/.config/hostmark/host-id")


def test_macos_identity_paths() -> None:
    paths = identity_paths(platform_name="darwin", environ={}, home=Path("/Users/example"))

    assert paths.system == Path("/Library/Application Support/Hostmark/host-id")
    assert paths.user == Path("/Users/example/Library/Application Support/Hostmark/host-id")


def test_windows_paths_and_case_insensitive_environment() -> None:
    paths = identity_paths(
        platform_name="win32",
        environ={"ProgramData": "C:/ProgramData", "localappdata": "C:/Users/Fox/AppData/Local"},
        home=Path("C:/Users/Fox"),
    )

    assert paths.system == Path("C:/ProgramData/Hostmark/host-id")
    assert paths.user == Path("C:/Users/Fox/AppData/Local/Hostmark/host-id")


def test_windows_missing_environment_uses_distinct_home_fallbacks() -> None:
    paths = identity_paths(platform_name="win32", environ={}, home=Path("C:/Users/Fox"))

    assert paths.system == Path("C:/Users/Fox/ProgramData/Hostmark/host-id")
    assert paths.user == Path("C:/Users/Fox/AppData/Local/Hostmark/host-id")
    assert paths.system != paths.user


def test_unsupported_platform_uses_reserved_platform_error() -> None:
    with pytest.raises(PlatformOperationError):
        identity_paths(platform_name="plan9", environ={}, home=Path("/home/example"))


def test_discovery_reports_neither_system_only_and_user_only(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)
    with pytest.raises(IdentityNotInitializedError):
        discover_identity(paths)

    paths.system.parent.mkdir(parents=True)
    paths.system.write_bytes(f"{HOST_A}\n".encode("ascii"))
    system = discover_identity(paths)
    assert system.scope == "system"
    assert system.host_id == HOST_A

    paths.system.unlink()
    paths.user.parent.mkdir(parents=True)
    paths.user.write_bytes(f"{HOST_A}\n".encode("ascii"))
    user = discover_identity(paths)
    assert user.scope == "user"
    assert user.path == paths.user


@pytest.mark.parametrize("same_value", [True, False])
def test_both_identity_files_are_always_a_conflict(tmp_path: Path, same_value: bool) -> None:
    paths = local_paths(tmp_path)
    paths.system.parent.mkdir(parents=True)
    paths.user.parent.mkdir(parents=True)
    paths.system.write_bytes(f"{HOST_A}\n".encode("ascii"))
    other = HOST_A if same_value else "2c179ac7-7252-46be-8dc4-0db8d83e5de1"
    paths.user.write_bytes(f"{other}\n".encode("ascii"))

    with pytest.raises(IdentityConflictError, match="both system and user"):
        discover_identity(paths)


@pytest.mark.parametrize(
    "content",
    [
        HOST_A.encode("ascii"),
        f"{HOST_A}\r\n".encode("ascii"),
        b"not-a-uuid\n",
        b"F0C5EBCE-B37E-45D5-9F62-5C5A12F25116\n",
    ],
)
def test_malformed_identity_content_is_rejected(tmp_path: Path, content: bytes) -> None:
    paths = local_paths(tmp_path)
    paths.user.parent.mkdir(parents=True)
    paths.user.write_bytes(content)

    with pytest.raises(HostmarkError, match="identity file"):
        discover_identity(paths)


def test_identity_path_that_is_a_directory_is_not_treated_as_missing(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)
    paths.user.mkdir(parents=True)

    with pytest.raises(HostmarkError) as caught:
        discover_identity(paths)

    message = str(caught.value)
    assert "identity file" in message
    assert str(paths.user) in message
    assert "not initialized" not in message


def test_initialization_is_exclusive_and_durable_across_scopes(tmp_path: Path) -> None:
    paths = local_paths(tmp_path / "user-first")

    created = initialize_identity(
        scope="user",
        paths=paths,
        platform_name="linux",
        is_root=lambda: False,
        uuid_factory=lambda: FIXED_UUID,
    )

    assert created.host_id == HOST_A
    assert created.scope == "user"
    assert paths.user.read_bytes() == f"{HOST_A}\n".encode()
    assert not paths.system.exists()
    with pytest.raises(HostmarkError, match="already initialized"):
        initialize_identity(scope="user", paths=paths, platform_name="linux", is_root=lambda: False)
    with pytest.raises(HostmarkError, match="already initialized"):
        initialize_identity(scope="system", paths=paths, platform_name="linux", is_root=lambda: True)

    system_first = local_paths(tmp_path / "system-first")
    system_first.system.parent.mkdir(parents=True)
    system_first.system.write_bytes(f"{HOST_A}\n".encode("ascii"))
    with pytest.raises(HostmarkError, match="already initialized"):
        initialize_identity(scope="user", paths=system_first, platform_name="linux", is_root=lambda: False)


def test_posix_system_scope_requires_privilege(tmp_path: Path) -> None:
    with pytest.raises(PrivilegeRequiredError, match="requires root"):
        initialize_identity(
            scope="system",
            paths=local_paths(tmp_path),
            platform_name="linux",
            is_root=lambda: False,
        )


def test_windows_permission_error_mentions_elevated_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = local_paths(tmp_path)

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("synthetic denial")

    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(PrivilegeRequiredError, match="elevated Windows terminal"):
        initialize_identity(
            scope="system",
            paths=paths,
            platform_name="win32",
            is_root=lambda: False,
            uuid_factory=lambda: FIXED_UUID,
        )


def test_posix_sudo_reexec_preserves_argv_and_invoking_user_path() -> None:
    calls: list[tuple[str, list[str]]] = []
    argv = ["hostmark", "identity", "init", "--scope", "system", "--sudo", "value with spaces"]
    invoking_user_path = Path("/home/Fox User/.config/hostmark/host-id")

    def fake_exec(file: str, arguments: list[str]) -> object:
        calls.append((file, arguments))
        return object()

    reexecuted = maybe_reexec_for_system_scope(
        scope="system",
        use_sudo=True,
        platform_name="linux",
        is_root=lambda: False,
        argv=argv,
        executable="/venv/bin/python",
        execvp=fake_exec,
        which=lambda command: "/usr/bin/sudo" if command == "sudo" else None,
        invoking_user_identity_path=invoking_user_path,
    )

    assert reexecuted is True
    assert calls == [
        (
            "/usr/bin/sudo",
            [
                "sudo",
                "/venv/bin/python",
                "-m",
                "hostmark",
                *argv[1:],
                "--_invoking-user-identity-path",
                str(invoking_user_path),
            ],
        )
    ]


def test_posix_without_sudo_has_actionable_retry_and_windows_never_executes_sudo() -> None:
    invoking_user_path = Path("/home/example/.config/hostmark/host-id")
    with pytest.raises(PrivilegeRequiredError, match="retry with"):
        maybe_reexec_for_system_scope(
            scope="system",
            use_sudo=False,
            platform_name="linux",
            is_root=lambda: False,
            argv=["hostmark", "identity", "init"],
            invoking_user_identity_path=invoking_user_path,
        )
    with pytest.raises(PrivilegeRequiredError, match="elevated terminal"):
        maybe_reexec_for_system_scope(
            scope="system",
            use_sudo=True,
            platform_name="win32",
            is_root=lambda: False,
            invoking_user_identity_path=invoking_user_path,
        )
    with pytest.raises(HostmarkError, match="only valid with --scope system"):
        maybe_reexec_for_system_scope(
            scope="user",
            use_sudo=True,
            invoking_user_identity_path=invoking_user_path,
        )


def test_missing_sudo_executable_is_a_project_error() -> None:
    with pytest.raises(PrivilegeRequiredError, match="sudo is unavailable"):
        maybe_reexec_for_system_scope(
            scope="system",
            use_sudo=True,
            platform_name="linux",
            is_root=lambda: False,
            argv=["hostmark", "identity", "init", "--sudo"],
            which=lambda command: None,
            invoking_user_identity_path=Path("/home/example/.config/hostmark/host-id"),
        )


def test_existing_user_identity_blocks_sudo_before_reexec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = local_paths(tmp_path)
    paths.user.parent.mkdir(parents=True)
    paths.user.write_bytes(f"{HOST_A}\n".encode("ascii"))
    monkeypatch.setattr(identity_commands, "identity_paths", lambda: paths)

    def unexpected_reexec(**kwargs: object) -> bool:
        raise AssertionError("sudo re-exec must not run")

    monkeypatch.setattr(identity_commands, "maybe_reexec_for_system_scope", unexpected_reexec)
    result = RUNNER.invoke(app, ["identity", "init", "--sudo"])

    assert result.exit_code == 1
    assert "already initialized at user scope" in result.stderr


def test_privileged_recheck_catches_identity_created_after_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = local_paths(tmp_path / "invoking-user")
    privileged_paths = IdentityPaths(system=paths.system, user=tmp_path / "root-user" / "host-id")
    monkeypatch.setattr(identity_commands, "identity_paths", lambda: privileged_paths)

    def create_racing_identity(**kwargs: object) -> bool:
        paths.user.parent.mkdir(parents=True)
        paths.user.write_bytes(f"{HOST_A}\n".encode("ascii"))
        return False

    monkeypatch.setattr(identity_commands, "maybe_reexec_for_system_scope", create_racing_identity)
    result = RUNNER.invoke(
        app,
        ["identity", "init", "--sudo", "--_invoking-user-identity-path", str(paths.user)],
    )

    assert result.exit_code == 1
    assert "already initialized at user scope" in result.stderr
    assert not paths.system.exists()


def test_identity_show_raw_prints_only_uuid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = local_paths(tmp_path)
    paths.user.parent.mkdir(parents=True)
    paths.user.write_bytes(f"{HOST_A}\n".encode("ascii"))
    monkeypatch.setattr(identity_commands, "identity_paths", lambda: paths)

    result = RUNNER.invoke(app, ["identity", "show", "--raw"])

    assert result.exit_code == 0
    assert result.stdout == f"{HOST_A}\n"
