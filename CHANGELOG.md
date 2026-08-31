# Changelog

All notable changes to hostmark are documented here.

## 0.2.0 - 2026-08-30

- Prepare Hostmark's first public PyPI release.
- Add PyPI Trusted Publishing through GitHub Actions OIDC with a checksummed, build-once artifact handoff.
- Remove private-index publication and installation configuration.
- Document public installation through standard uv, pipx, and pip commands.
- Add zero-byte `HOSTMARK_REPOSITORY` marker discovery with root-level `hosts.json` registries.
- Add stable per-user repository defaults for Linux, macOS, and Windows.
- Add `repo path`, local unborn-main `repo init`, and noninteractive clone/fast-forward `repo sync` commands.
- Require tracked canonical `.gitattributes`, marker, and registry files; pin both the attributes file and registry to LF
  under Windows-style `core.autocrlf=true` checkouts, with local Git regression coverage.
- Require the active branch to track `origin/*` and preserve registry-validation exit code after synchronization.
- Use GitPython 3.1.59+ as a safe object interface over system Git, with explicit repository cleanup and concise handling
  for unsafe protocol or option rejections.
- Preserve direct registry-file overrides while removing implicit `registry/hosts.json` upward discovery.
- Validate canonical registry state after every clone or pull without committing, pushing, or remediating automatically.
- Clarify first-use repository location, machine registration, and manual OS hostname remediation.

## 0.1.0 - 2026-08-29

- Add cross-platform UUIDv4 local identity initialization and discovery.
- Add strict canonical JSON host registry validation and append-only baseline checks.
- Add registration, rename, retirement, inspection, formatting, validation, and hostname drift commands.
- Add optimistic atomic persistence, deterministic tests, documentation, CI, and a protected private-index publication
  workflow.
- Prevent sudo initialization from losing the invoking user's identity path or creating a duplicate identity.
- Report registry filesystem failures without tracebacks and validate complete FQDN and UTF-8 text constraints.
- Enforce registry history on pull requests and direct main pushes, and require publish sources to belong to current main.
- Keep package builds separate from the compact deterministic test and local-check suite.
