# Development

## Environment and common checks

Hostmark requires Python 3.11 or newer and uses uv:

```bash
uv sync --locked --python 3.11 --extra dev
make check
```

Make targets are:

- `sync`: install runtime plus development dependencies;
- `format`: apply Ruff safe fixes and formatting;
- `format-check`: check formatting;
- `lint`: run Ruff lint rules;
- `typecheck`: run mypy over `src` and `tests`;
- `test`: run the deterministic pytest suite;
- `registry-check`: canonically validate the example and an existing real registry once;
- `build`: build, run Twine checks, and inspect distribution privacy/metadata;
- `check`: aggregate formatting, lint, typing, tests, and registry validation without building packages; and
- `clean`: remove only project-generated caches and build outputs, never registry data.

Run both `make check` and `make build` for release validation, and run `git diff --check` before committing. Normal pytest
runs do not build a wheel or create a nested virtual environment; the explicit local build target owns the additional
artifact checks. Tests never write `/etc`, ProgramData, or `/Library`; platform paths, clock, UUID generation, hostname reading,
transaction timing are injected at service boundaries. Repository integration tests use GitPython with temporary local
bare Git repositories only, explicit test actors, an isolated temporary Git configuration, and no network access. One
test adds `core.autocrlf=true` to that temporary configuration; tests never read or change the user's global Git
configuration.

## Registry fixtures

Only synthetic UUIDs and reserved example domains belong in tests or `registry/hosts.example.json`. Do not copy real host
inventory, production runtime configuration, remotes, or credentials into fixtures. Tests create marked inventory
repositories only under pytest temporary directories. The source checkout must not contain root `HOSTMARK_REPOSITORY` or
`hosts.json`; a real inventory belongs in its separate private repository.

The artifact verifier reads the expected version directly from `src/hostmark/version.py`, checks the GitPython runtime
constraint, then opens both wheel and sdist and rejects the entire `registry/` tree, host inventory names, a live
repository marker, bytecode, caches, and machine-local files.

Expected registry filesystem failures—including parent, temporary-file, write/sync, creation, replacement, and
concurrency re-read failures—cross the CLI boundary as concise project errors. Tests exercise representative failures
and require temporary cleanup and preservation of an unreplaced original.

## CI scope

Shared CI runs the same Ubuntu/Python 3.11 contract as the other public projects: Ruff formatting,
Ruff lint, and pytest using the committed lockfile. The additional mypy, registry-history,
cross-platform, package-install, and CLI smoke checks remain available as focused local checks;
they are not duplicated as required CI jobs.

Repository path tests inject platform, environment, home, and working-directory inputs. System-Git/GitPython integration
tests are limited to local init/clone/fast-forward and linked-worktree flows and skip only when Git is unavailable.
