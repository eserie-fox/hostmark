# Releasing

Public Hostmark releases are published to TestPyPI and PyPI by GitHub Actions using Trusted
Publishing and GitHub OIDC. The publication jobs use the GitHub environments named `testpypi`
and `pypi`; no username, password, or API-token secret is used. Do not publish locally.

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
5. Merge the release preparation changes to `main` and wait for normal CI and the TestPyPI
   publication to pass.
6. Check the TestPyPI package, then create and push the version tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

7. The `v*` tag push builds the package again and publishes it to PyPI through OIDC and the
   `pypi` environment.
8. After publication, smoke-test the release from the normal public package index:

   ```bash
   uv tool run --from "hostmark==<version>" hostmark --version
   ```

   In a separate clean Python environment, also run:

   ```bash
   python -m pip install "hostmark==<version>"
   hostmark --version
   ```

Pushes to `main` and manual workflow runs build and publish to TestPyPI. Tag pushes build and
publish separately to PyPI. Do not overwrite released files or retry a conflicting version with
`skip-existing`; any source change after a release requires a new version.
