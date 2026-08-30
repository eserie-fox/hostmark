# hostmark

`hostmark` is a cross-platform CLI for a stable local host identity and a Git-managed canonical hostname registry. It
stores one UUIDv4 on each operating-system instance, maps that identifier to an intended short hostname, and reports
hostname drift on demand. It never changes the operating-system hostname, DNS, Cloudflare, or startup settings. Its
bounded Git support initializes, clones, or fast-forwards the inventory repository only when explicitly requested.

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

Create the first private inventory repository at the platform-specific user default. The `--site` option is repeatable.

```bash
hostmark repo init \
  --dns-suffix node.infra.example.com \
  --site nc1
hostmark repo path
```

Change into the Repository directory printed by `hostmark repo path`, then run:

```bash
git add .gitattributes HOSTMARK_REPOSITORY hosts.json
git commit -m "Initialize hostmark repository"
git remote add origin <remote-url>
git push -u origin main
```

`repo init` creates an unborn `main` branch, canonical `.gitattributes`, an empty marker, and a canonical empty registry.
It does not stage, commit, configure a remote, or push, and it is not sync-ready until those three files are committed.

On another machine, install Hostmark 0.2.0, create that machine's identity, and record its UUID before cloning. On
Windows, run `identity init` without `--sudo` from an elevated terminal.

```bash
hostmark identity init --sudo
hostmark identity show --raw
hostmark repo sync --remote <remote-url>
hostmark repo path
```

Change into the Repository directory printed by `hostmark repo path`, then register, review, and publish the record:

```bash
hostmark registry register nc1-example-01
git diff -- hosts.json
hostmark registry validate --registry hosts.json
git add hosts.json
git commit -m "Register nc1-example-01"
git push
hostmark check
```

If the machine's current OS hostname differs from the registered name, this first check is expected to report drift.
Manually change the OS hostname to the canonical registry hostname, reboot or re-login when the operating system
requires it, and run `hostmark check` again until it succeeds. Hostmark detects this mismatch; it never changes the OS
hostname.

System scope is recommended and normally requires elevation on Linux and macOS.
Before sudo elevation, Hostmark checks both the system path and the invoking user's path; see
[platform identity storage](docs/platform-identity.md) for the duplicate-prevention details.

```bash
# Explicit fallback when system scope is unsuitable:
hostmark identity init --scope user
```

Never initialize a host ID in a VM template or generic system image. Each clone must generate its own identity after it
becomes an independent operating-system instance.

An administrator may pre-register another machine only after obtaining the UUID generated on that machine. The
administrator must use that exact value with `--host-id`, never invent a replacement UUID for the target machine:

```bash
hostmark registry register nc1-fox-01 \
  --host-id f0c5ebce-b37e-45d5-9f62-5c5a12f25116
```

The target then synchronizes the repository and follows the same hostname mismatch, manual remediation, and final
`hostmark check` flow.

Rename the same identity in the registry first:

```bash
hostmark registry rename nc1-fox-01 nc1-fox-02 --dry-run
hostmark registry rename nc1-fox-01 nc1-fox-02
git diff -- hosts.json
hostmark check  # expected mismatch
# Manually change the operating-system hostname after review.
hostmark check  # must now succeed
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
hostmark registry format --registry hosts.json
hostmark registry validate --registry hosts.json
hostmark registry validate \
  --registry hosts.json \
  --against /tmp/hosts.base.json
git diff -- hosts.json
```

`registry format --check` only checks bytes. Formatting can reorder canonical arrays and object fields, but it refuses
semantic errors and never repairs identity or lifecycle data.

The normal read-only daily sequence is explicit:

```bash
hostmark repo sync && hostmark check
```

`repo sync` requires the three repository metadata/data files to be tracked, rejects tracked changes, ignores unrelated
untracked files, pulls only the current `origin/*` upstream with fast-forward-only semantics, validates `hosts.json`,
and never pushes. Hostmark uses GitPython as a typed interface to system Git, so the user's credential helpers and SSH
configuration remain authoritative. `check` itself never invokes Git or performs network access. See the
[repository workflow](docs/repository.md) for discovery defaults, authentication behavior, and v0.1 migration.

## Scope and non-goals

Hostmark stores only UUID identity, hostname history, lifecycle metadata, sites, notes, and the DNS suffix used to compute
`hostname + "." + dns_suffix`. It deliberately excludes IP addresses, MAC addresses, DHCP, hypervisors, service names,
service domains, ports, DNS records, Cloudflare, credentials, reachability, and monitoring. There is no daemon, boot-time
service, automatic hostname remediation, automatic Git commit/push, network probe, central server, database, identity
reset, host deletion, unretirement, or hostname allocation/reuse command.

See [the CLI reference](docs/cli.md), [schema reference](docs/registry-schema.md), and
[lifecycle guide](docs/lifecycle.md) for the complete contract.
