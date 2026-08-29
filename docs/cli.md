# CLI reference

Running `hostmark` shows help and succeeds. `hostmark --version` prints only the version. Every registry-related command
and `check` accepts `--registry PATH` / `-r PATH`. Resolution is explicit option, `HOSTMARK_REGISTRY`, upward search for
`registry/hosts.json`, then—only for `registry init`—`./registry/hosts.json`.

## Identity commands

- `identity init [--scope system|user] [--sudo]` creates one UUIDv4 without overwrite. Default scope is system. `--sudo`
  is POSIX system-scope only. Output includes UUID, scope, path, and a registration example.
- `identity show [--raw]` discovers exactly one identity. Default output includes UUID, scope, and path; `--raw` prints
  only the UUID.

## Registry commands

- `registry init --dns-suffix SUFFIX --site SITE... [-r PATH]` creates a canonical empty file and refuses overwrite.
- `registry register HOSTNAME [-r PATH] [--host-id UUID] [--notes TEXT] [--dry-run]` adds an active record. Without
  `--host-id`, it discovers the local identity. It does not change the OS hostname.
- `registry rename HOST NEW_HOSTNAME [-r PATH] [--dry-run]` selects by current hostname or UUID, never a historical name.
  It requires an active record, reserves the old name in history, and does not change the OS hostname.
- `registry retire HOST --reason TEXT [--replacement HOST] [-r PATH] [--dry-run]` terminally retires an active record.
  A replacement selector is a current hostname or UUID and must identify another active record.
- `registry list [-r PATH] [--status active|retired] [--site SITE]` prints canonical hostname order with status, UUID,
  computed FQDN, and replacement hostname.
- `registry show HOST [-r PATH]` shows all stored fields, computed FQDN, resolved replacement, and reverse replacements.
- `registry format [-r PATH] [--check]` strictly parses and semantically validates before representation changes.
  `--check` never writes and exits 8 when bytes are not canonical.
- `registry validate [-r PATH] [--against BASELINE]` requires a canonical candidate. With a baseline it enforces
  append-only identity/name/lifecycle history and summarizes accepted changes plus DNS suffix warnings. It never writes.

All mutation commands share the same transaction path. `--dry-run` performs the full transition and validation, prints
an LF-only unified diff, does not write, and succeeds when the candidate is valid.

## Check

`check [-r PATH]` discovers local identity, validates the registry, rejects an unknown or retired UUID, reads
`socket.gethostname()`, removes whitespace/trailing dot/FQDN suffix, and compares the lower-case short name. Case-only
Windows presentation is not drift. A mismatch that equals the record's previous hostname says so explicitly. Output on
success includes identity path, UUID, registry name, raw actual name, expected FQDN, and match status. It makes no network,
Git, DNS, or mutation call.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success. |
| 1 | Generic expected operational error. |
| 2 | CLI usage error. |
| 3 | Local identity not initialized. |
| 4 | Both local identity files exist. |
| 5 | Registry selector or local UUID not found. |
| 6 | Local hostname mismatch. |
| 7 | Local UUID or selected lifecycle target is retired. |
| 8 | Invalid or non-canonical registry. |
| 9 | Elevated privilege required. |
| 10 | Concurrent registry modification detected. |
| 11 | Unsupported platform or hostname-read failure. |

Known operational errors are printed concisely to stderr without tracebacks. Usage diagnostics remain Typer/Click code 2.
