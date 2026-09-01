# Releasing

Public Hostmark releases are published to PyPI by GitHub Actions using PyPI Trusted Publishing
and GitHub OIDC. The publication job uses the GitHub environment named `pypi`; no PyPI username,
password, or API-token secret is used. Do not publish locally.

## Release checklist

1. Update the single executable version source, `src/hostmark/version.py`, and add the release
   entry to `CHANGELOG.md`.
2. Run `make check`, `make build`, and `git diff --check`. `make build` performs the Twine and
   artifact privacy/metadata checks.
3. Inspect wheel and sdist members, then install the wheel in a clean temporary environment.
   Verify import, `hostmark --version`, `python -m hostmark --version`, root help, and
   `hostmark repo --help`. Neither artifact may contain `hosts.json`, a live
   `HOSTMARK_REPOSITORY` data file, `.git` metadata, or an inventory worktree.
4. If a separate source archive is needed, create it from tracked files with `git archive`
   rather than archiving a working directory containing `.git`, `.venv`, caches, or `dist`.
5. Merge the release preparation changes to `main` and wait for normal CI to pass.
6. Create and publish a normal GitHub Release for the intended version tag.
7. The release workflow calls the shared public build workflow once. Its project-local publish
   job downloads the resulting sdist and wheel artifact and sends it to PyPI through OIDC and
   the `pypi` environment, without checking out source or rebuilding.
8. After publication, smoke-test the release from the normal public package index:

   ```bash
   uv tool run --from "hostmark==<version>" hostmark --version
   ```

   In a separate clean Python environment, also run:

   ```bash
   python -m pip install "hostmark==<version>"
   hostmark --version
   ```

Publishing a GitHub Release is the sole automated publication entry point. Tag pushes and manual
dispatches do not invoke package publication. Do not overwrite released files or retry a
conflicting version with `skip-existing`; any source change after a release requires a new
version.
