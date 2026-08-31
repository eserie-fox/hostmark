# Releasing

Public Hostmark releases are published to PyPI by GitHub Actions using PyPI Trusted Publishing and GitHub OIDC. The
publication job uses the GitHub environment named `pypi`; no PyPI username, password, or API-token secret is stored in
GitHub. Do not publish locally.

## Release checklist

1. Update the single executable version source, `src/hostmark/version.py`, and add the release entry to `CHANGELOG.md`.
   The artifact verifier reads that file with the standard library and derives expected names and metadata from it.
2. Run `make check`, `make build`, and `git diff --check`. Derive `SOURCE_DATE_EPOCH` from the release commit and run
   two clean `uv build --no-sources` builds. `make build` performs the Twine and artifact privacy/metadata checks;
   `scripts/release/compare_artifacts.py` requires identical wheel bytes and identical extracted sdist paths, contents,
   normalized modes, entry types, and symlink targets. Record raw sdist hashes but ignore only container metadata.
3. Inspect wheel and sdist members, then install the wheel in a clean temporary environment. Verify import,
   `hostmark --version`, `python -m hostmark --version`, root help, and `hostmark repo --help`. Neither artifact may
   contain `hosts.json`, a live `HOSTMARK_REPOSITORY` data file, `.git` metadata, or an inventory worktree. Wheel metadata
   must contain `GitPython>=3.1.59,<4` as a runtime requirement.
4. If a separate source archive is needed, create it from tracked files, for example with `git archive`, rather than
   archiving a working directory containing `.git`, `.venv`, caches, or `dist`.
5. Merge the exact validated commit to `main` and wait for CI. The release tag must be `v<version>` and must equal `v`
   plus `hostmark.version.__version__`.
6. Later, under separate authorization, create and push the release tag. Its commit must be reachable from
   `origin/main`. A newly created tag push is the sole publication authority: the workflow verifies the source, derives
   the deterministic build epoch, builds once, runs Twine and artifact privacy/member validation, records SHA-256
   checksums, and uploads one artifact bundle. The `pypi` publication job downloads and verifies that exact bundle and
   publishes it without checking out source or rebuilding.
7. After publication, smoke-test the release from the normal public package index:

   ```bash
   uv tool run --from hostmark==<version> hostmark --version
   ```

   In a separate clean Python environment, also run:

   ```bash
   python -m pip install "hostmark==<version>"
   hostmark --version
   ```

`workflow_dispatch` must target the current `origin/main` tip and produces downloadable validation artifacts only; it
cannot publish. Tag deletion events cannot build or publish. Do not overwrite released files or retry a conflicting
version with `skip-existing`: PyPI files are immutable, and any source change after a release requires a new version.
The workflow does not create a GitHub Release automatically.
