# Changelog

All notable changes to hostmark are documented here.

## 0.2.0 - 2026-08-30

- Add zero-byte `HOSTMARK_REPOSITORY` marker discovery with root-level `hosts.json` registries.
- Add stable per-user repository defaults for Linux, macOS, and Windows.
- Add `repo path`, local unborn-main `repo init`, and noninteractive clone/fast-forward `repo sync` commands.
- Preserve direct registry-file overrides while removing implicit `registry/hosts.json` upward discovery.
- Validate canonical registry state after every clone or pull without committing, pushing, or remediating automatically.

## 0.1.0 - 2026-08-29

- Add cross-platform UUIDv4 local identity initialization and discovery.
- Add strict canonical JSON host registry validation and append-only baseline checks.
- Add registration, rename, retirement, inspection, formatting, validation, and hostname drift commands.
- Add optimistic atomic persistence, deterministic tests, documentation, CI, and protected FoxPI publication workflow.
- Prevent sudo initialization from losing the invoking user's identity path or creating a duplicate identity.
- Report registry filesystem failures without tracebacks and validate complete FQDN and UTF-8 text constraints.
- Enforce registry history on pull requests and direct main pushes, and require publish sources to belong to current main.
- Keep package builds separate from the compact deterministic test and local-check suite.
