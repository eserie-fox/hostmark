from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_artifact_verifier_reads_version_source_dynamically(tmp_path: Path) -> None:
    version_file = tmp_path / "src" / "hostmark" / "version.py"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('__version__ = "9.8.7"\n', encoding="utf-8")
    output = tmp_path / "dist"
    output.mkdir()

    verifier = runpy.run_path(str(ROOT / "scripts" / "verify_artifacts.py"))
    read_project_version = verifier["read_project_version"]
    verify_artifacts = verifier["verify_artifacts"]
    artifact_error = verifier["ArtifactError"]

    assert read_project_version(tmp_path) == "9.8.7"
    with pytest.raises(artifact_error, match=r"hostmark-9\.8\.7-py3-none-any\.whl.*hostmark-9\.8\.7\.tar\.gz"):
        verify_artifacts(output, project_root=tmp_path)
