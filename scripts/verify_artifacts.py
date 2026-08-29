"""Inspect built distributions for metadata and private-registry boundaries."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

EXPECTED_VERSION = "0.1.0"
EXPECTED_ENTRY_POINT = "hostmark = hostmark.cli:main"


class ArtifactError(Exception):
    """A built artifact violates the release privacy or metadata contract."""


def verify_artifacts(directory: Path) -> tuple[Path, Path]:
    """Verify exactly one wheel and sdist and return their paths."""

    wheels = sorted(directory.glob("hostmark-*.whl"))
    sdists = sorted(directory.glob("hostmark-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactError(
            f"expected exactly one hostmark wheel and sdist in {directory}; found {len(wheels)} wheel(s) "
            f"and {len(sdists)} sdist(s)"
        )
    _verify_wheel(wheels[0])
    _verify_sdist(sdists[0])
    return wheels[0], sdists[0]


def _verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        _verify_member_privacy(members, artifact="wheel", forbid_tests=True)
        metadata_names = [name for name in members if name.endswith(".dist-info/METADATA")]
        entry_point_names = [name for name in members if name.endswith(".dist-info/entry_points.txt")]
        if len(metadata_names) != 1 or len(entry_point_names) != 1:
            raise ArtifactError(f"wheel must contain one METADATA and one entry_points.txt: {path.name}")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        entry_points = archive.read(entry_point_names[0]).decode("utf-8")
        if f"Version: {EXPECTED_VERSION}\n" not in metadata:
            raise ArtifactError(f"wheel metadata version is not {EXPECTED_VERSION}: {path.name}")
        if EXPECTED_ENTRY_POINT not in entry_points:
            raise ArtifactError(f"wheel console entry point is missing or incorrect: {path.name}")


def _verify_sdist(path: Path) -> None:
    with tarfile.open(path, mode="r:gz") as archive:
        members = [member.name for member in archive.getmembers()]
        _verify_member_privacy(members, artifact="sdist", forbid_tests=False)
        package_info = [
            name for name in members if len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).name == "PKG-INFO"
        ]
        if len(package_info) != 1:
            raise ArtifactError(f"sdist must contain one top-level PKG-INFO: {path.name}")
        extracted = archive.extractfile(package_info[0])
        if extracted is None:
            raise ArtifactError(f"could not read sdist PKG-INFO: {path.name}")
        metadata = extracted.read().decode("utf-8")
        if f"Version: {EXPECTED_VERSION}\n" not in metadata:
            raise ArtifactError(f"sdist metadata version is not {EXPECTED_VERSION}: {path.name}")


def _verify_member_privacy(members: Iterable[str], *, artifact: str, forbid_tests: bool) -> None:
    for member in members:
        parts = PurePosixPath(member).parts
        lowered = tuple(part.lower() for part in parts)
        if "registry" in lowered:
            raise ArtifactError(f"{artifact} contains forbidden registry data or documentation: {member}")
        if member.endswith((".pyc", ".pyo")) or "__pycache__" in parts:
            raise ArtifactError(f"{artifact} contains Python cache bytecode: {member}")
        if forbid_tests and "tests" in lowered:
            raise ArtifactError(f"wheel contains tests: {member}")
        if any(part.startswith(".env") or part in {"uv.lock", ".DS_Store", "Thumbs.db"} for part in parts):
            raise ArtifactError(f"{artifact} contains a machine-local file: {member}")
        if member.endswith(("hosts.json", "hosts.example.json")):
            raise ArtifactError(f"{artifact} contains host inventory: {member}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    arguments = parser.parse_args()
    try:
        wheel, sdist = verify_artifacts(arguments.directory)
    except ArtifactError as exc:
        parser.exit(1, f"artifact validation failed: {exc}\n")
    print(f"Artifact privacy and metadata checks passed: {wheel.name}, {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ArtifactError", "verify_artifacts"]
