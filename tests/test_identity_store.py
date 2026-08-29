"""Cross-platform local identity path, discovery, creation, and sudo tests."""

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
    sudo_reexec_argv,
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
    with pytest.raises(PlatformOperationError) as exc_info:
        identity_paths(platform_name="plan9", environ={}, home=Path("/home/example"))

    assert exc_info.value.exit_code == 11


def test_discovery_reports_neither_system_only_and_user_only(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)
    with pytest.raises(IdentityNotInitializedError):
        discover_identity(paths)

    paths.system.parent.mkdir(parents=True)
    paths.system.write_text(f"{HOST_A}\n", encoding="ascii", newline="\n")
    system = discover_identity(paths)
    assert system.scope == "system"
    assert system.host_id == HOST_A

    paths.system.unlink()
    paths.user.parent.mkdir(parents=True)
    paths.user.write_text(f"{HOST_A}\n", encoding="ascii", newline="\n")
    user = discover_identity(paths)
    assert user.scope == "user"
    assert user.path == paths.user


@pytest.mark.parametrize("same_value", [True, False])
def test_both_identity_files_are_always_a_conflict(tmp_path: Path, same_value: bool) -> None:
    paths = local_paths(tmp_path)
    paths.system.parent.mkdir(parents=True)
    paths.user.parent.mkdir(parents=True)
    paths.system.write_text(f"{HOST_A}\n", encoding="ascii")
    other = HOST_A if same_value else "2c179ac7-7252-46be-8dc4-0db8d83e5de1"
    paths.user.write_text(f"{other}\n", encoding="ascii")

    with pytest.raises(IdentityConflictError, match="both system and user"):
        discover_identity(paths)


@pytest.mark.parametrize(
    "content",
    [
        HOST_A,
        f"{HOST_A}\r\n",
        f"{HOST_A}\nextra\n",
        "not-a-uuid\n",
        "F0C5EBCE-B37E-45D5-9F62-5C5A12F25116\n",
    ],
)
def test_malformed_identity_content_is_rejected(tmp_path: Path, content: str) -> None:
    paths = local_paths(tmp_path)
    paths.user.parent.mkdir(parents=True)
    paths.user.write_bytes(content.encode())

    with pytest.raises(HostmarkError, match="identity file"):
        discover_identity(paths)


def test_identity_path_that_is_a_directory_is_not_treated_as_missing(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)
    paths.user.mkdir(parents=True)

    with pytest.raises(HostmarkError, match="could not read identity file"):
        discover_identity(paths)


def test_user_scope_initialization_is_exclusive_and_durable(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)

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


def test_initialization_refuses_other_scope_and_same_target_overwrite(tmp_path: Path) -> None:
    paths = local_paths(tmp_path)
    paths.system.parent.mkdir(parents=True)
    paths.system.write_text(f"{HOST_A}\n", encoding="ascii")

    with pytest.raises(HostmarkError, match="already initialized"):
        initialize_identity(scope="user", paths=paths, platform_name="linux", is_root=lambda: True)


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


def test_sudo_argv_preserves_every_argument_without_shell_parsing() -> None:
    argv = [
        "/venv/bin/hostmark",
        "identity",
        "init",
        "--scope",
        "system",
        "--sudo",
        "value with spaces",
    ]

    assert sudo_reexec_argv(argv, executable="/venv/bin/python") == [
        "sudo",
        "/venv/bin/python",
        "-m",
        "hostmark",
        *argv[1:],
    ]


def test_posix_sudo_reexec_uses_argument_array_and_preserves_invocation() -> None:
    calls: list[tuple[str, list[str]]] = []
    argv = ["hostmark", "identity", "init", "--scope", "system", "--sudo", "value with spaces"]

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
    )

    assert reexecuted is True
    assert calls == [("sudo", ["sudo", "/venv/bin/python", "-m", "hostmark", *argv[1:]])]


def test_posix_without_sudo_has_actionable_retry_and_windows_never_executes_sudo() -> None:
    with pytest.raises(PrivilegeRequiredError, match="retry with"):
        maybe_reexec_for_system_scope(
            scope="system",
            use_sudo=False,
            platform_name="linux",
            is_root=lambda: False,
            argv=["hostmark", "identity", "init"],
        )
    with pytest.raises(PrivilegeRequiredError, match="elevated terminal"):
        maybe_reexec_for_system_scope(
            scope="system",
            use_sudo=True,
            platform_name="win32",
            is_root=lambda: False,
        )


def test_identity_show_raw_prints_only_uuid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = local_paths(tmp_path)
    paths.user.parent.mkdir(parents=True)
    paths.user.write_text(f"{HOST_A}\n", encoding="ascii")
    monkeypatch.setattr(identity_commands, "identity_paths", lambda: paths)

    result = RUNNER.invoke(app, ["identity", "show", "--raw"])

    assert result.exit_code == 0
    assert result.stdout == f"{HOST_A}\n"
