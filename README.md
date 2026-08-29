# hostmark

`hostmark` is a cross-platform CLI for a stable local host identity and a Git-managed canonical hostname registry. It
stores one UUIDv4 on each operating-system instance, maps that identifier to an intended short hostname, and reports
hostname drift on demand. It never changes the operating-system hostname, DNS, Cloudflare, Git, or startup settings.

The local UUID answers “which operating-system instance is this?” The registry hostname answers “what should this
instance be called?” A hostname can change while the UUID remains stable. A retired UUID and every hostname it has
owned remain as permanent tombstones. Host IDs are identifiers, not authentication credentials or secrets.

## Install from FoxPI

Hostmark is intended for the private FoxPI index, not public PyPI. Configure the index and authenticate with placeholders
or an interactive credential store; never put a real password in a repository or command history.

```bash
uv auth login foxpi.foxenz.com --username <foxpi-username>
uv tool install hostmark \
  --index https://foxpi.foxenz.com/publisher/prod/+simple/
```

For development from this checkout:

```bash
uv sync --extra dev
uv run hostmark --version
```

## Quick start

Create the real, private source-of-truth registry with your actual node suffix. The `--site` option is repeatable.

```bash
hostmark registry init \
  --registry registry/hosts.json \
  --dns-suffix <real-node-suffix> \
  --site nc1
```

Initialize the stable local identity. System scope is recommended and normally requires elevation on Linux and macOS.
Before sudo elevation, Hostmark checks both the system path and the invoking user's path; see
[platform identity storage](docs/platform-identity.md) for the duplicate-prevention details.

```bash
hostmark identity init --sudo
# Explicit fallback when system scope is unsuitable:
hostmark identity init --scope user
```

Never initialize a host ID in a VM template or generic system image. Each clone must generate its own identity after it
becomes an independent operating-system instance.

Register the current machine, using its discovered local identity:

```bash
hostmark registry register nc1-orange --registry registry/hosts.json
hostmark check --registry registry/hosts.json
```

An administrator can register another machine using a synthetic-style explicit ID:

```bash
hostmark registry register nc1-fox-01 \
  --host-id f0c5ebce-b37e-45d5-9f62-5c5a12f25116 \
  --registry registry/hosts.json
```

Rename the same identity in the registry first:

```bash
hostmark registry rename nc1-fox-01 nc1-fox-02 --dry-run
hostmark registry rename nc1-fox-01 nc1-fox-02
git diff -- registry/hosts.json
hostmark check --registry registry/hosts.json  # expected mismatch
# Manually change the operating-system hostname after review.
hostmark check --registry registry/hosts.json  # must now succeed
```

Commit and review the registry update before changing the operating-system hostname. The first `check` deliberately
exposes drift; the second confirms the manual OS change. Hostmark never performs that change itself.

Retire an ended identity, optionally recording its active replacement:

```bash
hostmark registry retire nc1-fox-01 \
  --reason "Rebuilt as a new VM" \
  --replacement nc1-fox-02
```

## Manual registry workflow

Registry files are ordinary JSON designed for Git review. Before editing, inspect the record and preserve all required
fields. Never delete host tombstones or reuse names. After editing, canonicalize and validate the candidate, then compare
it with the authoritative base revision:

```bash
hostmark registry format --registry registry/hosts.json
hostmark registry validate --registry registry/hosts.json
hostmark registry validate \
  --registry registry/hosts.json \
  --against /tmp/hosts.base.json
git diff -- registry/hosts.json
```

`registry format --check` only checks bytes. Formatting can reorder canonical arrays and object fields, but it refuses
semantic errors and never repairs identity or lifecycle data.

## Scope and non-goals

Hostmark stores only UUID identity, hostname history, lifecycle metadata, sites, notes, and the DNS suffix used to compute
`hostname + "." + dns_suffix`. It deliberately excludes IP addresses, MAC addresses, DHCP, hypervisors, service names,
service domains, ports, DNS records, Cloudflare, credentials, reachability, and monitoring. There is no daemon, boot-time
service, automatic hostname remediation, Git automation, network probe, central server, database, identity reset, host
deletion, unretirement, or hostname allocation/reuse command.

See [the CLI reference](docs/cli.md), [schema reference](docs/registry-schema.md), and
[lifecycle guide](docs/lifecycle.md) for the complete contract.
