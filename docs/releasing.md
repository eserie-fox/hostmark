# Releasing

Hostmark releases are built and published to FoxPI by GitHub Actions. Do not publish locally or to public PyPI.

1. Update the single executable version source, `src/hostmark/version.py`, and add the release entry to `CHANGELOG.md`.
   The artifact verifier reads that file with the standard library and derives expected names and metadata from it.
2. Run `make check`, `make build`, and `git diff --check`. Derive `SOURCE_DATE_EPOCH` from the release commit and run
   two clean `uv build --no-sources` builds. `make build` performs the Twine and artifact privacy/metadata checks;
   `scripts/release/compare_artifacts.py` requires identical wheel bytes and identical extracted sdist paths, contents,
   normalized modes, entry types, and symlink targets. Record raw sdist hashes but ignore only container metadata.
3. Inspect wheel and sdist members, then install the wheel in a clean temporary environment. Verify import,
   `hostmark --version`, `python -m hostmark --version`, and root help.
4. If a separate source archive is needed, create it from tracked files, for example with `git archive`, rather than
   archiving a working directory containing `.git`, `.venv`, caches, or `dist`.
5. Merge the exact validated commit to `main` and wait for CI. The intended tag is `v<version>` and must equal `v` plus
   `hostmark.version.__version__`.
6. Later, under separate authorization, create and push the release tag. A tag publication requires its commit to be
   reachable from `origin/main`. The tag is the sole publication authority. The workflow builds once, checks
   privacy/metadata and tag/version equality, uploads one checksummed artifact bundle, and passes those exact files
   without rebuilding to the protected `foxpi-publish` environment.
7. After publication, manually smoke-test a clean install:

   ```bash
   uv tool run --from hostmark==<version> \
     --index https://foxpi.foxenz.com/publisher/prod/+simple/ \
     hostmark --version
   ```

Configure `FOXPI_PUBLISH_USERNAME` and `FOXPI_PUBLISH_PASSWORD` as protected environment secrets. A manual
`workflow_dispatch` must select the current `origin/main` tip, builds and validates downloadable artifacts only, and can
never enter the publish job. Published versions are immutable; if source changes, increment the version. No workflow
creates a public-PyPI upload or GitHub Release automatically.
