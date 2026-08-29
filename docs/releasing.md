# Releasing

Hostmark releases are built and published to FoxPI by GitHub Actions. Do not publish locally or to public PyPI.

1. Update the single version in `src/hostmark/version.py` and add the release entry to `CHANGELOG.md`.
2. Run `make check`, `git diff --check`, `uv build`, and `uvx twine check dist/*`.
3. Run `uv run python scripts/verify_artifacts.py dist`, inspect wheel and sdist members, and install the wheel in a clean
   temporary environment. Verify import, `hostmark --version`, `python -m hostmark --version`, and command help.
4. Merge the exact validated commit to `main` and wait for CI. The intended tag must equal `v` plus
   `hostmark.version.__version__`; version `0.1.0` requires `v0.1.0`.
5. Later, under separate authorization, create and push the release tag. The tag-triggered workflow verifies equality,
   builds once, checks privacy/metadata, uploads the exact artifact, and passes it without rebuilding to the protected
   `foxpi-publish` environment.
6. After publication, manually smoke-test a clean install:

   ```bash
   uv tool run --from hostmark==<version> \
     --index https://foxpi.foxenz.com/publisher/prod/+simple/ \
     hostmark --version
   ```

Configure `FOXPI_PUBLISH_USERNAME` and `FOXPI_PUBLISH_PASSWORD` as protected environment secrets. A manual
`workflow_dispatch` is for controlled recovery and does not replace tag/version review. Published versions are immutable;
if source changes, increment the version. No workflow creates a public-PyPI upload or GitHub Release automatically.
