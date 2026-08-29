# Development

## Environment and common checks

Hostmark requires Python 3.11 or newer and uses uv:

```bash
uv sync --extra dev
make check
```

Make targets are:

- `sync`: install runtime plus development dependencies;
- `format`: apply Ruff safe fixes and formatting;
- `format-check`: check formatting;
- `lint`: run Ruff lint rules;
- `typecheck`: run mypy over `src` and `tests`;
- `test`: run the deterministic pytest suite;
- `registry-check`: validate and format-check the example and an existing real registry;
- `build`: build, run Twine checks, and inspect distribution privacy/metadata;
- `check`: aggregate all authoritative local gates; and
- `clean`: remove only project-generated caches and build outputs, never registry data.

Run `git diff --check` before committing. Tests never write `/etc`, ProgramData, or `/Library`; platform paths, clock,
UUID generation, hostname reading, and transaction timing are injected at service boundaries.

## Registry fixtures

Only synthetic UUIDs and reserved example domains belong in tests or `registry/hosts.example.json`. Do not copy real host
inventory, production runtime configuration, or credentials into fixtures. The real `registry/hosts.json` is a private
Git source of truth and is intentionally not ignored, but is absent from this bootstrap repository.

The artifact verifier opens both wheel and sdist and rejects the entire `registry/` tree, host inventory names, bytecode,
caches, and machine-local files. The packaging test installs the wheel into a fresh temporary environment and checks both
console and `python -m` version paths.

## CI registry history

CI always validates and format-checks the example. If a real registry exists, it does the same. On pull requests, CI uses
the exact base SHA: deleting an existing base registry fails; an existing candidate is compared with `git show` output in
`$RUNNER_TEMP`; a newly introduced registry receives full snapshot validation. CI never formats or writes registry files.
