# Architecture

## State model

Hostmark separates local observed identity from Git-managed expected state.

1. Each managed OS instance owns a canonical UUIDv4 in one fixed local file.
2. A JSON registry maps that UUID to its intended canonical short hostname and lifecycle state.
3. `hostmark check` reads both sides plus `socket.gethostname()`, normalizes the actual short name, and reports drift.

The UUID survives ordinary hostname changes. It is not a credential and grants no access. The registry is the historical
source of truth, so an active record can be renamed, while a retired record and all names it owned remain permanent.

The node FQDN is computed as `hostname + "." + dns_suffix`; it is never redundantly stored.

## Data boundary

The registry intentionally excludes IP and MAC addresses, DHCP state, hypervisor placement, ports, services, service
domains, Cloudflare records, DDNS, credentials, runtime reachability, and monitoring. Those values have different owners
and change rates. Putting them here would blur stable identity and intended naming with network discovery and service
routing.

The Python package contains the parser, invariants, services, and CLI. Private inventory lives in the repository's
`registry/hosts.json` after an operator creates it. Setuptools, `MANIFEST.in`, CI, and artifact tests exclude the entire
`registry/` directory from both wheel and sdist. The package therefore cannot embed either real inventory or the example
registry.

## Runtime flow

- The CLI layer parses options and presents deterministic user-facing output.
- Domain models define the exact Pydantic shapes and known error taxonomy.
- Validation services enforce snapshot and historical invariants and produce canonical bytes.
- Identity and registry stores own filesystem behavior, including exclusive identity creation and optimistic atomic
  registry replacement.
- Host-state services own hostname normalization and read-only comparison.

Every ordinary mutation starts from canonical bytes, retains their SHA-256 identity, applies one pure transition,
validates and serializes the candidate, rechecks the source, atomically replaces it, and validates the result again.

## Deliberate operational limits

Hostmark runs only when invoked. It has no daemon, scheduler, startup installer, DNS request, reachability probe, or Git
invocation. Drift detection does not remediate anything. Operators decide when to change an OS hostname and when to
commit registry changes.
