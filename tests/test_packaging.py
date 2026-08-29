"""Build, member-inspection, metadata, and installed-wheel smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import venv
from importlib.metadata import entry_points, version
from pathlib import Path

from scripts.verify_artifacts import verify_artifacts

from hostmark.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_is_dynamic_and_console_entry_point_exists() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "hostmark"
    assert metadata["project"]["dynamic"] == ["version"]
    assert "version" not in metadata["project"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "hostmark.version.__version__"}
    assert metadata["project"]["scripts"]["hostmark"] == "hostmark.cli:main"
    assert version("hostmark") == __version__ == "0.1.0"
    assert any(
        point.name == "hostmark" and point.value == "hostmark.cli:main"
        for point in entry_points(group="console_scripts")
    )


def test_build_artifacts_and_install_wheel_in_fresh_environment(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel, sdist = verify_artifacts(output)

    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    console = environment / ("Scripts/hostmark.exe" if os.name == "nt" else "bin/hostmark")
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    imported = subprocess.run(
        [str(python), "-c", "import hostmark; print(hostmark.__file__)"],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    command_version = subprocess.run(
        [str(console), "--version"],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    module_version = subprocess.run(
        [str(python), "-m", "hostmark", "--version"],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    root_help = subprocess.run(
        [str(console)],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert wheel.name == "hostmark-0.1.0-py3-none-any.whl"
    assert sdist.name == "hostmark-0.1.0.tar.gz"
    assert str(ROOT / "src") not in imported.stdout
    assert "site-packages" in imported.stdout
    assert command_version.stdout == "0.1.0\n"
    assert module_version.stdout == "0.1.0\n"
    assert "registry" in root_help.stdout and "identity" in root_help.stdout
