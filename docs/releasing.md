# Releasing

Public Hostmark releases are published to PyPI by GitHub Actions using PyPI Trusted Publishing and GitHub OIDC. The
publication job uses the GitHub environment named `pypi`; no PyPI username, password, or API-token secret is stored in
GitHub. Do not publish locally.

## Release checklist

1. Update the single executable version source, `src/hostmark/version.py`, and add the release entry to `CHANGELOG.md`.
   The artifact verifier reads that file with the standard library and derives expected names and metadata from it.
2. Run `make check`, `make build`, and `git diff --check`. `make build` performs the Twine and artifact
   privacy/metadata checks.
3. Inspect wheel and sdist members, then install the wheel in a clean temporary environment. Verify import,
   `hostmark --version`, `python -m hostmark --version`, root help, and `hostmark repo --help`. Neither artifact may
   contain `hosts.json`, a live `HOSTMARK_REPOSITORY` data file, `.git` metadata, or an inventory worktree. Wheel metadata
   must contain `GitPython>=3.1.59,<4` as a runtime requirement.
4. If a separate source archive is needed, create it from tracked files, for example with `git archive`, rather than
   archiving a working directory containing `.git`, `.venv`, caches, or `dist`.
5. Merge the release changes to `main`, wait for normal main CI to pass, and identify the intended main commit. Confirm
   that `hostmark.version.__version__` contains the version being released.
6. Later, under separate authorization, create the exact annotated `v<version>` tag from that intended main commit and
   push only that tag. The tag must equal `v` plus `hostmark.version.__version__`.
7. The tag workflow verifies tag/version equality, builds the wheel and sdist once, runs Twine and Hostmark's artifact
   privacy checks, records SHA-256 hashes, and uploads one artifact bundle. The `pypi` publication job downloads and
   verifies that exact bundle, then publishes it through PyPI Trusted Publishing with GitHub OIDC and environment
   `pypi`, without checking out source or rebuilding.
8. After publication, smoke-test the release from the normal public package index:

   ```bash
   uv tool run --from "hostmark==<version>" hostmark --version
   ```

   In a separate clean Python environment, also run:

   ```bash
   python -m pip install "hostmark==<version>"
   hostmark --version
   ```

`workflow_dispatch` builds downloadable artifacts for inspection but cannot publish. Tag deletion events cannot build or
publish. Do not overwrite released files or retry a conflicting version with `skip-existing`: PyPI files are immutable,
and any source change after a release requires a new version. The workflow does not create a GitHub Release
automatically.
